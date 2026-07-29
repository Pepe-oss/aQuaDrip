"""RectangularLayoutBuilder — 矩形地块规则布局生成器

支持四种耕作模式：
- uniform: 等行距
- wide_narrow: 宽窄行交替
- ridge_count: 按垄数
- custom: 自定义行距
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from wdrip.topology import TopologyGraph, TopologyLevel
from wdrip.network import FieldInfo
from .base import LayoutBuilder, LayoutParams


@dataclass
class LateralPosition:
    """毛管位置信息"""
    index: int
    lateral_id: str
    start_junction_id: str
    emitter_count: int
    emitter_ids: List[str]
    # 位置信息（用于后续几何层）
    y_offset: float         # 垂直于种植方向的位置偏移
    start_x: float = 0.0    # 毛管起点的 x 坐标
    end_x: float = 100.0    # 毛管终点的 x 坐标
    ridge_number: Optional[int] = None  # 垄号


class RectangularLayoutBuilder(LayoutBuilder):
    """矩形地块规则布局构建器
    
    假设矩形地块已旋转对齐坐标轴，
    种植方向沿 X 轴，毛管沿 Y 轴方向生成。
    """
    
    def build_topology(self, field: FieldInfo, params: LayoutParams) -> TopologyGraph:
        self.graph = TopologyGraph()
        self.field = field
        self.params = params
        
        # 确定参数（params 优先，fallback 到 field）
        pattern = params.planting_pattern or field.planting_pattern
        row_spacings = params.row_spacings or field.row_spacings
        ridge_count = params.ridge_count or field.ridge_count
        emitter_spacing = params.emitter_spacing or field.emitter_spacing
        lateral_spacing = params.lateral_spacing or field.effective_lateral_spacing
        
        # 从 field geometry 获取地块尺寸
        width, length = self._get_field_dimensions()
        
        # 1. 计算毛管位置
        lateral_positions = self._compute_lateral_positions(
            width, pattern, row_spacings, ridge_count, lateral_spacing
        )
        
        # 2. 为每条毛管生成拓扑结构
        for pos in lateral_positions:
            self._build_lateral_topology(pos, length, emitter_spacing)

        # 3. 生成干管（简化占位，见 _build_mainline_topology 说明）
        self._build_mainline_topology(length)

        # 4. 生成支管（简化占位，见 _build_submain_topology 说明）
        self._build_submain_topology(length)

        return self.graph
    
    def _get_field_dimensions(self) -> Tuple[float, float]:
        """获取地块尺寸（宽度、长度）"""
        # 实际场景从 field.geometry 计算
        # 当前使用默认值
        return 50.0, 100.0  # width=50m, length=100m
    
    def _compute_lateral_positions(
        self,
        width: float,
        pattern: str,
        row_spacings: List[float],
        ridge_count: Optional[int],
        lateral_spacing: float,
    ) -> List[LateralPosition]:
        """计算毛管位置"""
        positions = []
        
        if pattern == "uniform":
            # 等行距：从 0 开始以 fixed_spacing 递增
            spacing = lateral_spacing or row_spacings[0]
            y = spacing / 2  # 从中间偏移开始
            idx = 0
            while y < width:
                lateral_id = self._generate_lateral_id(idx)
                positions.append(LateralPosition(
                    index=idx,
                    lateral_id=lateral_id,
                    start_junction_id=self._generate_junction_id(lateral_id),
                    emitter_count=0,
                    emitter_ids=[],
                    y_offset=y,
                ))
                y += spacing
                idx += 1
        
        elif pattern == "wide_narrow":
            # 宽窄行交替
            y = 0
            idx = 0
            while y < width:
                spacing = row_spacings[idx % len(row_spacings)]
                y += spacing / 2  # 从行中间
                if y < width:
                    lateral_id = self._generate_lateral_id(idx)
                    positions.append(LateralPosition(
                        index=idx,
                        lateral_id=lateral_id,
                        start_junction_id=self._generate_junction_id(lateral_id),
                        emitter_count=0,
                        emitter_ids=[],
                        y_offset=y,
                    ))
                y += spacing / 2
                idx += 1
        
        elif pattern == "ridge_count":
            # 垄数：宽度等分
            if ridge_count and ridge_count > 0:
                spacing = width / ridge_count
                for i in range(ridge_count):
                    y = spacing * (i + 0.5)  # 每垄中间
                    lateral_id = self._generate_lateral_id(i)
                    positions.append(LateralPosition(
                        index=i,
                        lateral_id=lateral_id,
                        start_junction_id=self._generate_junction_id(lateral_id),
                        emitter_count=0,
                        emitter_ids=[],
                        y_offset=y,
                        ridge_number=i + 1,
                    ))
        
        elif pattern == "custom":
            # 自定义：使用用户指定的精确位置
            for idx, y in enumerate(row_spacings):
                if y < width:
                    lateral_id = self._generate_lateral_id(idx)
                    positions.append(LateralPosition(
                        index=idx,
                        lateral_id=lateral_id,
                        start_junction_id=self._generate_junction_id(lateral_id),
                        emitter_count=0,
                        emitter_ids=[],
                        y_offset=y,
                    ))
        
        return positions
    
    def _build_lateral_topology(
        self,
        pos: LateralPosition,
        length: float,
        emitter_spacing: float,
    ):
        """为单条毛管生成拓扑
        
        结构：J_start ── Emitter_1 ── Emitter_2 ── ... ── Emitter_N
              ↑                                        ↑
           支管连接点                                 毛管末端
        """
        # 计算滴头数量
        n_emitters = max(1, int(length / emitter_spacing))
        
        # 创建毛管起始 Junction（用于连接支管）
        self.graph.add_node(pos.start_junction_id, level=TopologyLevel.LATERAL)
        
        # 生成 EmitterNode ID 列表
        emitter_ids = []
        for i in range(n_emitters):
            eid = self._generate_emitter_id(pos.lateral_id, i)
            emitter_ids.append(eid)
            self.graph.add_node(eid, level=TopologyLevel.LATERAL)
        
        # 创建毛管边（每两个相邻节点之间一条边）
        # 起始 Junction → 第一个 Emitter
        self.graph.add_edge(
            f"{pos.lateral_id}_seg_0",
            pos.start_junction_id,
            emitter_ids[0],
            edge_type="pipe",
            level=TopologyLevel.LATERAL,
        )
        
        # 相邻 Emitter 之间
        for i in range(len(emitter_ids) - 1):
            self.graph.add_edge(
                f"{pos.lateral_id}_seg_{i+1}",
                emitter_ids[i],
                emitter_ids[i+1],
                edge_type="pipe",
                level=TopologyLevel.LATERAL,
            )
        
        # 更新位置信息
        pos.emitter_count = n_emitters
        pos.emitter_ids = emitter_ids
        pos.end_x = length
    
    def _build_mainline_topology(self, length: float):
        """生成干管拓扑（**简化占位实现**）

        仅生成一条 M_SRC→M_END 的单线干管，忽略 LayoutParams.mainline_strategy。

        注意：生产环境中干管采用**手动绘制范式**（用户在 QGIS 的
        aqd_pipes 图层中绘制，pipe_type=mainline）。此方法仅为
        端到端拓扑测试（test_topology / test_integration）保留，
        不代表最终的干管布局算法。文档 7.3 的沿长边/短边/中央/边界
        等策略未在此实现。
        """
        # 简单模式：一条干管沿地块长边
        mainline_id = "M001"
        mainline_start = "M_SRC"
        mainline_end = "M_END"
        
        self.graph.add_node(mainline_start, level=TopologyLevel.MAINLINE)
        self.graph.add_node(mainline_end, level=TopologyLevel.MAINLINE)
        self.graph.add_edge(
            mainline_id, mainline_start, mainline_end,
            edge_type="pipe",
            level=TopologyLevel.MAINLINE,
        )
    
    def _build_submain_topology(self, length: float):
        """生成支管拓扑（**简化占位实现**）

        把每条毛管的起始 Junction 直连到单一节点 M_END，忽略
        LayoutParams.submain_strategy / submain_spacing。

        注意：生产环境中支管采用**手动绘制范式**（用户在 QGIS 中绘制，
        交叉节点由插件 aquadrip-plugin/tools/crossing_node_tool.py 在
        支管与毛管的几何交点处生成）。此方法仅为端到端拓扑测试保留，
        文档 7.3.3 的"交叉-连接"等距/MST/骨架线/最短路策略未在此实现。
        """
        # 对于每条毛管，从干管引出一条支管连接到毛管的起始 Junction
        submain_count = 0
        for pos in self._get_lateral_positions():
            submain_id = f"S{submain_count:04d}"
            # 支管从干管末端连接到毛管起始 Junction
            self.graph.add_edge(
                submain_id,
                "M_END",
                pos.start_junction_id,
                edge_type="pipe",
                level=TopologyLevel.SUBMAIN,
            )
            submain_count += 1
    
    def _get_lateral_positions(self) -> List[LateralPosition]:
        """从 graph 中恢复毛管位置信息"""
        # 从节点的 adjacency 推断
        positions = []
        for nid, node in self.graph.nodes.items():
            if nid.startswith("J_L") and nid.endswith("_start"):
                positions.append(LateralPosition(
                    index=0,
                    lateral_id=nid.replace("J_", "").replace("_start", ""),
                    start_junction_id=nid,
                    emitter_count=0,
                    emitter_ids=[],
                    y_offset=0,
                ))
        return positions
    
    def get_position_data(self) -> List[LateralPosition]:
        """获取毛管位置数据（用于后续几何层赋值）"""
        return self._positions if hasattr(self, '_positions') else []
