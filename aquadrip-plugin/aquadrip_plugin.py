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
        """初始化 GUI（菜单 + 工具栏）"""
        # 验证 wdrip-core
        try:
            from wdrip.network import DripNetwork
            self._wdrip_ok = True
        except ImportError as e:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", f"wdrip-core 加载失败: {e}")
            self._wdrip_ok = False
            return

        # 创建菜单与工具栏
        menu = self.iface.pluginMenu().addMenu("&aQuaDrip")
        toolbar = self.iface.addToolBar("aQuaDrip")
        toolbar.setObjectName("aQuaDripToolBar")
        self.toolbar = toolbar

        # 创建主面板（仅日志区）
        from .ui.dockwidget import AQuaDripDockWidget
        self.dockwidget = AQuaDripDockWidget(self.iface)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dockwidget)
        self.dockwidget.log_message("aQuaDrip 已加载")

        # 功能列表：(图标, 名称, handler, tooltip)
        entries = [
            ("mActionNewVectorLayer", "生成图层", self.on_setup_layers,
             "创建 aQuaDrip 标准 GeoPackage 图层"),
            ("mActionAddOgrLayer", "毛管生成", self.on_generate_lateral,
             "选中农田地块后，设置农艺参数并生成毛管"),
            ("mActionSplitFeatures", "切割管道", self.on_trim_lateral,
             "点击管道在任意位置将其分割为两段"),
            ("mActionCreateMemoryLayer", "生成交叉节点", self.on_generate_crossing_nodes,
             "选中一条支管后，为其与所有毛管的交叉点生成节点"),
            ("mActionEditTable", "编辑属性", self.on_edit_property,
             "选中地块/管道/节点后，修改其内部参数"),
            ("mActionStart", "运行模拟", self.on_run_simulation,
             "同步图层→构建管网→WNTR 水力模拟→结果回写"),
        ]
        for icon, name, handler, tip in entries:
            action = QAction(QgsApplication.getThemeIcon(icon),
                             name, self.iface.mainWindow())
            action.triggered.connect(handler)
            action.setToolTip(tip)
            menu.addAction(action)
            toolbar.addAction(action)
            self.actions.append(action)

    def unload(self):
        """卸载插件"""
        for action in self.actions:
            try:
                self.iface.removePluginMenu("&aQuaDrip", action)
                self.iface.removeToolBarIcon(action)
            except:
                pass
        self.actions.clear()

        if getattr(self, "toolbar", None):
            try:
                del self.toolbar
            except Exception:
                pass
            self.toolbar = None

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
            success = setup.setup_layers()
            
            if success:
                QMessageBox.information(
                    self.iface.mainWindow(),
                    "aQuaDrip",
                    f"图层已创建完成\n\n"
                    f"文件位置: {setup.gpkg_path}\n\n"
                    f"• 农田地块 (aqd_fields)\n"
                    f"• 管道 (aqd_pipes) — 干管/支管/毛管/设备\n"
                    f"• 节点 (aqd_nodes) — 水源/施肥罐\n"
                    f"• 观测点 (aqd_obs_points)"
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

    def on_trim_lateral(self):
        """激活管道切割工具"""
        self._trim_dlg = None
        from .ui.trim_dialog import TrimDialog
        dlg = TrimDialog(self.iface.mainWindow())
        dlg.apply_clicked.connect(lambda p: self._on_trim_apply(p))
        dlg.finished.connect(lambda: setattr(self, '_trim_dlg', None))
        self._trim_dlg = dlg
        dlg.show()

    def _on_trim_apply(self, params):
        """切割参数确认后激活工具"""
        from .tools.trim_tool import TrimTool
        tool = TrimTool(self.iface, params["pipe_types"], params["cut_length"])
        self.iface.mapCanvas().setMapTool(tool)

    def on_generate_crossing_nodes(self):
        """为选中的支管生成与毛管的交叉节点"""
        layer = self.iface.activeLayer()
        if layer is None:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "请先在图层面板选中 aqd_pipes 图层")
            return

        source = layer.source() if hasattr(layer, "source") else ""
        if "aqd_pipes" not in source:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "当前活动图层不是 aqd_pipes")
            return

        selected = layer.selectedFeatures()
        selected = list(selected)
        if len(selected) != 1:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "请恰好选中 1 条支管（pipe_type=submain）")
            return

        feat = selected[0]
        ptype = str(feat.attribute("pipe_type") or "")
        if ptype != "submain":
            self.iface.messageBar().pushWarning(
                "aQuaDrip", f"选中要素 pipe_type={ptype or '空'}，应为 submain（支管）")
            return

        try:
            from .tools.crossing_node_tool import CrossingNodeGenerator
            CrossingNodeGenerator(self.iface).generate(feat)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.iface.messageBar().pushWarning(
                "aQuaDrip", f"生成交叉节点失败: {e}")

    def on_generate_lateral(self):
        """毛管生成：选中农田地块 → 参数浮动窗（含生成按钮）"""
        feat, layer = self._get_single_selected("aqd_fields")
        if feat is None:
            return
        from .ui.property_dialog import PropertyDialog
        # 必须存为实例属性：局部变量 show() 后会被 GC，
        # 导致信号（按钮/联动）全部断开，对话框"假活"
        self._prop_dlg = PropertyDialog(
            self.iface, layer, feat, show_generate=True,
            parent=self.iface.mainWindow())
        self._prop_dlg.finished.connect(
            lambda: setattr(self, "_prop_dlg", None))
        self._prop_dlg.show()

    def on_edit_property(self):
        """编辑属性：选中地块/管道/节点 → 对应属性浮动窗"""
        feat, layer = self._get_single_selected(None)
        if feat is None:
            return
        try:
            from .ui.property_dialog import PropertyDialog
            self._edit_dlg = PropertyDialog(
                self.iface, layer, feat, parent=self.iface.mainWindow())
            self._edit_dlg.finished.connect(
                lambda: setattr(self, "_edit_dlg", None))
            self._edit_dlg.show()
        except ValueError as e:
            self.iface.messageBar().pushWarning("aQuaDrip", str(e))

    def _get_single_selected(self, required_layer_key):
        """获取当前唯一选中要素

        Args:
            required_layer_key: 指定图层名（如 "aqd_fields"），
                None 表示接受任意 aQuaDrip 图层（地块/管道/节点）

        Returns:
            (feat, layer) 或 (None, None)（已弹提示）
        """
        layer = self.iface.activeLayer()
        if layer is None or not hasattr(layer, "selectedFeatures"):
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "请先在图层面板选中相应图层和要素")
            return None, None

        if required_layer_key:
            src = layer.source() or ""
            if layer.name() != required_layer_key and required_layer_key not in src:
                self.iface.messageBar().pushWarning(
                    "aQuaDrip", f"当前活动图层不是 {required_layer_key}")
                return None, None
        else:
            from .ui.property_dialog import PropertyDialog
            if PropertyDialog._mode_of_layer(layer) is None:
                self.iface.messageBar().pushWarning(
                    "aQuaDrip", "当前图层不是 aQuaDrip 图层（地块/管道/节点）")
                return None, None

        selected = list(layer.selectedFeatures())
        if len(selected) != 1:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "请恰好选中 1 个要素")
            return None, None
        return selected[0], layer

    def on_run_simulation(self):
        """运行水力模拟：同步→构建→展开滴头→WNTR→结果回写→CU/DU 统计"""
        try:
            from .tools.sync_manager import SyncManager

            sync = SyncManager(self.iface)
            net = sync.sync_qgis_to_network()

            # 预检：必须有水源
            sources = [n for n in net.nodes.values()
                       if hasattr(n, "source_type")]
            if not sources:
                QMessageBox.warning(
                    self.iface.mainWindow(), "aQuaDrip",
                    "管网中没有水源节点。\n\n"
                    "请先用「添加水源」在地图上放置水源。")
                return
            if not net.links:
                QMessageBox.warning(
                    self.iface.mainWindow(), "aQuaDrip",
                    "管网中没有管道。")
                return

            # 校验：显示问题但允许继续（死端等在构建期常见）
            errors = net.validate()
            if errors and self.dockwidget:
                for e in errors[:5]:
                    self.dockwidget.log_message(f"⚠️ 校验: {e}")

            # 运行模拟（小管网秒级，同步执行 + 等待光标）
            from wdrip.simulation import DripSimulation
            from qgis.PyQt.QtWidgets import QApplication
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                sim = DripSimulation(net)
                result = sim.run()
            finally:
                QApplication.restoreOverrideCursor()

            if not result.success:
                QMessageBox.critical(
                    self.iface.mainWindow(), "aQuaDrip",
                    f"模拟失败：\n{result.message}")
                return

            # 结果回写图层
            sync.sync_from_network(net, result)

            # CU/DU 均匀度统计
            from wdrip.analysis import UniformityAnalyzer
            flows = [float(arr[0]) for arr in result.emitter_flow.values()
                     if len(arr) > 0]
            cu = UniformityAnalyzer.cu(flows) if flows else 0.0
            du = UniformityAnalyzer.du(flows) if flows else 0.0

            stats = [
                f"✅ {result.message}",
                f"节点 {len(net.nodes)} / 管道 {len(net.links)} / 滴头 {len(flows)}",
            ]
            if flows:
                stats.append(
                    f"滴头流量 {min(flows):.2f}~{max(flows):.2f} L/h")
                stats.append(f"CU = {cu:.1f}%   DU = {du:.1f}%")

            if self.dockwidget:
                for line in stats:
                    self.dockwidget.log_message(line)
            QMessageBox.information(
                self.iface.mainWindow(), "aQuaDrip 模拟完成",
                "\n".join(stats))

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            traceback.print_exc()
            if self.dockwidget:
                self.dockwidget.log_message(f"❌ 模拟运行失败: {e}")
                # 输出关键堆栈行，便于定位
                for line in tb.strip().splitlines()[-6:]:
                    self.dockwidget.log_message(f"   {line}")
            self.iface.messageBar().pushWarning(
                "aQuaDrip", f"模拟运行失败: {e}")
