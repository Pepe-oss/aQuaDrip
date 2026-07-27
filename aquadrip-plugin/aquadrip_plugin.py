# -*- coding: utf-8 -*-
"""
aQuaDrip 插件主类 — 菜单、工具栏、DockWidget 管理
"""

import os
import sys
from qgis.core import QgsApplication
from qgis.gui import QgisInterface
from qgis.PyQt.QtWidgets import QAction, QToolBar, QMenu, QMessageBox
from qgis.PyQt.QtGui import QIcon


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
        
        self.actions = []       # 所有 QAction
        self.menu = None        # 主菜单
        self.toolbar = None     # 工具栏
        self.dockwidget = None
        self.provider = None
        self._wdrip_ok = False

    def initGui(self):
        """初始化 GUI（菜单、工具栏、动作）"""
        # 验证 wdrip-core
        try:
            from wdrip.network import DripNetwork
            from wdrip.simulation import DripSimulation
            self._wdrip_ok = True
        except ImportError as e:
            self.iface.messageBar().pushWarning(
                self.tr("aQuaDrip"), self.tr("wdrip-core 加载失败: {}").format(e)
            )
            import traceback
            traceback.print_exc()
            return

        # 创建菜单
        self.menu = self.iface.pluginMenu().addMenu(self.tr("&aQuaDrip"))

        # 创建工具栏
        self.toolbar = self.iface.addToolBar("aQuaDrip")
        self.toolbar.setObjectName("aQuaDripToolBar")

        # 注册动作
        self._add_action(self.tr("新建项目"), "mActionNewProject",
                        self.on_new_project, self.tr("创建新灌溉项目"))
        self._add_action(self.tr("打开项目"), "mActionOpenProject",
                        self.on_open_project, self.tr("打开已有 .aqd 项目"))
        self._add_action(self.tr("保存项目"), "mActionSaveProject",
                        self.on_save_project, self.tr("保存当前项目"))
        
        self.menu.addSeparator()
        self.toolbar.addSeparator()
        
        self._add_action(self.tr("生成管网"), "mActionDraw",
                        self.on_generate_network, self.tr("农艺参数驱动自动生成管网"))
        self._add_action(self.tr("参数配置"), "mActionOptions",
                        self.on_configure, self.tr("配置滴头/管道/设备参数"))
        self._add_action(self.tr("运行模拟"), "mActionStart",
                        self.on_run_simulation, self.tr("运行 WNTR 水力模拟"))
        
        self.menu.addSeparator()
        self.toolbar.addSeparator()
        
        self._add_action(self.tr("结果分析"), "mActionReport",
                        self.on_show_results, self.tr("均匀度/压力/流量分析"))
        self._add_action(self.tr("导出 INP"), "mActionFileExit",
                        self.on_export_inp, self.tr("导出 EPANET INP 文件"))

    def unload(self):
        """卸载插件"""
        # 移除所有动作
        for action in self.actions:
            try:
                self.iface.removePluginMenu("&aQuaDrip", action)
                self.iface.removeToolBarIcon(action)
            except:
                pass
        self.actions.clear()
        
        # 移除菜单和工具栏
        if self.menu:
            self.menu.deleteLater()
            self.menu = None
        if self.toolbar:
            del self.toolbar
            self.toolbar = None
        
        # 移除 DockWidget
        if self.dockwidget:
            self.iface.removeDockWidget(self.dockwidget)
            self.dockwidget = None
        
        # 注销 Processing Provider
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

    # ---- 动作管理 ----

    def _add_action(self, text, icon_name, callback, tooltip=""):
        """添加菜单+工具栏动作"""
        icon = QgsApplication.getThemeIcon(icon_name)
        action = QAction(icon, text, self.iface.mainWindow())
        action.triggered.connect(callback)
        action.setToolTip(tooltip or text)
        action.setStatusTip(tooltip or text)
        
        self.menu.addAction(action)
        self.toolbar.addAction(action)
        self.actions.append(action)
        return action

    def _not_implemented(self, feature_name):
        """未实现功能提示"""
        QMessageBox.information(
            self.iface.mainWindow(),
            self.tr("aQuaDrip"),
            self.tr("「{}」功能将在后续版本中实现").format(feature_name)
        )

    def _check_wdrip(self):
        """检查 wdrip-core 是否可用"""
        if not self._wdrip_ok:
            QMessageBox.warning(
                self.iface.mainWindow(),
                self.tr("aQuaDrip"),
                self.tr("wdrip-core 核心库未加载，请检查安装")
            )
            return False
        return True

    # ---- 占位回调 ----

    def on_new_project(self):
        self._not_implemented(self.tr("新建项目"))

    def on_open_project(self):
        self._not_implemented(self.tr("打开项目"))

    def on_save_project(self):
        self._not_implemented(self.tr("保存项目"))

    def on_generate_network(self):
        if not self._check_wdrip():
            return
        self._not_implemented(self.tr("生成管网"))

    def on_configure(self):
        if not self._check_wdrip():
            return
        self._not_implemented(self.tr("参数配置"))

    def on_run_simulation(self):
        if not self._check_wdrip():
            return
        self._not_implemented(self.tr("运行模拟"))

    def on_show_results(self):
        if not self._check_wdrip():
            return
        self._not_implemented(self.tr("结果分析"))

    def on_export_inp(self):
        if not self._check_wdrip():
            return
        self._not_implemented(self.tr("导出 INP"))

    # ---- 国际化 ----

    @staticmethod
    def tr(message):
        """简单 i18n 支持（后续接入 QGIS 翻译系统）"""
        return message
