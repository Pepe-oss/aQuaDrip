"""SyncManager — QGIS 图层与 wdrip-core DripNetwork 双向同步

核心方法:
  sync_qgis_to_network()  — QGIS → DripNetwork
      读取农田/节点/管道 → 端点匹配节点（回写 from_node/to_node）
      → 毛管按 emitter_spacing 展开为 EmitterNode 滴头链
  sync_from_network()     — DripNetwork → QGIS（模拟结果回写）

单位约定（与 wdrip.network.links 一致）：
  - Pipe/Valve diameter: mm（WNTR 转换时在 core 内统一 /1000）
  - length: m（取几何长度）
  - 坐标/容差: 随图层 CRS（投影=米，经纬度=度，sync 时警告）
"""

import math
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer, QgsGeometry, QgsPointXY, QgsFeature,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
)
from qgis.PyQt.QtWidgets import QApplication

if TYPE_CHECKING:
    from wdrip.network import DripNetwork
    from wdrip.simulation.result import SimulationResult


class SyncManager:
    """QGIS ↔ DripNetwork 同步管理器"""

    def __init__(self, iface):
        self.iface = iface
        self.project = QgsProject.instance()

    # ── 字段安全读取 ──

    @staticmethod
    def _attr(feat: QgsFeature, name: str, default=None):
        """安全读取字段值（字段不存在或 NULL 时返回 default）

        委托给公共 layer_utils.attr，保持调用点不变。
        """
        from .layer_utils import attr
        return attr(feat, name, default)

    # ── 从 QGIS 读取 → 构建 DripNetwork ──

    def _all_link_layers(self) -> List[QgsVectorLayer]:
        """返回项目中的 aqd_pipes / aqd_pumps / aqd_valves（排除 None）。"""
        layers = []
        for key in ("aqd_pipes", "aqd_pumps", "aqd_valves"):
            ly = self._get_layer(key)
            if ly is not None:
                layers.append(ly)
        return layers

    def _features_from(self, layer: Optional[QgsVectorLayer]) -> List[QgsFeature]:
        if layer is None:
            return []
        return list(layer.getFeatures())

    def sync_qgis_to_network(self, expand: bool = True,
                             split_vertices: bool = False) -> 'DripNetwork':
        """从 QGIS 图层读取数据，构建 DripNetwork

        Args:
            expand: 是否展开毛管为滴头链（模拟用）。
                INP 导出时应为 False 以保留原始管网结构。
            split_vertices: 是否在每个折线顶点处分割管道（INP 导出用）。
                EPANET 只支持两点直线，QGIS 折线的每个顶点都需要 junction。
        """
        from wdrip.network import (
            DripNetwork, FieldInfo,
            SourceNode, Junction,
            Pipe, Pump, Valve, ValveType,
            expand_lateral,
        )

        net = DripNetwork(name=QApplication.translate("SyncManager", "aQuaDrip 项目"))

        pipe_layer = self._get_layer("aqd_pipes")
        pump_layer = self._get_layer("aqd_pumps")
        valve_layer = self._get_layer("aqd_valves")
        if self._is_geographic():
            self.log(QApplication.translate("SyncManager", "⚠️ 图层为经纬度坐标，长度/面积按度计算，建议投影到米制坐标系"))

        # 1. 读取农田
        # FieldInfo 是单数模型：多田块项目把面积累加，农艺参数取第一个
        # 田块，并提示用户（原先静默丢弃其余田块）
        field_layer = self._get_layer("aqd_fields")
        if field_layer and field_layer.featureCount() > 0:
            feats = list(field_layer.getFeatures())
            feat = feats[0]
            fgeom = feat.geometry()
            total_area = sum(
                (f.geometry().area()
                 if f.geometry() and not f.geometry().isEmpty() else 0.0)
                for f in feats)
            if len(feats) > 1:
                self.log(
                    QApplication.translate("SyncManager", "⚠️ 检测到 {0} 个田块，FieldInfo 仅支持单一农艺参数：面积已累加({1:.1f})，其余参数取第一个田块").format(len(feats), total_area))
            net.field_info = FieldInfo(
                area=total_area,
                crop_type=str(self._attr(feat, "crop_type") or ""),
                planting_pattern=str(self._attr(feat, "planting_pattern") or "uniform"),
                row_spacings=[float(self._attr(feat, "row_spacing") or 0.5)],
                ridge_count=int(self._attr(feat, "ridge_count") or 0) or None,
                row_direction=float(self._attr(feat, "row_direction") or 0),
                emitter_spacing=float(self._attr(feat, "emitter_spacing") or 0.3),
                geometry=fgeom,
            )

        # 2. 读取节点和所有 link 要素（管道 / 水泵 / 阀门）
        node_layer = self._get_layer("aqd_nodes")
        node_features = self._features_from(node_layer)

        pipe_features = self._features_from(pipe_layer)
        pump_features = self._features_from(pump_layer)
        valve_features = self._features_from(valve_layer)

        # 3. 统一拓扑构建（几何相交驱动，不经坐标匹配）
        from .topology_builder import TopologyBuilder

        if split_vertices:
            # INP 导出：折线每个顶点都需 junction。
            # 处理三个图层各自的折线切段。

            def _build_fake_features(layer, features):
                """把 features 在每个折线顶点切断，生成 fake feature 列表"""
                if not layer or not features:
                    return []
                flds = layer.fields()
                recs = []
                for feat in features:
                    geom = feat.geometry()
                    if not geom or geom.isEmpty():
                        continue
                    line = geom.asPolyline()
                    if len(line) < 2:
                        continue
                    recs.append({
                        "line": line,
                        "lid": str(self._attr(feat, "id") or f"{self._lid_prefix_for_layer(layer)}{feat.id()}"),
                        "geom": geom,
                        "feat": feat,
                    })
                vertex_segs = self._split_at_vertices(recs)
                result = []
                for seg in vertex_segs:
                    src_feat = seg["record"].get("feat")
                    if src_feat is not None and flds is not None:
                        fake_feat = QgsFeature(flds)
                        fake_feat.setAttributes(src_feat.attributes())
                        fake_feat.setId(src_feat.id())
                    else:
                        fake_feat = QgsFeature()
                    fake_feat.setGeometry(QgsGeometry.fromPolylineXY(seg["pts"]))
                    result.append(fake_feat)
                return result

            builder = TopologyBuilder(net, self._is_geographic())
            segments = builder.build(
                node_features,
                _build_fake_features(pipe_layer, pipe_features),
                _build_fake_features(pump_layer, pump_features),
                _build_fake_features(valve_layer, valve_features),
            )
        else:
            builder = TopologyBuilder(net, self._is_geographic())
            segments = builder.build(
                node_features, pipe_features, pump_features, valve_features)

        # 诊断
        lat_count = len([s for s in segments if s["pipe_type"] == "lateral"])
        self.log(QApplication.translate("SyncManager", "拓扑构建: {0} 段（毛管 {1}） 节点 {2}").format(len(segments), lat_count, len(net.nodes)))

        # 4. 从 segments 建 link + 收集毛管
        laterals: List[dict] = []
        link_geometry: Dict[str, list] = {}

        # 按 device 分组，准备分别回写到对应图层
        # layer_map: device → layer
        layer_map = {
            "none": pipe_layer,
            "pump": pump_layer,
            "valve": valve_layer,
        }

        # 收集每个 device 组的 segments，统一编辑+提交
        group_segs: dict = {}  # device → [segments]
        for seg in segments:
            group_segs.setdefault(seg["device"], []).append(seg)

        for device, segs in group_segs.items():
            layer = layer_map.get(device)
            if layer is None:
                continue
            need_edit = not layer.isEditable()
            if need_edit:
                layer.startEditing()
            try:
                fid_to_segs = {}
                for seg in segs:
                    fid_to_segs.setdefault(seg["fid"], []).append(seg)


                for seg in segs:
                    pts = seg["pts"]
                    seg_length = QgsGeometry.fromPolylineXY(pts).length()
                    if seg_length <= 0:
                        continue
                    lid = seg["lid"] if seg["part"] == 0 else \
                        f"{seg['lid']}_p{seg['part'] + 1}"
                    from_node = seg["from_node"]
                    to_node = seg["to_node"]
                    if not from_node or not to_node:
                        continue

                    link_geometry[lid] = [
                        (float(p.x()), float(p.y())) for p in pts
                    ]

                    feat = seg["feat"]
                    diameter = float(self._attr(feat, "diameter") or 0)
                    roughness = float(self._attr(feat, "roughness") or 130)
                    pipe_type = seg["pipe_type"]

                    if device == "pump":
                        link = Pump(lid, from_node, to_node,
                                    rated_head=float(self._attr(feat, "pump_head") or 0),
                                    rated_flow=float(self._attr(feat, "pump_flow") or 0),
                                    rated_power=float(self._attr(feat, "pump_power") or 0))
                    elif device == "valve":
                        vtype_str = str(self._attr(feat, "valve_type") or "GATE").upper()
                        vtype = getattr(ValveType, vtype_str, ValveType.PRV)
                        setting = float(self._attr(feat, "setting") or 0)
                        # 读取阀门开闭状态（GPKG 中存储 "open"/"closed"）
                        status_str = str(self._attr(feat, "status") or "open").lower()
                        from wdrip.network.links import ValveStatus
                        vstatus = ValveStatus.CLOSED if status_str == "closed" else ValveStatus.OPEN
                        link = Valve(lid, from_node, to_node,
                                     valve_type=vtype,
                                     setting=setting,
                                     diameter=diameter,
                                     status=vstatus)
                    else:
                        link = Pipe(lid, from_node, to_node,
                                    pipe_type=pipe_type,
                                    diameter=diameter, length=seg_length,
                                    roughness=roughness)

                    net.add_link(link)

                    if pipe_type == "lateral" and device == "none":
                        es = float(self._attr(feat, "emitter_spacing") or 0)
                        if es <= 0 and net.field_info:
                            es = net.field_info.emitter_spacing
                        ek = self._attr(feat, "emitter_k") or None
                        ex = self._attr(feat, "emitter_x") or None
                        laterals.append({
                            "lid": lid,
                            "spacing": es if es > 0 else 0.3,
                            "k": float(ek) if ek is not None else None,
                            "x": float(ex) if ex is not None else None,
                        })

                # 拓扑回写（写回各自图层）
                for fid, fsegs in fid_to_segs.items():
                    if not fsegs:
                        continue
                    f = fsegs[0]["feat"]
                    f.setAttribute("from_node", fsegs[0]["from_node"] or "")
                    f.setAttribute("to_node", fsegs[-1]["to_node"] or "")
                    layer.updateFeature(f)
            except Exception:
                if need_edit:
                    layer.rollBack()
                raise
            else:
                if need_edit and not layer.commitChanges():
                    layer.rollBack()
                    self.log(QApplication.translate("SyncManager", "⚠️ 图层 {0} 提交失败").format(layer.name()))

        # 5. 毛管展开为 EmitterNode 滴头链
        #    关键：emitter_spacing 是米单位，必须投影到米制 CRS（UTM）后再展开，
        #    否则在经纬度下 math.hypot 算出的"长度"是度，滴头数永远 = 1。
        if expand and laterals:
            src_crs = self._detect_crs()
            is_geo = src_crs is not None and src_crs.isGeographic()
            if is_geo:
                # 临时投影到 UTM → 展开 → 投影回原 CRS
                self._reproject_net(net, src_crs, to_utm=True)
                try:
                    for lat in laterals:
                        try:
                            expand_lateral(net, lat["lid"], lat["spacing"],
                                           emitter_k=lat.get("k"),
                                           emitter_x=lat.get("x"))
                        except Exception as e:
                            self.log(QApplication.translate("SyncManager", "⚠️ 毛管 {0} 展开失败: {1}").format(lat['lid'], e))
                finally:
                    self._reproject_net(net, src_crs, to_utm=False)
            else:
                for lat in laterals:
                    try:
                        expand_lateral(net, lat["lid"], lat["spacing"],
                                       emitter_k=lat.get("k"),
                                       emitter_x=lat.get("x"))
                    except Exception as e:
                        self.log(QApplication.translate("SyncManager", "⚠️ 毛管 {0} 展开失败: {1}").format(lat['lid'], e))

        # expand 后补全 link 几何
        for lid, link in net.links.items():
            if lid in link_geometry:
                continue
            a = net.get_node(link.from_node)
            b = net.get_node(link.to_node)
            if a is not None and b is not None:
                link_geometry[lid] = [(a.x, a.y), (b.x, b.y)]

        net.link_geometry = link_geometry

        # 6. 为所有节点（含 auto_N / E_* 滴头）提取 DEM 高程
        #    高程提取工具只写 aqd_nodes 图层，expand 创建的新节点
        #    elevation 为 0 → 模拟时 pressure = total_head − 0 = 总水头值，
        #    显示为"一千多"的假高压。此处直接采样 DEM 补全所有节点高程。
        if expand:
            self._apply_dem_to_network(net)

        return net

    # ── CRS 投影辅助 ──

    def _apply_dem_to_network(self, net):
        """为 DripNetwork 中所有节点采样 DEM 高程。

        expand_lateral 创建的 auto_N / E_* 节点 elevation 为 0，
        导致模拟压力 = total_head − 0 = 虚高的几千。此方法从项目
        中的 DEM 栅格直接采样补全所有节点高程，并修正水源水头。

        无 DEM 时所有节点高程保持 0（同一高度），模拟只考虑管道
        摩擦损失，不考虑地形高差。
        """
        # 1. 查找 DEM 图层（与 ElevationExtractor 相同的优先级+fallback）
        dem_layer = self._find_dem_layer()
        if dem_layer is None:
            return  # 无 DEM 图层，高程保持 0（同一高度）

        provider = dem_layer.dataProvider()
        if provider is None:
            return

        # 2. CRS 变换
        node_crs = self._detect_crs()
        dem_crs = dem_layer.crs()
        xform = None
        if node_crs is not None and node_crs.isValid() and dem_crs.isValid() \
                and node_crs != dem_crs:
            xform = QgsCoordinateTransform(node_crs, dem_crs, self.project)

        # 3. 采样所有节点
        updated = 0
        total = len(net.nodes)
        max_elev = 0.0
        for node in net.nodes.values():
            pt = QgsPointXY(node.x, node.y)
            if xform is not None:
                pt = xform.transform(pt)
            value, valid = provider.sample(pt, 1)
            if valid:
                node.elevation = float(value)
                max_elev = max(max_elev, node.elevation)
                updated += 1

        # 4. 修正水源水头（DEM 高程远大于默认水头 20m 时必须修正，
        #    否则 pressure = head - elevation < 0 → 负压 → 管网不出水）
        if updated > 0 and max_elev > 0:
            from wdrip.network import SourceNode
            margin = 20.0  # 安全裕量（m）
            for node in net.nodes.values():
                if isinstance(node, SourceNode):
                    required = max(node.elevation, max_elev) + margin
                    if node.head < required:
                        old_head = node.head
                        node.head = required
                        self.log(
                            QApplication.translate("SyncManager", "🔧 水源 {0} 水头修正: {1:.1f} → {2:.1f}m").format(node.id, old_head, required))

            self.log(QApplication.translate("SyncManager", "🌐 DEM 高程已应用于 {0}/{1} 个节点").format(updated, total))

    def _detect_crs(self) -> Optional[QgsCoordinateReferenceSystem]:
        """检测项目 CRS（用于判定地理/投影坐标系）。"""
        for key in ("aqd_nodes", "aqd_pipes", "aqd_fields"):
            ly = self._get_layer(key)
            if ly is not None and ly.crs().isValid():
                return ly.crs()
        if self.project.crs().isValid():
            return self.project.crs()
        return None

    def _find_dem_layer(self) -> Optional[QgsRasterLayer]:
        """查找 DEM 栅格图层

        优先级: name=="DEM 高程" > name 含 dem/elevation/高程 > 无匹配
        不回退到任意栅格（避免从正射影像/卫星底图采样错误高程）。
        """
        rasters = []
        for _lid, layer in self.project.mapLayers().items():
            if not isinstance(layer, QgsRasterLayer):
                continue
            if layer.name() == "DEM 高程":  # 图层名是数据标识,不翻译
                return layer
            rasters.append(layer)
        dem_keywords = ("dem", "elevation", QApplication.translate("SyncManager", "高程"), "altitude", "dtm", "srtm")
        for layer in rasters:
            name_lower = layer.name().lower()
            if any(kw in name_lower for kw in dem_keywords):
                return layer
        return None

    def _reproject_net(self, net, src_crs: QgsCoordinateReferenceSystem,
                       to_utm: bool):
        """原地投影 DripNetwork 的所有节点坐标。

        to_utm=True  : src_crs → UTM（用于米单位展开）
        to_utm=False : UTM → src_crs（展开后还原）
        """
        if not net.nodes:
            return
        # 以第一个节点坐标算 UTM zone
        sample = next(iter(net.nodes.values()))
        if to_utm:
            utm = self._utm_zone(sample.x, sample.y)
            self._utm_crs = utm
            xform = QgsCoordinateTransform(src_crs, utm, self.project)
        else:
            utm = getattr(self, "_utm_crs", None)
            if utm is None:
                return
            xform = QgsCoordinateTransform(utm, src_crs, self.project)

        for node in net.nodes.values():
            pt = QgsPointXY(node.x, node.y)
            tp = xform.transform(pt)
            node.x = tp.x()
            node.y = tp.y()

    @staticmethod
    def _utm_zone(lon: float, lat: float) -> QgsCoordinateReferenceSystem:
        """根据经纬度返回对应 UTM zone 的 CRS。"""
        zone = int(math.floor((lon + 180) / 6) + 1)
        epsg = 32600 + zone if lat >= 0 else 32700 + zone
        return QgsCoordinateReferenceSystem(f"EPSG:{epsg}")

    # ── 将模拟结果写回 QGIS ──

    def sync_from_network(self, network: 'DripNetwork',
                          result: 'SimulationResult' = None):
        """将模拟结果写回 QGIS 图层（flow/velocity/pressure）

        管道/水泵/阀门的 flow/velocity 分别写回对应图层。
        """
        node_layer = self._get_layer("aqd_nodes")
        if not result:
            return

        # 写入所有 link 图层结果（流量、流速）
        for layer in self._all_link_layers():
            lid_prefix = self._lid_prefix_for_layer(layer)
            need_edit = not layer.isEditable()
            if need_edit:
                layer.startEditing()
            try:
                for feat in layer.getFeatures():
                    lid = str(self._attr(feat, "id") or f"{lid_prefix}{feat.id()}")
                    changed = False
                    if lid in result.link_flow:
                        arr = result.link_flow[lid]
                        if len(arr) > 0:
                            feat.setAttribute("flow", float(arr[-1]))
                            changed = True
                    if lid in result.link_velocity:
                        arr = result.link_velocity[lid]
                        if len(arr) > 0:
                            feat.setAttribute("velocity", float(arr[-1]))
                            changed = True
                    if changed:
                        layer.updateFeature(feat)
            except Exception:
                if need_edit:
                    layer.rollBack()
                raise
            else:
                if need_edit and not layer.commitChanges():
                    layer.rollBack()
                    self.log(QApplication.translate("SyncManager", "⚠️ 图层 {0} 提交失败").format(layer.name()))
            layer.triggerRepaint()

        # 写入节点结果（压力）
        if node_layer:
            self._ensure_field(node_layer, "pressure")
            need_edit = not node_layer.isEditable()
            if need_edit:
                node_layer.startEditing()
            try:
                for feat in node_layer.getFeatures():
                    nid = str(self._attr(feat, "id") or f"N{feat.id()}")
                    if nid in result.node_pressure:
                        arr = result.node_pressure[nid]
                        if len(arr) > 0:
                            feat.setAttribute("pressure", float(arr[-1]))
                            node_layer.updateFeature(feat)
            except Exception:
                if need_edit:
                    node_layer.rollBack()
                raise
            else:
                if need_edit and not node_layer.commitChanges():
                    node_layer.rollBack()
                    self.log(QApplication.translate("SyncManager", "⚠️ 图层 {0} 提交失败").format(node_layer.name()))
            node_layer.triggerRepaint()

    # ── 顶点切段（INP 导出用）──

    def _split_at_vertices(self, records: list) -> list:
        """INP 导出用：把每条管道在每个折线顶点处拆分为多段

        EPANET 只支持两点直线，QGIS 折线的每个顶点都需要一个 junction。
        每条折线 (v0,v1,...,vn) 拆为 n 段：(v0,v1), (v1,v2), ..., (v_{n-1},vn)。

        Returns:
            [{"record", "part", "pts"}]，part=0 为第一段（保留原 lid）
        """
        all_segments = []
        for rec in records:
            line = rec["line"]
            if len(line) < 2:
                continue
            for i in range(len(line) - 1):
                pts = [line[i], line[i + 1]]
                # 跳过零长度段
                if line[i].distance(line[i + 1]) < 1e-10:
                    continue
                all_segments.append({
                    "record": rec,
                    "part": i,
                    "pts": pts,
                })
        return all_segments

    def _is_geographic(self) -> bool:
        layer = self._get_layer("aqd_nodes") or self._get_layer("aqd_pipes")
        return bool(layer and layer.crs().isGeographic())

    # ── 图层查找（从项目中找，与其他工具一致）──

    @staticmethod
    def _lid_prefix_for_layer(layer: QgsVectorLayer) -> str:
        """根据图层名返回 link ID 前缀。

        L=管道, PU=水泵, V=阀门。与 TopologyBuilder._collect_links 一致。
        """
        src = layer.source() if hasattr(layer, "source") else ""
        if "aqd_pumps" in src or layer.name() == "aqd_pumps":
            return "PU"
        if "aqd_valves" in src or layer.name() == "aqd_valves":
            return "V"
        return "L"

    @staticmethod
    def _ensure_field(layer: QgsVectorLayer, field_name: str):
        """确保图层存在指定字段（用于旧 GPKG 的字段迁移）"""
        from qgis.core import QgsField
        from qgis.PyQt.QtCore import QVariant
        if layer.fields().lookupField(field_name) < 0:
            layer.dataProvider().addAttributes(
                [QgsField(field_name, QVariant.Double)])
            layer.updateFields()

    def _get_layer(self, key: str) -> Optional[QgsVectorLayer]:
        """从项目已加载图层中查找（按名称或 source 匹配）

        注意：必须用项目中的图层实例，写回结果才能实时刷新；
        用 gpkg 路径重开的图层对象修改后项目视图不会更新。
        """
        from .layer_utils import find_layer
        return find_layer(self.project, key)

    def log(self, msg: str):
        """输出日志（线程安全：非主线程时跳过 pushMessage）"""
        # macOS 禁止非主线程操作 UI，后台线程调用时只打印
        from qgis.PyQt.QtCore import QThread, QCoreApplication
        try:
            app = QCoreApplication.instance()
            if app and QThread.currentThread() == app.thread():
                self.iface.messageBar().pushMessage(
                    "aQuaDrip", msg, level=0, duration=3)
        except Exception:
            pass
        # 始终输出到 Python 控制台
        print(f"[aQuaDrip] {msg}")
