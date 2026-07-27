"""StyleManager — QGIS 图层样式管理

为各类管网元素设置默认渲染样式，
为模拟结果设置热力图渲染。
"""

from qgis.core import (
    QgsMarkerSymbol, QgsLineSymbol, QgsFillSymbol,
    QgsSingleSymbolRenderer, QgsCategorizedSymbolRenderer,
    QgsGraduatedSymbolRenderer, QgsRendererRange,
    QgsLayerTreeLayer,
)
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import Qt


class StyleManager:
    """样式管理器"""

    # 颜色方案
    COLORS = {
        "mainline": QColor("#1a5276"),   # 深蓝
        "submain": QColor("#2e86c1"),    # 中蓝
        "lateral": QColor("#85c1e9"),    # 浅蓝
        "junction": QColor("#2e86c1"),   # 蓝色节点
        "emitter": QColor("#27ae60"),    # 绿色
        "source": QColor("#1a5276"),     # 深蓝水源
        "pump": QColor("#e74c3c"),       # 红色泵
        "valve": QColor("#f39c12"),      # 橙色阀
        "field": QColor("#27ae60"),      # 绿色地块
        "flow_low": QColor("#2ecc71"),   # 低流量
        "flow_mid": QColor("#f1c40f"),   # 中流量
        "flow_high": QColor("#e74c3c"),  # 高流量
        "pressure_low": QColor("#e74c3c"),    # 低压
        "pressure_mid": QColor("#f39c12"),    # 中压
        "pressure_high": QColor("#2ecc71"),   # 高压
    }

    def __init__(self):
        self._styles = {}

    def apply_default_styles(self, layers: dict):
        """为所有图层应用默认样式"""
        for key, layer in layers.items():
            if layer is None:
                continue
            renderer = self._make_renderer(key)
            if renderer:
                layer.setRenderer(renderer)
                layer.triggerRepaint()

    def _make_renderer(self, key: str):
        """创建默认渲染器"""
        makers = {
            "field": lambda: self._field_style(),
            "junction": lambda: self._junction_style(),
            "emitter": lambda: self._emitter_style(),
            "source": lambda: self._source_style(),
            "mainline": lambda: self._pipe_style("mainline", 2.5),
            "submain": lambda: self._pipe_style("submain", 1.5),
            "lateral": lambda: self._pipe_style("lateral", 0.8),
            "pump": lambda: self._pump_style(),
            "valve": lambda: self._valve_style(),
        }
        maker = makers.get(key)
        return maker() if maker else None

    # ---- 各元素样式 ----

    def _field_style(self):
        sym = QgsFillSymbol.createSimple({
            "color": "200, 230, 200, 80",
            "outline_color": "39, 174, 96",
            "outline_width": "0.5",
        })
        return QgsSingleSymbolRenderer(sym)

    def _junction_style(self):
        sym = QgsMarkerSymbol.createSimple({
            "name": "circle",
            "color": "#2e86c1",
            "size": "2.5",
            "outline_color": "white",
            "outline_width": "0.5",
        })
        return QgsSingleSymbolRenderer(sym)

    def _emitter_style(self):
        sym = QgsMarkerSymbol.createSimple({
            "name": "diamond",
            "color": "#27ae60",
            "size": "2",
            "outline_color": "white",
            "outline_width": "0.3",
        })
        return QgsSingleSymbolRenderer(sym)

    def _source_style(self):
        sym = QgsMarkerSymbol.createSimple({
            "name": "square",
            "color": "#1a5276",
            "size": "5",
            "outline_color": "white",
            "outline_width": "1",
        })
        return QgsSingleSymbolRenderer(sym)

    def _pipe_style(self, pipe_type, width):
        color = self.COLORS.get(pipe_type, QColor("#666"))
        sym = QgsLineSymbol.createSimple({
            "color": color.name(),
            "width": str(width),
            "capstyle": "round",
        })
        return QgsSingleSymbolRenderer(sym)

    def _pump_style(self):
        sym = QgsLineSymbol.createSimple({
            "color": "#e74c3c",
            "width": "2.5",
            "capstyle": "round",
        })
        return QgsSingleSymbolRenderer(sym)

    def _valve_style(self):
        sym = QgsLineSymbol.createSimple({
            "color": "#f39c12",
            "width": "2.0",
            "capstyle": "round",
        })
        return QgsSingleSymbolRenderer(sym)

    # ---- 结果渲染 ----

    def make_pressure_renderer(self, values: list):
        """创建压力热力图渲染器
        
        Args:
            values: [(value, label), ...]
        """
        if not values:
            return None
        
        max_val = max(v for v, _ in values)
        ranges = []
        n_colors = 5
        
        for i in range(n_colors):
            v_min = max_val * i / n_colors
            v_max = max_val * (i + 1) / n_colors
            frac = i / (n_colors - 1)
            r = int(255 * frac)
            g = int(255 * (1 - frac))
            b = 0
            color = QColor(r, g, b, 200)
            ranges.append(QgsRendererRange(v_min, v_max, color, f"{v_min:.1f}-{v_max:.1f}"))
        
        return QgsGraduatedSymbolRenderer("pressure", ranges)

    def make_flow_renderer(self, diameter_attr: str = "diameter"):
        """创建流量渲染器（线宽按流量分级）"""
        sym = QgsLineSymbol.createSimple({
            "color": "#2e86c1",
            "width": "1",
            "capstyle": "round",
        })
        renderer = QgsSingleSymbolRenderer(sym)
        renderer.setUsingSymbolLevels(True)
        return renderer

    # ---- 工具 ----

    def save_style_to_qml(self, layer, path: str):
        """将图层样式导出为 QML 文件"""
        from qgis.core import QgsMapLayerStyle
        style = QgsMapLayerStyle()
        style.readFromLayer(layer)
        with open(path, "w") as f:
            f.write(style.xmlData())

    def load_style_from_qml(self, layer, path: str):
        """从 QML 文件加载样式"""
        from qgis.core import QgsMapLayerStyle
        with open(path) as f:
            xml = f.read()
        style = QgsMapLayerStyle(xml)
        style.writeToLayer(layer)
