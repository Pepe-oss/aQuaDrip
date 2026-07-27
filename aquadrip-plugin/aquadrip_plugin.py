# -*- coding: utf-8 -*-
"""
aQuaDrip 插件主类
"""

import os
from qgis.core import QgsApplication, QgsProcessingProvider
from qgis.gui import QgisInterface


class AQuaDripPlugin:
    """aQuaDrip QGIS 插件主类"""

    def __init__(self, iface: QgisInterface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.dockwidget = None
        self.provider = None

    def initGui(self):
        """初始化 GUI（菜单、工具栏、DockWidget）"""
        # TODO: Phase 2 — 添加菜单和工具栏按钮
        # TODO: Phase 2 — 创建 DockWidget
        # TODO: Phase 4 — 注册 Processing Provider
        pass

    def unload(self):
        """卸载插件"""
        # TODO: 清理菜单、工具栏、DockWidget
        # TODO: 注销 Processing Provider
        if self.dockwidget:
            self.iface.removeDockWidget(self.dockwidget)
            self.dockwidget = None
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
