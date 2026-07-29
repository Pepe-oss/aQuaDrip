# -*- coding: utf-8 -*-
"""
aQuaDrip 插件主类
"""

import os
import sys
from qgis.core import QgsApplication
from qgis.gui import QgisInterface
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.PyQt.QtCore import Qt


class AQuaDripPlugin:
    """aQuaDrip QGIS 插件主类"""

    def __init__(self, iface: QgisInterface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(os.path.realpath(__file__))
        
        # 将 wdrip-core 加入 Python 路径
        _p = os.path.join(self.plugin_dir, "..", "wdrip-core")
        _p = os.path.abspath(_p)
        if os.path.isdir(os.path.join(_p, "wdrip")) and _p not in sys.path:
            sys.path.insert(0, _p)
        
        self.actions = []
        self.dockwidget = None
        self.provider = None

    def initGui(self):
        """初始化 GUI（菜单、工具栏）"""
        # 验证 wdrip-core
        try:
            from wdrip.network import DripNetwork
            self._wdrip_ok = True
        except ImportError as e:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", f"wdrip-core 加载失败: {e}")
            self._wdrip_ok = False
            return

        # 创建菜单
        menu = self.iface.pluginMenu().addMenu("&aQuaDrip")
        
        # 初始化图层
        action = QAction(QgsApplication.getThemeIcon("mActionNewVectorLayer"),
                        "初始化图层", self.iface.mainWindow())
        action.triggered.connect(self.on_setup_layers)
        action.setToolTip("创建 aQuaDrip 标准 GeoPackage 图层")
        menu.addAction(action)
        self.actions.append(action)
        
        # 创建主面板
        from .ui.dockwidget import AQuaDripDockWidget
        self.dockwidget = AQuaDripDockWidget(self.iface)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dockwidget)
        self.dockwidget.log_message("aQuaDrip 已加载")

        # 分隔线
        menu.addSeparator()

    def unload(self):
        """卸载插件"""
        for action in self.actions:
            try:
                self.iface.removePluginMenu("&aQuaDrip", action)
                self.iface.removeToolBarIcon(action)
            except:
                pass
        self.actions.clear()
        
        if self.dockwidget:
            self.iface.removeDockWidget(self.dockwidget)
            self.dockwidget = None
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

    def on_setup_layers(self):
        """一键创建标准图层"""
        self.iface.messageBar().pushMessage(
            "aQuaDrip", "正在创建图层...", level=0, duration=3)
        
        try:
            from .tools.layer_setup import LayerSetupAction
            
            setup = LayerSetupAction(self.iface)
            success = setup.setup()
            
            if success:
                QMessageBox.information(
                    self.iface.mainWindow(),
                    "aQuaDrip",
                    f"图层已创建完成\n\n"
                    f"文件位置: {setup.gpkg_path}\n\n"
                    f"• 农田地块 (aqd_fields)\n"
                    f"• 管道 (aqd_pipes) — 含泵/阀设备字段\n"
                    f"• 节点 (aqd_nodes) — 水源/施肥罐\n"
                    f"• 观测点 (aqd_obs_points) — 校准用"
                )
            else:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "aQuaDrip",
                    "图层创建失败，请查看 Python 日志"
                )
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.iface.messageBar().pushWarning(
                "aQuaDrip", f"创建失败: {e}")
