# -*- coding: utf-8 -*-
"""PipePressureChecker — 管道承压分析工具

读取最近一次模拟结果（sim_history）中的节点压力，与 aqd_pipes 图层中
每条管道的 max_pressure（最大承压）对比，标记超压泄漏风险位置。

判定规则：
  pipe_pressure = max(from_node压力, to_node压力)
  ratio = pipe_pressure / max_pressure
  - ratio > 1.0  → leak    (超压，可能有泄漏风险)
  - 0.8 ~ 1.0    → warning (接近承压极限)
  - < 0.8        → safe    (安全)
  - max_pressure = 0 → unset (未设置承压，跳过)
"""

from typing import Dict, Optional

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRendererCategory, QgsSymbol,
    QgsCategorizedSymbolRenderer, QgsFeature,
)
from qgis.PyQt.QtGui import QColor


class PipePressureChecker:
    """管道承压分析"""

    THRESHOLD = 0.8  # 80% 以上为 warning

    def __init__(self, iface):
        self.iface = iface

    def check(self):
        """主入口：读取压力 → 对比承压 → 写状态 + 着色"""
        # 1. 读取模拟结果
        pipe_layer = self._find_layer("aqd_pipes")
        if pipe_layer is None:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "未找到 aqd_pipes 图层")
            return

        node_pressure = self._load_node_pressure()
        if not node_pressure:
            self.iface.messageBar().pushWarning(
                "aQuaDrip",
                "未找到模拟结果，请先运行水力模拟并保存历史记录")
            return

        # 2. 逐管道判定
        statuses: Dict[int, str] = {}  # {fid: status}
        stats = {"leak": 0, "warning": 0, "safe": 0, "unset": 0}

        for feat in pipe_layer.getFeatures():
            mp = self._safe_float(feat, "max_pressure")
            if mp <= 0:
                statuses[feat.id()] = "unset"
                stats["unset"] += 1
                continue

            fn = str(feat.attribute("from_node") or "")
            tn = str(feat.attribute("to_node") or "")
            fp = node_pressure.get(fn, 0.0)
            tp = node_pressure.get(tn, 0.0)
            pipe_p = max(abs(fp), abs(tp))
            ratio = pipe_p / mp

            if ratio > 1.0:
                statuses[feat.id()] = "leak"
                stats["leak"] += 1
            elif ratio >= self.THRESHOLD:
                statuses[feat.id()] = "warning"
                stats["warning"] += 1
            else:
                statuses[feat.id()] = "safe"
                stats["safe"] += 1

        # 3. 写回 pressure_status 字段
        written = self._write_status(pipe_layer, statuses)
        pipe_layer.triggerRepaint()

        # 4. 分类着色
        self._apply_renderer(pipe_layer)

        # 5. 报告
        total = sum(stats.values())
        self.iface.messageBar().pushMessage(
            "aQuaDrip",
            f"承压分析: {stats['leak']}红/{stats['warning']}黄/{stats['safe']}绿/{stats['unset']}灰"
            f"（共{total}条）",
            level=0, duration=6)

    # ── 数据读取 ──

    def _load_node_pressure(self) -> Dict[str, float]:
        """从 sim_history 加载最新记录的 node_pressure"""
        from ..tools.layer_utils import find_gpkg_path
        gpkg_path = find_gpkg_path(None, "aqd_fields")
        if not gpkg_path:
            return {}
        from ..tools.sim_history import SimHistory
        h = SimHistory(gpkg_path)
        records = h.load()
        if not records:
            return {}
        return records[0].get("node_pressure", {})

    def _safe_float(self, feat: QgsFeature, fname: str,
                    default: float = 0.0) -> float:
        idx = feat.fields().lookupField(fname)
        if idx < 0:
            return default
        val = feat.attribute(idx)
        if val is None:
            return default
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    # ── 写回图层 ──

    @staticmethod
    def _ensure_field(layer: QgsVectorLayer, name: str):
        """确保图层存在指定字段（旧GPKG缺新字段时自动补建）"""
        if layer.fields().lookupField(name) >= 0:
            return
        from qgis.core import QgsField
        from qgis.PyQt.QtCore import QVariant
        field_type = QVariant.String if name.endswith("_status") else QVariant.Double
        layer.dataProvider().addAttributes([QgsField(name, field_type)])
        layer.updateFields()

    def _write_status(self, layer: QgsVectorLayer,
                      statuses: Dict[int, str]) -> int:
        # 确保字段存在（旧 GPKG 可能缺少新增字段）
        self._ensure_field(layer, "pressure_status")

        need_edit = not layer.isEditable()
        if need_edit:
            layer.startEditing()
        try:
            written = 0
            for fid, status in statuses.items():
                # 获取要素（通过 fid 循环比 getFeatures 更高效但需要 rebuild）
                for feat in layer.getFeatures():
                    if feat.id() == fid:
                        feat.setAttribute("pressure_status", status)
                        layer.updateFeature(feat)
                        written += 1
                        break
            if need_edit and not layer.commitChanges():
                layer.rollBack()
                self.iface.messageBar().pushWarning(
                    "aQuaDrip", "承压状态写入失败")
                return 0
        except Exception:
            if need_edit:
                layer.rollBack()
            raise
        return written

    # ── 着色 ──

    def _apply_renderer(self, pipe_layer: QgsVectorLayer):
        categories = []
        geom_type = pipe_layer.geometryType()

        color_schemes = [
            ("leak", "超压泄漏风险", QColor(220, 50, 50), 1.8),   # 红
            ("warning", "接近承压极限", QColor(255, 170, 0), 1.4),  # 橙
            ("safe", "安全", QColor(50, 180, 60), 0.8),             # 绿
            ("unset", "未设置承压", QColor(180, 180, 180), 0.6),    # 灰
        ]

        for status, label, color, width in color_schemes:
            symbol = QgsSymbol.defaultSymbol(geom_type)
            symbol.setColor(color)
            symbol.setWidth(width)
            categories.append(
                QgsRendererCategory(status, symbol, label))

        renderer = QgsCategorizedSymbolRenderer(
            "pressure_status", categories)
        pipe_layer.setRenderer(renderer)

    # ── 图层查找 ──

    def _find_layer(self, key: str) -> Optional[QgsVectorLayer]:
        from .layer_utils import find_layer
        return find_layer(QgsProject.instance(), key)
