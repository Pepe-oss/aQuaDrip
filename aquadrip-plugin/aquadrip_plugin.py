# -*- coding: utf-8 -*-
"""
aQuaDrip 插件主类 — 菜单、工具栏、状态机、事件总线
"""

import os
import sys
from qgis.core import QgsApplication
from qgis.gui import QgisInterface
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.PyQt.QtCore import Qt

from .tools.state_machine import ProjectStateMachine, ProjectState
from .tools.event_bus import EventBus, SIMULATION_PROGRESS, ERROR_OCCURRED


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
        
        # 状态机
        self.state_machine = ProjectStateMachine()
        self.state_machine.add_listener(self._on_state_changed)
        
        # 事件总线
        self.event_bus = EventBus()
        
        # 动作字典 {name: QAction}
        self.actions = {}
        self.menu = None
        self.toolbar = None
        self.dockwidget = None
        self.provider = None
        self._wdrip_ok = False

    # ---- 初始化 ----

    def initGui(self):
        """初始化 GUI"""
        try:
            from wdrip.network import DripNetwork
            from wdrip.simulation import DripSimulation
            self._wdrip_ok = True
        except ImportError as e:
            self.iface.messageBar().pushWarning(
                self.tr("aQuaDrip"), self.tr("wdrip-core 加载失败: {}").format(e))
            import traceback; traceback.print_exc()
            return

        # 菜单
        self.menu = self.iface.pluginMenu().addMenu(self.tr("&aQuaDrip"))

        # 工具栏
        self.toolbar = self.iface.addToolBar("aQuaDrip")
        self.toolbar.setObjectName("aQuaDripToolBar")

        # 注册动作（按功能分组）
        self._add_actions([
            ("new_project",    "mActionNewProject",    self.tr("新建项目")),
            ("open_project",   "mActionOpenProject",   self.tr("打开项目")),
            ("save_project",   "mActionSaveProject",   self.tr("保存项目")),
        ])
        self.menu.addSeparator()
        self.toolbar.addSeparator()
        
        self._add_actions([
            ("draw_field",     "mActionDraw",          self.tr("绘制农田")),
            ("select",         "mActionSelect",        self.tr("选择要素")),
            ("delete",         "mActionDeleteSelected", self.tr("删除要素")),
            ("draw_pump",      "mActionAdd",          self.tr("绘制水泵")),
            ("draw_valve",     "mActionAdd",          self.tr("绘制阀门")),
            ("gen_network",    "mActionProcessing",    self.tr("生成管网")),
            ("configure",      "mActionOptions",       self.tr("参数配置")),
        ])
        self.menu.addSeparator()
        self.toolbar.addSeparator()
        
        self._add_actions([
            ("run_simulation", "mActionStart",         self.tr("运行模拟")),
            ("show_results",   "mActionReport",        self.tr("结果分析")),
            ("calibrate",      "mActionReFresh",       self.tr("模型校准")),
            ("export_inp",     "mActionFileExit",      self.tr("导出 INP")),
        ])
        
        # 初始化按钮状态
        self._update_actions()

        # 创建 DockWidget
        from .ui.dockwidget import AQuaDripDockWidget
        self.dockwidget = AQuaDripDockWidget(self.iface)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dockwidget)
        
        # 当前激活的地图工具
        self._active_tool = None

        # 连接 DockWidget 信号
        self.dockwidget.button_clicked.connect(self._on_dockwidget_button)

        # 连接事件总线到日志
        self.event_bus.on(SIMULATION_PROGRESS, lambda msg: self.dockwidget.log_message(msg))

        # 初始化图层管理器（不创建图层，等新建项目时再创建）
        from .tools.layer_manager import LayerManager
        self.layer_manager = LayerManager()

        # 初始化样式管理器
        from .tools.style_manager import StyleManager
        self.style_manager = StyleManager()

        self.dockwidget.log_message(self.tr("aQuaDrip 已加载"))
        self.dockwidget.log_message(self.tr("wdrip-core 核心库就绪"))
        self.dockwidget.log_message(self.tr("点击「新建项目」开始设计"))

    def unload(self):
        """卸载插件"""
        for name, action in self.actions.items():
            try:
                self.iface.removePluginMenu("&aQuaDrip", action)
                self.iface.removeToolBarIcon(action)
            except:
                pass
        self.actions.clear()
        
        if self.menu:
            self.menu.deleteLater(); self.menu = None
        if self.toolbar:
            del self.toolbar; self.toolbar = None
        if self.dockwidget:
            self.iface.removeDockWidget(self.dockwidget); self.dockwidget = None
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
        
        # 清理事件总线
        self.event_bus.clear()

        # 清理图层
        if hasattr(self, 'layer_manager'):
            self.layer_manager.clear_layers()
        
        # 清理地图工具
        if self._active_tool:
            self.iface.mapCanvas().unsetMapTool(self._active_tool)
            self._active_tool = None

    # ---- 动作管理 ----

    def _add_actions(self, action_defs):
        """批量添加动作"""
        for key, icon_name, text in action_defs:
            icon = QgsApplication.getThemeIcon(icon_name)
            action = QAction(icon, text, self.iface.mainWindow())
            action.triggered.connect(lambda checked, k=key: self._on_action(k))
            action.setToolTip(text)
            action.setStatusTip(text)
            
            self.menu.addAction(action)
            self.toolbar.addAction(action)
            self.actions[key] = action

    def _on_action(self, key):
        """动作分发"""
        if not self._check_wdrip():
            return
        handler = getattr(self, f"_handle_{key}", None)
        if handler:
            handler()
        else:
            self._not_implemented(key)

    # ---- 状态驱动 UI ----

    def _on_state_changed(self, old_state, new_state):
        """状态变化时更新 UI"""
        self._update_actions()
        if self.dockwidget:
            self.dockwidget.log_message(f"状态: {old_state.value} → {new_state.value}")
        self.iface.messageBar().pushMessage(
            self.tr("aQuaDrip"),
            f"{old_state.value} → {new_state.value}",
            level=0, duration=3
        )

    def _on_dockwidget_button(self, button_name):
        """DockWidget 按钮回调"""
        action_map = {
            "generate_network": "gen_network",
            "configure": "configure",
            "run_simulation": "run_simulation",
            "show_results": "show_results",
        }
        key = action_map.get(button_name)
        if key:
            self._on_action(key)

    def _update_actions(self):
        """根据当前状态更新按钮启用/禁用"""
        s = self.state_machine
        disabled = 0
        
        # 新建/打开 — 始终可用
        self._set_enabled("new_project", True)
        self._set_enabled("open_project", True)
        
        # 保存 — 有内容才可保存
        self._set_enabled("save_project", s.has_field)
        
        # 绘制农田 — NEW 或 FIELD 状态可用
        self._set_enabled("draw_field", s.state in [ProjectState.NEW, ProjectState.FIELD_IMPORTED])
        
        # 选择要素 — 有图层即可
        self._set_enabled("select", s.has_field)
        
        # 生成管网 — 有农田，未锁定
        self._set_enabled("gen_network", s.has_field and not s.is_simulating)
        
        # 参数配置 — 有管网即可
        self._set_enabled("configure", s.has_network and not s.is_simulating)
        
        # 运行模拟 — SIMULATION_READY 状态
        self._set_enabled("run_simulation", s.can_simulate)
        
        # 结果分析 — 有结果
        self._set_enabled("show_results", s.has_results)
        
        # 模型校准 — 有结果
        self._set_enabled("calibrate", s.has_results)
        
        # 导出 — 有结果
        self._set_enabled("export_inp", s.has_results)

    def _handle_draw_field(self):
        """激活农田绘制工具"""
        from .tools.field_draw_tool import FieldDrawTool
        self._set_tool(FieldDrawTool(self.iface, self.layer_manager))
        self.state_machine.transition_to(ProjectState.FIELD_IMPORTED)

    def _handle_select(self):
        """激活选择工具"""
        from .tools.selection_tool import SelectionTool
        self._set_tool(SelectionTool(self.iface, self.layer_manager))

    def _handle_delete(self):
        """激活删除工具"""
        from .tools.delete_tool import DeleteTool
        self._set_tool(DeleteTool(self.iface, self.layer_manager))

    def _handle_draw_pump(self):
        """激活水泵绘制工具"""
        from .tools.pump_draw_tool import PumpDrawTool
        self._set_tool(PumpDrawTool(self.iface, self.layer_manager))

    def _handle_draw_valve(self):
        """激活阀门绘制工具"""
        from .tools.valve_draw_tool import ValveDrawTool
        self._set_tool(ValveDrawTool(self.iface, self.layer_manager))

    def _set_tool(self, tool):
        """设置当前地图工具"""
        if self._active_tool:
            self._active_tool.deactivate()
        self._active_tool = tool
        self.iface.mapCanvas().setMapTool(tool)

    def _set_enabled(self, key, enabled):
        """设置按钮启用状态"""
        action = self.actions.get(key)
        if action:
            action.setEnabled(enabled)

    # ---- 功能区（后续 Sprint 实现）----

    def _handle_new_project(self):
        """新建项目"""
        # 清理旧图层
        self.layer_manager.clear_layers()
        # 创建新图层
        self.layer_manager.setup()
        self.style_manager.apply_default_styles(self.layer_manager.get_all_layers())
        # 更新项目树
        self.dockwidget.update_project_tree("未命名项目")
        # 重置状态机
        self.state_machine.reset()
        self.dockwidget.log_message(self.tr("新建项目 — 图层已就绪"))
        self.dockwidget.log_message(self.tr("请绘制或导入农田地块"))

    def _handle_open_project(self):
        from qgis.PyQt.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            self.tr("打开项目"), "",
            self.tr("aQuaDrip 项目 (*.aqd)"))
        if path:
            self._not_implemented(self.tr("打开项目"))

    def _handle_save_project(self):
        from qgis.PyQt.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            self.tr("保存项目"), "",
            self.tr("aQuaDrip 项目 (*.aqd)"))
        if path:
            self._not_implemented(self.tr("保存项目"))

    def _handle_gen_network(self):
        self._not_implemented(self.tr("生成管网"))

    def _handle_configure(self):
        self._not_implemented(self.tr("参数配置"))

    def _handle_run_simulation(self):
        self._not_implemented(self.tr("运行模拟"))

    def _handle_show_results(self):
        self._not_implemented(self.tr("结果分析"))

    def _handle_calibrate(self):
        self._not_implemented(self.tr("模型校准"))

    def _handle_export_inp(self):
        self._not_implemented(self.tr("导出 INP"))

    # ---- 工具方法 ----

    def _not_implemented(self, name):
        QMessageBox.information(
            self.iface.mainWindow(),
            self.tr("aQuaDrip"),
            self.tr("「{}」功能将在后续版本中实现").format(name))

    def _check_wdrip(self):
        if not self._wdrip_ok:
            QMessageBox.warning(
                self.iface.mainWindow(),
                self.tr("aQuaDrip"),
                self.tr("wdrip-core 核心库未加载"))
            return False
        return True

    @staticmethod
    def tr(message):
        return message
