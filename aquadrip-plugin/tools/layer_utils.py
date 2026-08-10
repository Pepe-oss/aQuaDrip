# -*- coding: utf-8 -*-
"""图层查找与编辑事务的公共工具模块

历史上 aQuaDrip 的图层查找代码在 11 个文件、18 个函数中重复实现，
且匹配逻辑存在细微不一致（有的只查 source，有的查 source or name，
有的忘记过滤 QgsVectorLayer），导致用户重命名图层时不同工具行为割裂。

本模块提供统一的查找 / 安全属性读取 / 编辑会话上下文管理器，
作为 tools/ 与 ui/ 各类的单一来源。
"""

import contextlib
from typing import Optional, Union


# ── 图层查找 ──

def find_layer(project, key: str, *, match_source: bool = True,
               match_name: bool = True):
    """从项目已加载图层中查找矢量图层（按 name 或 source 匹配）

    统一了过去散落在 18 处的查找逻辑。默认同时匹配 source 和 name
    （最宽松，覆盖用户重命名图层的场景）。

    Args:
        project: QgsProject 实例（传 None 则用 QgsProject.instance()）
        key: 图层标识，如 "aqd_pipes" / "aqd_nodes" / "aqd_fields"
        match_source: 是否检查 key 出现在 layer.source() 中
        match_name: 是否检查 layer.name() == key

    Returns:
        QgsVectorLayer 或 None
    """
    if project is None:
        from qgis.core import QgsProject
        project = QgsProject.instance()

    from qgis.core import QgsVectorLayer
    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        src = layer.source() if hasattr(layer, "source") else ""
        name = layer.name() if hasattr(layer, "name") else ""
        if (match_source and key in src) or (match_name and name == key):
            return layer
    return None


def find_layers(project, *keys):
    """一次性查找多个图层，返回 {key: layer} 字典（未找到的 key 不含在结果中）

    避免 rotation_scheduler._find_layers 那样手写多分支循环。
    """
    if project is None:
        from qgis.core import QgsProject
        project = QgsProject.instance()

    found = {}
    for key in keys:
        layer = find_layer(project, key)
        if layer is not None:
            found[key] = layer
    return found


def find_gpkg_path(project=None, key: str = "aqd_fields") -> Optional[str]:
    """从项目图层的 source 中提取 GPKG 文件路径

    source 格式: /path/to/aquadrip.gpkg|layername=aqd_fields
    用 "|" 分割取第一段，并校验以 .gpkg 结尾。

    Args:
        project: QgsProject 实例（None 则用 QgsProject.instance()）
        key: 用于定位的图层标识，默认 aqd_fields（最稳定）

    Returns:
        GPKG 文件绝对路径，或 None（未找到）
    """
    layer = find_layer(project, key)
    if layer is None:
        return None
    src = layer.source() or ""
    gpkg_path = src.split("|")[0]
    if gpkg_path.endswith(".gpkg"):
        return gpkg_path
    return None


# ── 安全属性读取 ──

def attr(feat, name: str, default=None):
    """安全读取要素字段值（字段不存在或 NULL 时返回 default）

    基于 lookupField + 整数索引，对缺失字段 / None 值稳健，
    兼容不同 QGIS 版本（attribute(name) 在某些版本会抛 KeyError）。
    """
    idx = feat.fields().lookupField(name)
    if idx < 0:
        return default
    val = feat.attribute(idx)
    return default if val is None else val


def safe_float(feat, name: str, default: float = 0.0) -> float:
    """安全读取 float 字段"""
    val = attr(feat, name, None)
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def safe_int(feat, name: str, default: int = 0) -> int:
    """安全读取 int 字段"""
    val = attr(feat, name, None)
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def safe_str(feat, name: str, default: str = "") -> str:
    """安全读取字符串字段（结果已 strip）"""
    val = attr(feat, name, None)
    if val is None:
        return default
    return str(val).strip()


# ── 编辑会话上下文管理器 ──

@contextlib.contextmanager
def edit_session(layer, on_commit_fail=None):
    """QGIS 图层编辑会话的上下文管理器

    正确处理：
    - 仅在图层未进入编辑模式时才 startEditing（避免抢占用户已开启的会话）
    - try 块抛异常时自动 rollBack，不提交半截脏数据
    - 检查 commitChanges() 返回值，失败时 rollBack 并通过 on_commit_fail 回调通知

    用法::

        with edit_session(layer) as ly:
            ly.updateFeature(feat)
            ly.addFeature(new_feat)

    Args:
        layer: QgsVectorLayer
        on_commit_fail: 可选回调，签名 callback(layer)，在 commitChanges
            返回 False 时调用（如记录日志或向 messageBar 推送警告）
    """
    need_edit = not layer.isEditable()
    if need_edit:
        layer.startEditing()
    try:
        yield layer
    except Exception:
        if need_edit:
            layer.rollBack()
        raise
    else:
        if need_edit:
            if layer.commitChanges():
                return
            # commit 失败：回滚并通知
            layer.rollBack()
            if on_commit_fail is not None:
                on_commit_fail(layer)
