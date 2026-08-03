"""ElevationExtractor — 从 DEM 栅格提取节点高程并写回 aqd_nodes 图层

使用 QGIS 原生 QgsRasterDataProvider.sample()，自动处理 DEM 与矢量
图层的 CRS 差异，无需手动投影。
"""

from typing import Optional

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer,
    QgsPointXY,
)
from qgis.PyQt.QtWidgets import QProgressBar


class ElevationExtractor:
    """从项目中的 DEM 栅格图层提取所有节点高程"""

    def __init__(self, iface):
        self.iface = iface
        self.project = QgsProject.instance()

    def run(self) -> dict:
        """主入口：查找 DEM → 采样高程 → 写回图层

        Returns:
            {"updated": int, "skipped": int, "total": int,
             "min": float, "max": float, "mean": float}
        """
        # 1. 查找 DEM 图层
        dem_layer = self._find_dem_layer()
        if dem_layer is None:
            self.iface.messageBar().pushWarning(
                "aQuaDrip",
                "未找到 DEM 图层。请先在「新建项目」中导入 DEM 栅格文件。")
            return {"updated": 0, "skipped": 0, "total": 0}

        provider = dem_layer.dataProvider()
        if provider is None:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "无法读取 DEM 数据")
            return {"updated": 0, "skipped": 0, "total": 0}

        # 2. 查找 aqd_nodes 图层
        node_layer = self._find_node_layer()
        if node_layer is None:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "未找到 aqd_nodes 图层")
            return {"updated": 0, "skipped": 0, "total": 0}

        features = list(node_layer.getFeatures())
        total = len(features)
        if total == 0:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "aqd_nodes 图层中没有节点")
            return {"updated": 0, "skipped": 0, "total": 0}

        # 3. 创建进度条
        bar = QProgressBar()
        bar.setMaximum(total)
        bar_msg = self.iface.messageBar().createMessage(
            "aQuaDrip", f"正在提取 {total} 个节点的高程...")
        bar_msg.layout().addWidget(bar)
        self.iface.messageBar().pushWidget(bar_msg, level=0)

        try:
            updated = 0
            skipped = 0
            elevations = []

            node_layer.startEditing()

            for i, feat in enumerate(features):
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    skipped += 1
                    continue

                pt = geom.asPoint()
                value, valid = provider.sample(
                    QgsPointXY(pt.x(), pt.y()), 1)

                if valid:
                    elev = float(value)
                    feat.setAttribute("elevation", elev)
                    elevations.append(elev)
                    updated += 1
                else:
                    skipped += 1

                node_layer.updateFeature(feat)

                # 每 200 个节点更新一次进度
                if i % 200 == 0:
                    bar.setValue(i)

            node_layer.commitChanges()
            node_layer.triggerRepaint()
            bar.setValue(total)

        finally:
            self.iface.messageBar().clearWidgets()

        # 4. 报告
        if elevations:
            stats = {
                "updated": updated, "skipped": skipped, "total": total,
                "min": min(elevations), "max": max(elevations),
                "mean": sum(elevations) / len(elevations),
            }
        else:
            stats = {
                "updated": 0, "skipped": skipped, "total": total,
                "min": 0, "max": 0, "mean": 0,
            }

        self.iface.messageBar().pushMessage(
            "aQuaDrip",
            f"高程提取完成: {updated}/{total} 个节点已更新 "
            f"（范围 {stats['min']:.1f}~{stats['max']:.1f} m，"
            f"均值 {stats['mean']:.1f} m）",
            level=0, duration=8)
        return stats

    # ── 图层查找 ──

    def _find_dem_layer(self) -> Optional[QgsRasterLayer]:
        """查找项目中的 DEM 栅格图层，按优先级匹配。

        优先级: 名称=="DEM 高程" > 名称含"DEM" > 任意栅格图层
        """
        rasters = []
        for _lid, layer in self.project.mapLayers().items():
            if not isinstance(layer, QgsRasterLayer):
                continue
            if layer.name() == "DEM 高程":
                return layer
            rasters.append(layer)

        for layer in rasters:
            if "dem" in layer.name().lower():
                return layer

        if rasters:
            return rasters[0]
        return None

    def _find_node_layer(self) -> Optional[QgsVectorLayer]:
        """查找 aqd_nodes 矢量图层。"""
        for _lid, layer in self.project.mapLayers().items():
            if not isinstance(layer, QgsVectorLayer):
                continue
            src = layer.source() if hasattr(layer, "source") else ""
            if "aqd_nodes" in src or layer.name() == "aqd_nodes":
                return layer
        return None
