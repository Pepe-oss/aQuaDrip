"""ElevationExtractor — 从 DEM 栅格提取节点高程并写回 aqd_nodes 图层

使用 QGIS 原生 QgsRasterDataProvider.sample()。
节点与 DEM 的 CRS 可能不同（常见：节点 EPSG:4326 经纬度，
DEM UTM 投影），采样前用 QgsCoordinateTransform 做坐标转换。
"""

from typing import Optional

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer,
    QgsPointXY, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
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

        # 3. 构造 CRS 变换：节点 CRS → DEM CRS
        node_crs = node_layer.crs()
        dem_crs = dem_layer.crs()
        xform = None
        if node_crs.isValid() and dem_crs.isValid() \
                and node_crs != dem_crs:
            xform = QgsCoordinateTransform(node_crs, dem_crs, self.project)

        features = list(node_layer.getFeatures())
        total = len(features)
        if total == 0:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "aqd_nodes 图层中没有节点")
            return {"updated": 0, "skipped": 0, "total": 0}

        # 4. 创建进度条
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
                sample_pt = QgsPointXY(pt.x(), pt.y())
                # 若节点与 DEM CRS 不同，转换坐标
                if xform is not None:
                    sample_pt = xform.transform(sample_pt)

                value, valid = provider.sample(sample_pt, 1)

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

        # 5. 修正水源水头
        #    若 DEM 高程远大于水源默认头（20m），水无法"爬"到节点位置。
        #    自动将水源水头设为最高节点高程 + 安全裕量，保证全管网正压供水。
        #    WNTR 中 Reservoir.base_head 是总水力坡度线高程，必须 > 下游节点高程。
        source_fixed = False
        if elevations:
            max_elev = max(elevations)
            source_fixed = self._fix_source_head(
                node_layer, max_elev, min_head_margin=20.0)

        # 6. 报告
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

        msg = (
            f"高程提取完成: {updated}/{total} 个节点已更新 "
            f"（范围 {stats['min']:.1f}~{stats['max']:.1f} m，"
            f"均值 {stats['mean']:.1f} m）")
        if source_fixed:
            msg += f"  🔧 水源水头已自动修正"
        self.iface.messageBar().pushMessage(
            "aQuaDrip", msg, level=0, duration=8)
        return stats

    # ── 水源水头修正 ──

    def _fix_source_head(self, node_layer: QgsVectorLayer,
                          max_elev: float,
                          min_head_margin: float = 20.0) -> bool:
        """将水源水头自动修正为 ≥ 最高节点高程 + 裕量。

        水源水头（Reservoir.base_head）必须大于所有下游节点高程才能保证
        正压供水。默认水源水头 20m，在 DEM 高程 ~1500m 时不适用。

        Returns:
            True if source head was modified.
        """
        need_edit = not node_layer.isEditable()
        if need_edit:
            node_layer.startEditing()
        try:
            modified = False
            for feat in node_layer.getFeatures():
                ntype = self._safe_attr(feat, "node_type", "junction")
                if ntype != "source":
                    continue
                old_head = float(self._safe_attr(feat, "head") or 20)
                source_elev = float(self._safe_attr(feat, "elevation") or 0)
                # 水源总头至少 = max(源高程, 最高下游高程) + 裕量
                required = max(source_elev, max_elev) + min_head_margin
                if old_head < required:
                    feat.setAttribute("head", required)
                    node_layer.updateFeature(feat)
                    modified = True
            if need_edit:
                node_layer.commitChanges()
        except Exception:
            if need_edit:
                node_layer.rollBack()
            raise
        return modified

    @staticmethod
    def _safe_attr(feat, name, default=None):
        idx = feat.fields().lookupField(name)
        if idx < 0:
            return default
        val = feat.attribute(idx)
        return default if val is None else val

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
