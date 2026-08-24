# -*- coding: utf-8 -*-
"""PipePressureChecker — 管道承压分析工具

读取最近一次模拟结果（sim_history）中的节点压力，与 aqd_pipes 图层中
每条管道的 max_pressure（最大承压）对比，在**临时图层**中显示超压风险。

判定规则：
  pipe_pressure = max(from_node压力, to_node压力)
  ratio = pipe_pressure / max_pressure
  - ratio > 1.0  → leak    (超压，可能有泄漏风险)
  - 0.8 ~ 1.0    → warning (接近承压极限)
  - < 0.8        → safe    (安全)
  - max_pressure = 0 → unset (未设置承压，跳过)
  - 端点压力查不到  → unknown (未 sync 回写端点 / 历史缺该节点，
                      显式标记而非拿 0 误判 safe)

不修改原始 aqd_pipes 图层，结果写入临时内存图层「承压分析」。
"""

from typing import Dict, List, Optional

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
    QgsField, QgsRendererCategory, QgsSymbol,
    QgsCategorizedSymbolRenderer,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor

LAYER_NAME = "承压分析"


class PipePressureChecker:
    """管道承压分析（临时图层模式）"""

    THRESHOLD = 0.8  # 80% 以上为 warning

    def __init__(self, iface):
        self.iface = iface

    def check(self):
        """主入口：读取压力 → 对比承压 → 生成临时图层"""
        pipe_layer = self._find_layer("aqd_pipes")
        if pipe_layer is None:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "未找到 aqd_pipes 图层")
            return

        node_pressure, record_info = self._load_node_pressure()
        if not node_pressure:
            self.iface.messageBar().pushWarning(
                "aQuaDrip",
                "未找到模拟结果，请先运行水力模拟并保存历史记录")
            return

        # 轮灌模拟只含单分区节点压力，其余分区管道查不到压力 → 误判安全
        if record_info.get("rotation_id"):
            zone_name = record_info.get("zone", "?")
            self.iface.messageBar().pushWarning(
                "aQuaDrip",
                f"最新记录是轮灌分区 {zone_name} 的结果，仅含该分区压力。"
                f"建议先运行完整模拟（非轮灌）再做承压分析")
            return

        # 逐管道判定
        results: List[dict] = []
        stats = {"leak": 0, "warning": 0, "safe": 0, "unset": 0, "unknown": 0}

        for feat in pipe_layer.getFeatures():
            geom = feat.geometry()
            if not geom or geom.isEmpty():
                continue

            mp = self._safe_float(feat, "max_pressure")
            fn = self._safe_str(feat, "from_node")
            tn = self._safe_str(feat, "to_node")
            pipe_p = 0.0

            if mp <= 0:
                status = "unset"
            elif not fn or not tn or (
                    fn not in node_pressure and tn not in node_pressure):
                # 端点为空（未模拟回写 / 新增管道）或历史中查不到该节点：
                # 显式标记 unknown——拿 0 当压力会把所有管道误判 safe
                status = "unknown"
            else:
                fp = node_pressure.get(fn, 0.0)
                tp = node_pressure.get(tn, 0.0)
                pipe_p = max(abs(fp), abs(tp))
                ratio = pipe_p / mp
                if ratio > 1.0:
                    status = "leak"
                elif ratio >= self.THRESHOLD:
                    status = "warning"
                else:
                    status = "safe"

            stats[status] = stats.get(status, 0) + 1
            results.append({
                "geom": geom,
                "status": status,
                "max_pressure": mp,
                "actual_pressure": pipe_p,
            })

        if not results:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "管道图层中没有有效管道")
            return

        # 生成临时图层
        self._create_temp_layer(pipe_layer, results)

        total = sum(stats.values())
        self.iface.messageBar().pushMessage(
            "aQuaDrip",
            f"承压分析: {stats['leak']}红/{stats['warning']}黄/{stats['safe']}绿"
            f"/{stats['unknown']}蓝(压力未知)/{stats['unset']}灰"
            f"（共{total}条）",
            level=0, duration=6)

    # ── 临时图层 ──

    def _create_temp_layer(self, src_layer: QgsVectorLayer,
                           results: List[dict]):
        """创建临时内存图层显示承压分析结果"""
        project = QgsProject.instance()
        crs = src_layer.crs()
        crs_id = crs.authid() if crs.isValid() else "EPSG:4326"

        # 删除同名旧图层
        for lid, layer in list(project.mapLayers().items()):
            if layer.name() == LAYER_NAME:
                project.removeMapLayer(lid)

        layer = QgsVectorLayer(
            f"LineString?crs={crs_id}", LAYER_NAME, "memory")
        dp = layer.dataProvider()
        dp.addAttributes([
            QgsField("status", QVariant.String),
            QgsField("max_pressure", QVariant.Double),
            QgsField("actual_pressure", QVariant.Double),
        ])
        layer.updateFields()

        feats = []
        for r in results:
            feat = QgsFeature(layer.fields())
            feat.setGeometry(r["geom"])
            feat.setAttributes([
                r["status"], r["max_pressure"], r["actual_pressure"],
            ])
            feats.append(feat)

        dp.addFeatures(feats)

        # 分类着色
        self._apply_renderer(layer)
        project.addMapLayer(layer)
        layer.triggerRepaint()

    def _apply_renderer(self, layer: QgsVectorLayer):
        geom_type = layer.geometryType()
        categories = [
            ("leak", "超压泄漏风险", QColor(220, 50, 50), 1.8),
            ("warning", "接近承压极限", QColor(255, 170, 0), 1.4),
            ("safe", "安全", QColor(50, 180, 60), 0.8),
            ("unknown", "压力未知(未回写端点)", QColor(100, 149, 237), 0.6),
            ("unset", "未设置承压", QColor(180, 180, 180), 0.6),
        ]
        cats = []
        for status, label, color, width in categories:
            symbol = QgsSymbol.defaultSymbol(geom_type)
            symbol.setColor(color)
            symbol.setWidth(width)
            cats.append(QgsRendererCategory(status, symbol, label))

        layer.setRenderer(QgsCategorizedSymbolRenderer("status", cats))

    # ── 数据读取 ──

    def _load_node_pressure(self):
        """返回 (node_pressure_dict, record_info)"""
        from .layer_utils import find_gpkg_path
        gpkg_path = find_gpkg_path(None, "aqd_fields")
        if not gpkg_path:
            return {}, {}
        from .sim_history import SimHistory
        records = SimHistory(gpkg_path).load()
        if not records:
            return {}, {}
        rec = records[0]
        return rec.get("node_pressure", {}), rec

    @staticmethod
    def _safe_float(feat: QgsFeature, fname: str,
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

    @staticmethod
    def _safe_str(feat: QgsFeature, fname: str,
                  default: str = "") -> str:
        """容错读取字符串字段（旧 GPKG 缺字段时返回默认值）"""
        idx = feat.fields().lookupField(fname)
        if idx < 0:
            return default
        val = feat.attribute(idx)
        return str(val) if val is not None else default

    def _find_layer(self, key: str) -> Optional[QgsVectorLayer]:
        from .layer_utils import find_layer
        return find_layer(QgsProject.instance(), key)
