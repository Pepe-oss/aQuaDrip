"""毛管展开 — 把 lateral Pipe 展开为 EmitterNode 滴头链

设计依据（DEVELOPMENT_PLAN.md 6.4 / 7.3.1）：
- 滴头（EmitterNode）由 wdrip-core 内部管理，用户在 QGIS 中只需画毛管线
- 毛管结构：J_start ── E1 ── E2 ── ... ── En（最后一个滴头即毛管末端）

展开规则：
- 第一个分段保留原 link_id（改为 from_node → E1），使
  DripNetwork.validate() 的 lateral_id 校验通过，且 QGIS 侧结果回写
  能按原 ID 匹配
- 原 to_node（毛管末端）原地升级为 EmitterNode（保持 id 不变），
  这样支管共享的交叉节点引用关系不受影响
- 滴头沿 from→to 直线等距分布（手画折线毛管按直线处理）
"""

import math
from typing import Dict, Optional

from .nodes import EmitterNode, SourceNode, DripNode
from .links import Pipe
from .emitter import BUILTIN_EMITTERS, EmitterSpec

# 默认滴头：Netafim DripperNet 16mm 1.6L/h（非 PC，k=0.506, x=0.5）
DEFAULT_EMITTER_KEY = "Netafim_DripperNet_16mm_1.6"


def expand_lateral(net, link_id: str,
                   emitter_spacing: float,
                   emitter_k: Optional[float] = None,
                   emitter_x: Optional[float] = None,
                   emitter_spec: Optional[EmitterSpec] = None) -> int:
    """把一条 lateral Pipe 展开为 EmitterNode 滴头链

    Args:
        net: DripNetwork
        link_id: 待展开的毛管 ID（必须是 pipe_type="lateral" 的 Pipe）
        emitter_spacing: 滴头间距（m），滴头数 n = max(1, int(L/spacing))
        emitter_k: 滴头流量系数（L/h / m^x），缺省用默认滴头
        emitter_x: 滴头流态指数，缺省用默认滴头
        emitter_spec: 关联的滴头规格（可选）

    Returns:
        生成的滴头数量

    Raises:
        KeyError: link 不存在
        ValueError: link 不是 lateral Pipe，或参数非法
    """
    link = net.get_link(link_id)
    if link is None:
        raise KeyError(f"管道 {link_id} 不存在")
    if getattr(link, "pipe_type", None) != "lateral":
        raise ValueError(f"管道 {link_id} 不是毛管（pipe_type=lateral）")
    if emitter_spacing <= 0:
        raise ValueError("滴头间距必须大于 0")

    # 默认滴头参数
    if emitter_k is None or emitter_x is None:
        spec = emitter_spec or BUILTIN_EMITTERS.get(DEFAULT_EMITTER_KEY)
        if spec is None:
            raise ValueError("未指定滴头参数且默认滴头库不可用")
        emitter_k = emitter_k if emitter_k is not None else spec.k
        emitter_x = emitter_x if emitter_x is not None else spec.x
        emitter_spec = spec

    a = net.get_node(link.from_node)
    b = net.get_node(link.to_node)
    if a is None or b is None:
        raise ValueError(f"毛管 {link_id} 的端点节点缺失")

    length = math.hypot(b.x - a.x, b.y - a.y)
    if length <= 0:
        raise ValueError(f"毛管 {link_id} 长度为零")

    n = max(1, int(length / emitter_spacing))
    seg_len = length / n  # 滴头等距分布，末端对齐

    if n == 1:
        # 只有一个滴头：原 to_node 升级为滴头，原 Pipe 保留
        _upgrade_to_emitter(net, b, link_id, 0,
                            emitter_k, emitter_x, emitter_spec)
        link.length = length
        return 1

    # n >= 2：中间滴头 E_1..E_{n-1}，末端 b 升级为滴头
    # 第一段保留原 link_id：from_node → E_1
    prev_id = a.id
    for i in range(1, n):
        t = i / n
        ex = a.x + (b.x - a.x) * t
        ey = a.y + (b.y - a.y) * t
        eid = f"E_{link_id}_{i:03d}"
        emitter = EmitterNode(
            eid, ex, ey, elevation=b.elevation,
            emitter_k=emitter_k, emitter_x=emitter_x,
            emitter_spec=emitter_spec,
            lateral_id=link_id, segment_index=i - 1,
        )
        net.add_node(emitter)

        if i == 1:
            # 原 Pipe 改接 E_1，保留 link_id
            link.to_node = eid
            link.length = seg_len
        else:
            net.add_link(Pipe(
                f"{link_id}_seg{i:03d}", prev_id, eid,
                pipe_type="lateral",
                diameter=link.diameter, length=seg_len,
                roughness=link.roughness, material=link.material,
            ))
        prev_id = eid

    # 末端：原 to_node 原地升级为滴头（保持 id，支管引用不受影响）
    _upgrade_to_emitter(net, b, link_id, n - 1,
                        emitter_k, emitter_x, emitter_spec)
    net.add_link(Pipe(
        f"{link_id}_seg{n:03d}", prev_id, b.id,
        pipe_type="lateral",
        diameter=link.diameter, length=length - (n - 1) * seg_len,
        roughness=link.roughness, material=link.material,
    ))

    return n


def expand_all_laterals(net,
                        spacings: Optional[Dict[str, float]] = None,
                        default_spacing: float = 0.3,
                        emitter_k: Optional[float] = None,
                        emitter_x: Optional[float] = None) -> Dict[str, int]:
    """展开 network 中所有毛管

    Args:
        net: DripNetwork
        spacings: 每条毛管的滴头间距 {link_id: spacing}，缺省用 default_spacing
        default_spacing: 默认滴头间距（m）
        emitter_k / emitter_x: 滴头参数（缺省用默认滴头）

    Returns:
        {link_id: 滴头数量}
    """
    lateral_ids = [
        lid for lid, link in net.links.items()
        if getattr(link, "pipe_type", None) == "lateral"
    ]
    result: Dict[str, int] = {}
    for lid in lateral_ids:
        spacing = (spacings or {}).get(lid, default_spacing)
        result[lid] = expand_lateral(
            net, lid, spacing, emitter_k, emitter_x)
    return result


def _upgrade_to_emitter(net, node: DripNode, lateral_id: str,
                        segment_index: int,
                        emitter_k: float, emitter_x: float,
                        emitter_spec: Optional[EmitterSpec]):
    """把节点原地升级为 EmitterNode（保持 id 不变）

    末端节点可能同时是支管共享的交叉节点，保持 id 不变可保证
    其他 link 的 from_node/to_node 引用仍然有效。
    SourceNode（水源）不升级。
    """
    if isinstance(node, SourceNode):
        return
    net.nodes[node.id] = EmitterNode(
        node.id, node.x, node.y, elevation=node.elevation,
        description=node.description, tag=node.tag,
        demand=getattr(node, "demand", 0.0),
        emitter_k=emitter_k, emitter_x=emitter_x,
        emitter_spec=emitter_spec,
        lateral_id=lateral_id, segment_index=segment_index,
    )
