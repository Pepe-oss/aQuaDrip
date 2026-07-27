"""LayerManager — QGIS 图层管理

自动创建/管理 aQuaDrip 的 QGIS 图层组和图层。
"""

import os
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsLayerTreeGroup,
    QgsLayerTreeLayer, QgsField, QgsCoordinateReferenceSystem,
    QgsWkbTypes, QgsMarkerSymbol, QgsLineSymbol,
    QgsSingleSymbolRenderer, QgsCategorizedSymbolRenderer,
    QgsGraduatedSymbolRenderer, QgsRendererRange,
    QgsRectangle, QgsFeature, QgsGeometry, QgsPointXY, QgsLineString, edit,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor


class LayerManager:
    """图层管理器"""

    # 图层定义: (name, geometry_type, fields, crs)
    LAYER_DEFS = {
        "field": {
            "name": "农田地块",
            "geom": "Polygon",
            "fields": [
                QgsField("id", QVariant.String, "String"),
                QgsField("crop", QVariant.String, "String"),
                QgsField("area", QVariant.Double, "Real"),
                QgsField("pattern", QVariant.String, "String"),
                QgsField("row_spacing", QVariant.Double, "Real"),
                QgsField("ridge_count", QVariant.Int, "Integer"),
            ],
        },
        "junction": {
            "name": "节点",
            "geom": "Point",
            "fields": [
                QgsField("id", QVariant.String, "String"),
                QgsField("elevation", QVariant.Double, "Real"),
                QgsField("node_type", QVariant.String, "String"),
            ],
        },
        "emitter": {
            "name": "滴头",
            "geom": "Point",
            "fields": [
                QgsField("id", QVariant.String, "String"),
                QgsField("k", QVariant.Double, "Real"),
                QgsField("x", QVariant.Double, "Real"),
                QgsField("lateral_id", QVariant.String, "String"),
                QgsField("pressure", QVariant.Double, "Real"),
                QgsField("flow", QVariant.Double, "Real"),
            ],
        },
        "source": {
            "name": "水源",
            "geom": "Point",
            "fields": [
                QgsField("id", QVariant.String, "String"),
                QgsField("type", QVariant.String, "String"),
                QgsField("head", QVariant.Double, "Real"),
                QgsField("flow", QVariant.Double, "Real"),
            ],
        },
        "mainline": {
            "name": "干管",
            "geom": "LineString",
            "fields": [
                QgsField("id", QVariant.String, "String"),
                QgsField("diameter", QVariant.Double, "Real"),
                QgsField("length", QVariant.Double, "Real"),
                QgsField("roughness", QVariant.Double, "Real"),
                QgsField("flow", QVariant.Double, "Real"),
                QgsField("velocity", QVariant.Double, "Real"),
            ],
        },
        "submain": {
            "name": "支管",
            "geom": "LineString",
            "fields": [
                QgsField("id", QVariant.String, "String"),
                QgsField("diameter", QVariant.Double, "Real"),
                QgsField("length", QVariant.Double, "Real"),
                QgsField("flow", QVariant.Double, "Real"),
            ],
        },
        "lateral": {
            "name": "毛管",
            "geom": "LineString",
            "fields": [
                QgsField("id", QVariant.String, "String"),
                QgsField("diameter", QVariant.Double, "Real"),
                QgsField("length", QVariant.Double, "Real"),
                QgsField("emitter_spacing", QVariant.Double, "Real"),
                QgsField("flow", QVariant.Double, "Real"),
            ],
        },
        "pump": {
            "name": "水泵",
            "geom": "LineString",
            "fields": [
                QgsField("id", QVariant.String, "String"),
                QgsField("head", QVariant.Double, "Real"),
                QgsField("flow", QVariant.Double, "Real"),
                QgsField("power", QVariant.Double, "Real"),
            ],
        },
        "valve": {
            "name": "阀门",
            "geom": "LineString",
            "fields": [
                QgsField("id", QVariant.String, "String"),
                QgsField("type", QVariant.String, "String"),
                QgsField("setting", QVariant.Double, "Real"),
            ],
        },
    }

    # 图层分组结构
    GROUP_TREE = {
        "aQuaDrip": {
            "农田": ["field"],
            "管网": ["mainline", "submain", "lateral", "junction", "emitter"],
            "设备": ["source", "pump", "valve"],
        }
    }

    def __init__(self):
        self.project = QgsProject.instance()
        self.root = self.project.layerTreeRoot()
        self._layers = {}  # {key: QgsVectorLayer}
        self._group_nodes = {}  # {group_name: QgsLayerTreeGroup}
        self._aq_group = None

    def setup(self):
        """创建图层组和所有图层"""
        # 移除旧的 aQuaDrip 分组（如果存在）
        old = self._find_group(self.root, "aQuaDrip")
        if old:
            self.root.removeChildNode(old)
        self._aq_group = None
        
        self._create_groups(self.GROUP_TREE)
        self._create_layers()
        return self._layers

    def _create_groups(self, tree, parent=None):
        """递归创建图层组"""
        if parent is None:
            parent = self.root
        for name, children in tree.items():
            group = parent.addGroup(name)
            if isinstance(children, dict):
                self._create_groups(children, group)
            if name == "aQuaDrip":
                self._aq_group = group

    def _create_layers(self):
        """创建所有图层"""
        for key, defn in self.LAYER_DEFS.items():
            layer = self._create_layer(key, defn)
            if layer:
                self._layers[key] = layer
                self._add_layer_to_group(layer, key)

    def _create_layer(self, key, defn):
        """创建单个矢量图层"""
        uri = f"{defn['geom']}?crs=EPSG:4326"
        layer = QgsVectorLayer(uri, defn["name"], "memory")
        if not layer.isValid():
            return None
        
        provider = layer.dataProvider()
        provider.addAttributes(defn["fields"])
        layer.updateFields()
        
        # 添加一个虚拟要素，使图层有有效范围（防止"缩放到图层组"崩溃）
        # 仅农田图层需要，其他图层设置默认范围即可
        if key == "field":
            dummy = QgsFeature(layer.fields())
            geom_type = defn["geom"]
            if geom_type == "Point":
                dummy.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(0, 0)))
            elif geom_type == "LineString":
                dummy.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(0, 0), QgsPointXY(1, 1)]))
            elif geom_type == "Polygon":
                g = QgsGeometry.fromRect(QgsRectangle(0, 0, 1, 1))
                dummy.setGeometry(g)
            provider.addFeature(dummy)
        else:
            layer.setExtent(QgsRectangle(0, 0, 1, 1))
        
        return layer

    def _add_layer_to_group(self, layer, key):
        """将图层添加到对应的分组"""
        # 查找 key 属于哪个分组
        for group_name, layer_keys in self._get_group_children().items():
            if key in layer_keys:
                # 找到 aQuaDrip 下的对应分组
                parent_group = self._find_group(self.root, "aQuaDrip")
                if parent_group:
                    child_group = self._find_group(parent_group, group_name)
                    if child_group:
                        child_group.addLayer(layer)
                        return
        # 默认添加到 root
        self.root.addLayer(layer)

    def _get_group_children(self):
        """获取 {分组名: [图层key]}"""
        result = {}
        for group_name, keys in self.GROUP_TREE.get("aQuaDrip", {}).items():
            if isinstance(keys, list):
                result[group_name] = keys
        return result

    @staticmethod
    def _find_group(parent, name):
        """在树中查找分组"""
        for child in parent.children():
            if isinstance(child, QgsLayerTreeGroup) and child.name() == name:
                return child
        return None

    # ---- 图层获取 ----

    def get_layer(self, key: str) -> QgsVectorLayer:
        """获取图层"""
        return self._layers.get(key)

    def get_all_layers(self) -> dict:
        """获取所有图层"""
        return self._layers

    # ---- 图层清理 ----

    def clear_layers(self, key: str = None):
        """清理图层"""
        if key:
            # 清理指定图层
            layer = self._layers.pop(key, None)
            if layer:
                try:
                    self.project.removeMapLayer(layer)
                except RuntimeError:
                    pass
            return
        
        # 清理所有图层
        for k, layer in list(self._layers.items()):
            try:
                self.project.removeMapLayer(layer)
            except RuntimeError:
                pass
        self._layers.clear()
        if self._aq_group:
            try:
                _ = self._aq_group.name()
                self.root.removeChildNode(self._aq_group)
            except RuntimeError:
                pass
            self._aq_group = None

    # ---- 从 DripNetwork 更新 ----

    def clear_dummy_features(self):
        """清除所有图层中的虚拟要素"""
        for key, layer in self._layers.items():
            if layer and layer.featureCount() > 0:
                with edit(layer):
                    for feat in layer.getFeatures():
                        layer.deleteFeature(feat.id())
                        break  # 只需删除一个（虚拟要素）

    def update_from_network(self, network, result=None):
        """从 DripNetwork 和模拟结果更新图层"""
        # TODO: Sprint 3.6 实现
        pass
