# -*- coding: utf-8 -*-
"""
aQuaDrip 插件主类
"""

import os
import sys
from qgis.core import QgsApplication, QgsRasterLayer, QgsLayerTreeLayer
from qgis.gui import QgisInterface
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QApplication


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
        self._active_threads = []  # 追踪所有活跃后台线程

    def initGui(self):
        """初始化 GUI（菜单 + 工具栏）"""
        # 验证 wdrip-core
        try:
            from wdrip.network import DripNetwork
            self._wdrip_ok = True
        except ImportError as e:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "wdrip-core 加载失败: {0}").format(e))
            self._wdrip_ok = False
            return

        # 创建菜单与工具栏
        menu = self.iface.pluginMenu().addMenu("&aQuaDrip")
        self._menu = menu  # unload 时移除整个子菜单
        toolbar = self.iface.addToolBar("aQuaDrip")
        toolbar.setObjectName("aQuaDripToolBar")
        self.toolbar = toolbar

        # 创建主面板（仅日志区）
        from .ui.dockwidget import AQuaDripDockWidget
        self.dockwidget = AQuaDripDockWidget(self.iface)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dockwidget)
        self.dockwidget.log_message(QApplication.translate("AquadripPlugin", "aQuaDrip 已加载"))

        # 校准 tab 按钮连接
        self.dockwidget._btn_refresh.clicked.connect(self._on_calib_refresh)
        self.dockwidget._btn_resim.clicked.connect(self.on_run_simulation)
        self.dockwidget._btn_calibrate.clicked.connect(self._on_calib_run)
        # 轮灌 tab 按钮连接
        self.dockwidget._btn_rot_visualize.clicked.connect(self._on_rot_visualize)

        # 自定义图标路径
        from qgis.PyQt.QtGui import QIcon
        _icons = os.path.join(os.path.dirname(__file__), "icons")
        _icon = lambda name: QIcon(os.path.join(_icons, name))

        # 功能列表：(图标文件, 名称, handler, tooltip)
        entries = [
            ("generate_layers.svg", QApplication.translate("AquadripPlugin", "生成图层"), self.on_setup_layers,
             QApplication.translate("AquadripPlugin", "创建 aQuaDrip 标准 GeoPackage 图层")),
            ("open_project.svg", QApplication.translate("AquadripPlugin", "打开项目"), self.on_open_project,
             QApplication.translate("AquadripPlugin", "打开已有的 aQuaDrip GeoPackage 项目")),
            ("generate_laterals.svg", QApplication.translate("AquadripPlugin", "毛管生成"), self.on_generate_lateral,
             QApplication.translate("AquadripPlugin", "选中农田地块后，设置农艺参数并生成毛管")),
            ("trim_pipe.svg", QApplication.translate("AquadripPlugin", "切割管道"), self.on_trim_lateral,
             QApplication.translate("AquadripPlugin", "点击管道在任意位置将其分割为两段")),
            ("crossing_nodes.svg", QApplication.translate("AquadripPlugin", "生成交叉节点"), self.on_generate_crossing_nodes,
             QApplication.translate("AquadripPlugin", "选中一条管道后，为其与所有不同类型管道的交叉点生成连接节点")),
            ("edit_properties.svg", QApplication.translate("AquadripPlugin", "编辑属性"), self.on_edit_property,
             QApplication.translate("AquadripPlugin", "选中地块/管道/节点后，修改其内部参数")),
            ("run_simulation.svg", QApplication.translate("AquadripPlugin", "运行模拟"), self.on_run_simulation,
             QApplication.translate("AquadripPlugin", "同步图层→构建管网→WNTR 水力模拟→结果回写")),
            ("visualize.svg", QApplication.translate("AquadripPlugin", "可视化"), self.on_visualize,
             QApplication.translate("AquadripPlugin", "查看历史模拟记录，生成结果可视化图层")),
            ("zone_divide.svg", QApplication.translate("AquadripPlugin", "分区划分"), self.on_zone_divide,
             QApplication.translate("AquadripPlugin", "根据阀门位置自动划分管网分区")),
            ("rotation.svg", QApplication.translate("AquadripPlugin", "轮灌管理"), self.on_rotation,
             QApplication.translate("AquadripPlugin", "配置轮灌调度方案并逐轮次运行水力模拟")),
            ("pipe_pressure.svg", QApplication.translate("AquadripPlugin", "管道承压"), self.on_pipe_pressure_check,
             QApplication.translate("AquadripPlugin", "根据模拟结果检测管道超压泄漏风险")),
            ("inp_tools.svg", QApplication.translate("AquadripPlugin", "导出 INP"), self.on_export_inp,
             QApplication.translate("AquadripPlugin", "导出当前管网为 EPANET INP 文件")),
        ]
        for filename, name, handler, tip in entries:
            action = QAction(_icon(filename),
                             name, self.iface.mainWindow())
            if handler is not None:
                action.triggered.connect(handler)
            action.setToolTip(tip)
            menu.addAction(action)
            toolbar.addAction(action)
            self.actions.append(action)

        # 语言切换子菜单(元 UI 双语硬编码——用户尚未选择语言时也要能看懂)
        self._add_language_menu(menu)

    def unload(self):
        """卸载插件"""
        for action in self.actions:
            try:
                self.iface.removePluginMenu("&aQuaDrip", action)
                self.iface.removeToolBarIcon(action)
            except Exception:
                pass
        self.actions.clear()

        # 移除 "&aQuaDrip" 子菜单本身（removePluginMenu 只移除 action，
        # 不移除菜单，否则空菜单残留在插件菜单里）
        menu = getattr(self, "_menu", None)
        if menu is not None:
            try:
                plugin_menu = self.iface.pluginMenu()
                plugin_menu.removeAction(menu.menuAction())
                menu.deleteLater()
            except Exception:
                pass
            self._menu = None

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

        # 关闭可能仍开着的非模态对话框，避免其信号回调访问已销毁的主对象
        for attr in ("_prop_dlg", "_edit_dlg", "_trim_dlg", "_viz_dlg",
                     "_rot_dlg", "_calib_dlg"):
            dlg = getattr(self, attr, None)
            if dlg is not None:
                try:
                    dlg.close()
                    dlg.deleteLater()
                except Exception:
                    pass
                setattr(self, attr, None)

        # 断开所有活跃线程/worker 的信号连接（让它们自行结束，不阻塞卸载）
        self._stop_all_threads()

        # 卸载翻译器
        from .tools.i18n import remove_translator
        remove_translator()

    # ── 语言切换 ──

    def _add_language_menu(self, parent_menu):
        """在插件菜单尾部添加语言子菜单(重启 QGIS 后生效)"""
        from qgis.PyQt.QtWidgets import QMenu
        from qgis.PyQt.QtCore import QSettings
        from .tools.i18n import LANGUAGES, SETTING_KEY

        lang_menu = QMenu(QApplication.translate("AquadripPlugin", "语言 Language"), parent_menu)
        current = QSettings().value(SETTING_KEY, "auto", type=str) or "auto"
        # 元 UI:标签双语硬写,不经过 tr()(用户可能尚未选择语言)
        labels = {
            "auto": QApplication.translate("AquadripPlugin", "自动(跟随 QGIS) Auto (follow QGIS)"),
            "zh_CN": QApplication.translate("AquadripPlugin", "简体中文"),
            "en_US": "English",
        }
        for key in LANGUAGES:
            act = lang_menu.addAction(labels.get(key, key))
            act.setCheckable(True)
            act.setChecked(key == current)
            act.triggered.connect(lambda _=False, k=key: self._on_language_selected(k))
        parent_menu.addSeparator()
        parent_menu.addMenu(lang_menu)

    def _on_language_selected(self, key: str):
        from .tools.i18n import set_language
        msg = set_language(key)
        self.iface.messageBar().pushMessage("aQuaDrip", msg, level=0, duration=8)

    # ── 线程安全管理 ──

    def _stop_all_threads(self):
        """插件卸载时断开活跃线程/worker 的信号连接

        同时断开 worker 的 progress_changed/finished/error_occurred 信号，
        防止后台 worker 完成后通过 lambda 回调访问已销毁的对话框 → 段错误。
        """
        for entry in list(getattr(self, '_active_threads', [])):
            thread, worker = entry if isinstance(entry, tuple) else (entry, None)
            try:
                if worker is not None:
                    # 断开 worker 所有信号，避免回调触及已销毁的 UI
                    try:
                        worker.progress_changed.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                    try:
                        worker.finished.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                    try:
                        worker.error_occurred.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                if thread.isRunning():
                    try:
                        thread.finished.disconnect()
                    except (TypeError, RuntimeError):
                        pass
            except Exception:
                pass
        self._active_threads.clear()

    def _track_thread(self, thread: 'QThread', worker=None):
        """将线程加入活跃列表，finished 时自动清理

        Args:
            thread: QThread 实例
            worker: 可选的 SimulationWorker / RotationWorker，用于卸载时
                断开信号和 deleteLater 清理
        """
        self._active_threads.append((thread, worker))

        def on_finished():
            try:
                entry = (thread, worker)
                if entry in self._active_threads:
                    self._active_threads.remove(entry)
                thread.deleteLater()
                if worker is not None:
                    worker.deleteLater()
            except Exception:
                pass

        thread.finished.connect(on_finished)

    def on_setup_layers(self):
        """新建 aQuaDrip 项目：弹窗选择路径/可选影像/DEM → 创建 GPKG + QGZ

        CRS 统一策略：优先用导入栅格（正射/DEM）的 CRS 创建 GPKG，
        使矢量与栅格坐标系一致，避免后续高程采样等地形分析的 CRS 转换。
        """
        from .ui.new_project_dialog import NewProjectDialog

        dlg = NewProjectDialog(self.iface)
        if dlg.exec() != dlg.Accepted:
            return

        gpkg_path = dlg.gpkg_path()
        qgz_path = dlg.qgz_path()
        ortho_path = dlg.orthophoto_path()
        dem_path = dlg.dem_path()

        # 0. 探测导入栅格的 CRS，优先 DEM，其次正射
        target_crs = None
        for path in (dem_path, ortho_path):
            if not path:
                continue
            try:
                from qgis.core import QgsRasterLayer
                rl = QgsRasterLayer(path)
                if rl.isValid() and rl.crs().isValid():
                    target_crs = rl.crs()
                    break
            except Exception:
                pass

        # 1. 创建 GPKG 图层（用 target_crs 统一坐标系）
        self.iface.messageBar().pushMessage(
            "aQuaDrip", QApplication.translate("AquadripPlugin", "正在创建图层..."), level=0, duration=3)

        try:
            from .tools.layer_setup import LayerSetupAction

            setup = LayerSetupAction(self.iface)
            success = setup.setup_layers(gpkg_path, target_crs=target_crs)

            if not success:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "aQuaDrip",
                    QApplication.translate("AquadripPlugin", "图层创建失败，请查看 Python 日志"))
                return

            used_crs = setup._project_crs
            if self.dockwidget:
                self.dockwidget.log_message(
                    QApplication.translate("AquadripPlugin", "图层已创建: {0} (CRS: {1})").format(gpkg_path, used_crs.authid()))

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "创建失败: {0}").format(e))
            return

        # 2. 导入正射影像（可选）
        ortho_layer = self._add_raster_to_group(
            ortho_path, "Orthophoto") if ortho_path else None

        # 3. 导入 DEM（可选）
        dem_layer = self._add_raster_to_group(
            dem_path, "DEM") if dem_path else None  # 图层名是数据标识,不翻译(与查找逻辑耦合)

        # 4. 保存 QGZ 项目文件
        try:
            from qgis.core import QgsProject
            # 设置项目 CRS 与图层一致（避免"无坐标系"提示）
            if target_crs is not None and target_crs.isValid():
                QgsProject.instance().setCrs(target_crs)
            QgsProject.instance().write(qgz_path)
            if self.dockwidget:
                self.dockwidget.log_message(QApplication.translate("AquadripPlugin", "项目已保存: {0}").format(qgz_path))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "保存 QGZ 失败: {0}").format(e))
            # 不阻断：GPKG 已创建，用户可手动保存

        # 5. 成功提示
        parts = [f"📁 GPKG: {gpkg_path}", f"📁 QGZ:  {qgz_path}"]
        if target_crs is not None:
            parts.append(f"🌐 CRS:  {target_crs.authid()}")
        # 图层名已英文化(Fields/Pipes/...),完成消息直接列表名(语言无关)
        loaded = ["aqd_fields", "aqd_pipes", "aqd_nodes", "aqd_obs_points"]
        if ortho_layer:
            loaded.append("Orthophoto")
        if dem_layer:
            loaded.append("DEM")

        QMessageBox.information(
            self.iface.mainWindow(),
            "aQuaDrip",
            QApplication.translate("AquadripPlugin", "项目创建完成\n\n{0}\n\n已加载图层:\n").format(os.linesep.join(parts))
            + "\n".join(f"  • {s}" for s in loaded) + QApplication.translate("AquadripPlugin", "\n\n下次可直接用 QGIS 打开 .qgz 文件，\n或通过「打开项目」加载 .gpkg。").format())

    def _add_raster_to_group(self, path: str, layer_name: str,
                             group_name: str = "aQuaDrip"):
        """添加栅格图层到指定分组底部

        Args:
            path: 栅格文件路径
            layer_name: 图层显示名称
            group_name: 目标分组名

        Returns:
            QgsRasterLayer 或 None
        """
        if not path or not os.path.exists(path):
            return None

        layer = QgsRasterLayer(path, layer_name)
        if not layer.isValid():
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "无法加载栅格图层: {0}").format(layer_name))
            return None

        from qgis.core import QgsProject
        QgsProject.instance().addMapLayer(layer, False)

        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(group_name)
        if group:
            group.addChildNode(QgsLayerTreeLayer(layer))
        else:
            # 分组不存在时，直接添加到根层级
            root.addChildNode(QgsLayerTreeLayer(layer))

        return layer

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
        tool = TrimTool(self.iface, params["pipe_types"],
                        params["cut_length"], params.get("mode", "click"))
        self.iface.mapCanvas().setMapTool(tool)

    def on_generate_crossing_nodes(self):
        """为选中的管道生成与所有不同类型管道的连接节点"""
        layer = self.iface.activeLayer()
        if layer is None:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "请先在图层面板选中 aqd_pipes 图层"))
            return

        source = layer.source() if hasattr(layer, "source") else ""
        layer_name = layer.name() or ""
        is_link_layer = any(k in source or layer_name == k
                           for k in ("aqd_pipes", "aqd_pumps", "aqd_valves"))
        if not is_link_layer:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "当前活动图层不是 aqd_pipes / aqd_pumps / aqd_valves"))
            return

        selected = layer.selectedFeatures()
        selected = list(selected)
        if len(selected) != 1:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "请恰好选中 1 条管道"))
            return

        feat = selected[0]
        ptype = str(feat.attribute("pipe_type") or "")
        if not ptype:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "选中要素的 pipe_type 为空，请先设置管道类型"))
            return

        try:
            from .tools.crossing_node_tool import CrossingNodeGenerator
            CrossingNodeGenerator(self.iface).generate(feat, layer)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "生成连接节点失败: {0}").format(e))

    def on_generate_lateral(self):
        """毛管生成：选中农田地块 → 参数浮动窗（含生成按钮）"""
        feat, layer = self._get_single_selected("aqd_fields")
        if feat is None:
            return
        from .ui.property_dialog import PropertyDialog
        # 必须存为实例属性：局部变量 show() 后会被 GC，
        # 导致信号（按钮/联动）全部断开，对话框"假活"
        self._prop_dlg = PropertyDialog(
            self.iface, layer, [feat], show_generate=True,
            parent=self.iface.mainWindow())
        self._prop_dlg.finished.connect(
            lambda: setattr(self, "_prop_dlg", None))
        self._prop_dlg.show()

    def on_edit_property(self):
        """编辑属性：选中同类型要素 → 批量修改浮动窗"""
        feats, layer = self._get_selected_for_edit()
        if not feats:
            return
        try:
            from .ui.property_dialog import PropertyDialog
            self._edit_dlg = PropertyDialog(
                self.iface, layer, feats, parent=self.iface.mainWindow())
            self._edit_dlg.finished.connect(
                lambda: setattr(self, "_edit_dlg", None))
            self._edit_dlg.show()
        except ValueError as e:
            self.iface.messageBar().pushWarning("aQuaDrip", str(e))

    def _get_selected_for_edit(self):
        """获取当前选中要素（支持多选），校验同一图层+同类型

        Returns:
            (feats, layer) — feats 为非空列表，校验通过；否则 (None, None)
        """
        layer = self.iface.activeLayer()
        if layer is None or not hasattr(layer, "selectedFeatures"):
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "请先在图层面板选中相应图层和要素"))
            return None, None

        from .ui.property_dialog import PropertyDialog
        mode = PropertyDialog._mode_of_layer(layer)
        if mode is None:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "当前图层不是 aQuaDrip 图层（地块/管道/节点）"))
            return None, None

        selected = list(layer.selectedFeatures())
        if not selected:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "请至少选中 1 个要素"))
            return None, None

        # 多选时校验同类型
        if mode == "aqd_pipes" and len(selected) > 1:
            ptypes = {str(f.attribute("pipe_type") or "") for f in selected}
            if len(ptypes) > 1:
                self.iface.messageBar().pushWarning(
                    "aQuaDrip",
                    QApplication.translate("AquadripPlugin", "选中的要素包含多种管道类型（{0}），请仅选择同一类型").format(', '.join(ptypes)))
                return None, None
        elif mode == "aqd_nodes" and len(selected) > 1:
            ntypes = {str(f.attribute("node_type") or "junction") for f in selected}
            if len(ntypes) > 1:
                self.iface.messageBar().pushWarning(
                    "aQuaDrip",
                    QApplication.translate("AquadripPlugin", "选中的要素包含多种节点类型（{0}），请仅选择同一类型").format(', '.join(ntypes)))
                return None, None

        return selected, layer

    def _get_single_selected(self, required_layer_key):
        """获取当前唯一选中要素

        Args:
            required_layer_key: 指定图层名（如 "aqd_fields"/"aqd_pipes"/
                "aqd_pumps"/"aqd_valves"/"aqd_nodes"），
                None 表示接受任意 aQuaDrip 图层

        Returns:
            (feat, layer) 或 (None, None)（已弹提示）
        """
        layer = self.iface.activeLayer()
        if layer is None or not hasattr(layer, "selectedFeatures"):
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "请先在图层面板选中相应图层和要素"))
            return None, None

        if required_layer_key:
            src = layer.source() or ""
            if layer.name() != required_layer_key and required_layer_key not in src:
                self.iface.messageBar().pushWarning(
                    "aQuaDrip", QApplication.translate("AquadripPlugin", "当前活动图层不是 {0}").format(required_layer_key))
                return None, None
        else:
            from .ui.property_dialog import PropertyDialog
            if PropertyDialog._mode_of_layer(layer) is None:
                self.iface.messageBar().pushWarning(
                    "aQuaDrip", QApplication.translate("AquadripPlugin", "当前图层不是 aQuaDrip 图层（地块/管道/节点）"))
                return None, None

        selected = list(layer.selectedFeatures())
        if len(selected) != 1:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "请恰好选中 1 个要素"))
            return None, None
        return selected[0], layer

    def on_run_simulation(self):
        """运行水力模拟：同步构建管网 → 精度选择 → 后台线程模拟 + 进度条"""
        try:
            from .tools.sync_manager import SyncManager

            # 1. 同步构建 DripNetwork（必须主线程，涉及 QGIS 图层读写）
            sync = SyncManager(self.iface)
            net = sync.sync_qgis_to_network()

            # 预检
            sources = [n for n in net.nodes.values()
                       if hasattr(n, "source_type")]
            if not sources:
                QMessageBox.warning(
                    self.iface.mainWindow(), "aQuaDrip",
                    QApplication.translate("AquadripPlugin", "管网中没有水源节点。\n\n"
                    "请先用「添加水源」在地图上放置水源。"))
                return
            if not net.links:
                QMessageBox.warning(
                    self.iface.mainWindow(), "aQuaDrip",
                    QApplication.translate("AquadripPlugin", "管网中没有管道。"))
                return

            errors = net.validate()
            if errors and self.dockwidget:
                for e in errors[:5]:
                    self.dockwidget.log_message(QApplication.translate("AquadripPlugin", "⚠️ 校验: {0}").format(e))

            # 2. 弹出精度选择对话框
            from .ui.simulation_dialog import SimulationDialog
            dlg = SimulationDialog(self.iface)
            if dlg.exec() != dlg.Accepted:
                return
            precision = dlg.precision_level()
            save_history = dlg.save_history()

            # 3. 启动后台 Worker + QThread
            from .tools.simulation_worker import SimulationWorker
            from qgis.PyQt.QtCore import QThread
            from qgis.PyQt.QtWidgets import QProgressBar

            self._sim_net = net
            self._sim_sync = sync
            self._sim_save_history = save_history

            worker = SimulationWorker(net, precision)
            thread = QThread()
            self._sim_worker = worker
            worker.moveToThread(thread)

            # 进度条放在消息栏
            bar = QProgressBar()
            bar.setValue(0)
            bar_msg = self.iface.messageBar().createMessage(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "正在模拟..."))
            bar_msg.layout().addWidget(bar)
            self.iface.messageBar().pushWidget(bar_msg, level=0)

            # 信号连接
            worker.progress_changed.connect(
                lambda pct, msg: (bar.setValue(pct), bar.setFormat(msg)))
            worker.finished.connect(
                lambda result: self._on_sim_finished(net, sync, result, bar_msg, save_history))
            worker.error_occurred.connect(
                lambda err: self._on_sim_error(err, bar_msg))
            thread.started.connect(worker.run)

            # 清理（finished 时自动 deleteLater，由 _track_thread 管理）
            worker.finished.connect(thread.quit)
            worker.error_occurred.connect(thread.quit)
            self._track_thread(thread, worker)

            thread.start()

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "模拟启动失败: {0}").format(e))

    def _on_sim_finished(self, net, sync, result, bar_msg, save_history):
        """模拟完成回调（主线程，安全访问 QGIS 图层）"""
        self.iface.messageBar().clearWidgets()

        if not result.success:
            QMessageBox.critical(
                self.iface.mainWindow(), "aQuaDrip",
                QApplication.translate("AquadripPlugin", "模拟失败：\n{0}").format(result.message))
            return

        # 结果回写图层
        sync.sync_from_network(net, result)

        # CU/DU 统计
        from wdrip.analysis import UniformityAnalyzer
        flows = [float(arr[0]) for arr in result.emitter_flow.values()
                 if len(arr) > 0]
        cu = UniformityAnalyzer.cu(flows) if flows else 0.0
        du = UniformityAnalyzer.du(flows) if flows else 0.0

        # 保存历史（必须在观测点回填之前，因为需要 node_coords）
        if save_history:
            self._save_sim_history(net, result, cu, du)

        # 回填观测点模拟值到校准 tab（从刚保存的 simhistory 读取坐标）
        if self.dockwidget:
            self.dockwidget.refresh_obs_points(result)

        stats = [
            f"✅ {result.message}",
            QApplication.translate("AquadripPlugin", "节点 {0} / 管道 {1} / 滴头 {2}").format(len(net.nodes), len(net.links), len(flows)),
        ]
        if flows:
            stats.append(
                QApplication.translate("AquadripPlugin", "滴头流量 {0:.2f}~{1:.2f} L/h").format(min(flows), max(flows)))
            stats.append(f"CU = {cu:.1f}%   DU = {du:.1f}%")
        stats.append(QApplication.translate("AquadripPlugin", "结果已保存，可点击「可视化」工具查看"))

        if self.dockwidget:
            for line in stats:
                self.dockwidget.log_message(line)
        QMessageBox.information(
            self.iface.mainWindow(), QApplication.translate("AquadripPlugin", "aQuaDrip 模拟完成"),
            "\n".join(stats))

    def _on_sim_error(self, err, bar_msg):
        """模拟错误回调（主线程）"""
        self.iface.messageBar().clearWidgets()
        import traceback
        traceback.print_exc()
        if self.dockwidget:
            self.dockwidget.log_message(QApplication.translate("AquadripPlugin", "❌ 模拟运行失败: {0}").format(err))
        self.iface.messageBar().pushWarning("aQuaDrip", QApplication.translate("AquadripPlugin", "模拟失败: {0}").format(err))

    def _save_sim_history(self, net, result, cu: float, du: float):
        """将模拟结果保存到 sidecar 历史文件"""
        try:
            from .tools.sim_history import SimHistory
            from .tools.layer_utils import find_gpkg_path

            # 从项目找 GPKG 路径（优先用 aqd_fields，更稳定）
            gpkg_path = find_gpkg_path(None, "aqd_fields")

            if not gpkg_path:
                return  # 找不到 GPKG，静默跳过

            history = SimHistory(gpkg_path)

            # 提取结果数据（取稳态值 arr[0]）
            node_pressure = {nid: float(arr[0])
                             for nid, arr in result.node_pressure.items()
                             if len(arr) > 0}
            link_flow = {lid: float(arr[0])
                         for lid, arr in result.link_flow.items()
                         if len(arr) > 0}
            link_velocity = {lid: float(arr[0])
                             for lid, arr in result.link_velocity.items()
                             if len(arr) > 0}
            emitter_flow = {eid: float(arr[0])
                            for eid, arr in result.emitter_flow.items()
                            if len(arr) > 0}
            node_coords = {nid: [node.x, node.y]
                           for nid, node in net.nodes.items()}
            # 管道端点节点引用：可视化时按 from_node/to_node 从
            # node_coords 重建分段管道几何（拓扑切断产生的 L{fid}_p{n}
            # 不在 aqd_pipes 原始图层中，否则会被跳过不显示）
            link_endpoints = {lid: [link.from_node, link.to_node]
                              for lid, link in net.links.items()}
            # 管道折线顶点（含转弯）：可视化时按 lid 取折线画线，
            # 避免被交叉切断的分段只画端点直线而丢失转弯形状
            link_geometry = getattr(net, "link_geometry", None) or {}

            history.add(
                cu=cu, du=du,
                node_pressure=node_pressure,
                link_flow=link_flow,
                link_velocity=link_velocity,
                emitter_flow=emitter_flow,
                node_coords=node_coords,
                message=result.message,
                link_endpoints=link_endpoints,
                link_geometry=link_geometry,
            )
        except Exception as e:
            # 历史保存失败不影响模拟结果
            import traceback
            traceback.print_exc()
            if self.dockwidget:
                self.dockwidget.log_message(QApplication.translate("AquadripPlugin", "⚠️ 模拟历史保存失败: {0}").format(e))

    def on_visualize(self):
        """打开可视化对话框，选择历史记录进行可视化"""
        from .ui.visualize_dialog import VisualizeDialog
        from .tools.visualize import Visualizer

        self._viz_dlg = VisualizeDialog(self.iface,
                                         parent=self.iface.mainWindow())
        visualizer = Visualizer(self.iface)

        def on_request(record, mode):
            visualizer.show_results(record, mode)

        self._viz_dlg.visualize_requested.connect(on_request)
        self._viz_dlg.finished.connect(
            lambda: setattr(self, "_viz_dlg", None))
        self._viz_dlg.show()

    def on_zone_divide(self):
        """根据阀门自动划分管网分区"""
        try:
            from .tools.zone_divider import ZoneDivider
            ZoneDivider(self.iface).divide()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "分区划分失败: {0}").format(e))

    def on_pipe_pressure_check(self):
        """检查管道承压：对比模拟压力与最大承压"""
        try:
            from .tools.pipe_pressure_check import PipePressureChecker
            PipePressureChecker(self.iface).check()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "承压分析失败: {0}").format(e))

    # ── 轮灌管理 ──

    def on_rotation(self):
        """打开轮灌配置对话框

        如果用户已在地图上手动选中田块，自动预选该田块。
        """
        from .tools.rotation_scheduler import RotationScheduler
        from .ui.rotation_dialog import RotationDialog

        scheduler = RotationScheduler(self.iface)
        fields = scheduler.get_field_features()
        if not fields:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "未找到农田地块 (aqd_fields) 图层"))
            return

        selected_id = -1
        field_layer = scheduler._field_layer
        if field_layer and field_layer.selectedFeatureCount() > 0:
            selected_id = field_layer.selectedFeatures()[0].id()

        dlg = RotationDialog(self.iface)
        dlg.set_field_data(fields, selected_id)
        dlg.rotation_requested.connect(lambda cfg: self._on_rot_run(dlg, cfg))
        dlg.finished.connect(lambda: setattr(self, '_rot_dlg', None))
        self._rot_dlg = dlg
        dlg.show()

    def _on_rot_run(self, dlg, config):
        """异步运行轮灌模拟"""
        if self.dockwidget:
            self.dockwidget.clear_rotation()

        from .tools.rotation_scheduler import RotationScheduler, RotationWorker
        from qgis.PyQt.QtCore import QThread

        scheduler = RotationScheduler(self.iface)
        field_feat = scheduler.get_field_features()
        field_idx = config.get("field_idx", 0)
        if 0 <= field_idx < len(field_feat):
            scheduler.collect_field_data(field_feat[field_idx])

        zones = config.get("zones", [])
        if not zones:
            self.iface.messageBar().pushWarning("aQuaDrip", QApplication.translate("AquadripPlugin", "未配置有效的轮灌分区"))
            dlg._on_stop()
            return

        # QGIS 图层只允许主线程访问/编辑（sync_qgis_to_network 会回写
        # from_node/to_node）：先在主线程预取网络、zone 映射与田块面积，
        # 后台线程仅做纯内存模拟
        try:
            snapshot = scheduler.prepare_snapshot()
        except Exception as e:
            import traceback
            dlg.on_progress(0, QApplication.translate("AquadripPlugin", "错误: {0}\n{1}").format(e, traceback.format_exc()))
            dlg._on_stop()
            return
        if not snapshot["full_net"].links:
            self.iface.messageBar().pushWarning("aQuaDrip", QApplication.translate("AquadripPlugin", "管网为空，无法轮灌模拟"))
            dlg._on_stop()
            return

        worker = RotationWorker(scheduler, zones, **snapshot)
        thread = QThread()
        worker.moveToThread(thread)

        worker.progress_changed.connect(lambda p, m: dlg.on_progress(p, m))
        worker.finished.connect(lambda results: (
            dlg.on_done(results),
            self._show_rot_results(results, scheduler)
        ))
        worker.error_occurred.connect(
            lambda e: (dlg.on_progress(0, QApplication.translate("AquadripPlugin", "错误: {0}").format(e)), dlg._on_stop()))
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.error_occurred.connect(thread.quit)

        self._track_thread(thread, worker)
        thread.start()

    def _show_rot_results(self, results: list, scheduler):
        """直接在 dockwidget 展示轮灌结果，并写盘后台收集的历史记录"""
        if results:
            # 历史记录由 worker 在内存中收集，统一回到主线程写
            # .simhistory（避免并发"读-改-写"损坏 JSON）
            try:
                scheduler.flush_pending_history()
            except Exception:
                import traceback
                traceback.print_exc()
        if self.dockwidget and results:
            self.dockwidget.show_rotation_results(results, scheduler.rotation_id)

    def _on_rot_visualize(self):
        """可视化轮灌结果 → 打开可视化对话框"""
        self.on_visualize()

    def _run_silent_simulation(self):
        """异步静默运行模拟（校准用，不弹对话框）"""
        from .tools.sync_manager import SyncManager
        from .tools.simulation_worker import SimulationWorker
        from qgis.PyQt.QtCore import QThread
        from qgis.PyQt.QtWidgets import QProgressBar

        # 同步构建网络（必须主线程）
        sync = SyncManager(self.iface)
        net = sync.sync_qgis_to_network()
        sources = [n for n in net.nodes.values() if hasattr(n, "source_type")]
        if not sources or not net.links:
            return

        # 后台线程运行 WNTR
        worker = SimulationWorker(net, precision="fast")
        thread = QThread()
        self._sim_worker = worker
        worker.moveToThread(thread)

        bar = QProgressBar()
        bar.setValue(0)
        bar_msg = self.iface.messageBar().createMessage("aQuaDrip", QApplication.translate("AquadripPlugin", "正在重新模拟..."))
        bar_msg.layout().addWidget(bar)
        self.iface.messageBar().pushWidget(bar_msg, level=0)

        worker.progress_changed.connect(lambda p, m: bar.setValue(p))
        worker.finished.connect(lambda r: self._on_silent_sim_done(sync, net, r, bar_msg))
        worker.error_occurred.connect(lambda e: self._on_silent_sim_error(e, bar_msg))
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.error_occurred.connect(thread.quit)
        self._track_thread(thread, worker)
        thread.start()

    def _on_silent_sim_done(self, sync, net, result, bar_msg):
        """静默模拟完成回调"""
        self.iface.messageBar().clearWidgets()
        if not result.success:
            if self.dockwidget:
                self.dockwidget.log_message(QApplication.translate("AquadripPlugin", "⚠️ 模拟失败: {0}").format(result.message))
            return
        sync.sync_from_network(net, result)
        from wdrip.analysis import UniformityAnalyzer
        flows = [float(arr[0]) for arr in result.emitter_flow.values() if len(arr) > 0]
        cu = UniformityAnalyzer.cu(flows) if flows else 0.0
        du = UniformityAnalyzer.du(flows) if flows else 0.0
        self._save_sim_history(net, result, cu, du)
        if self.dockwidget:
            self.dockwidget.refresh_obs_points(result)
            self.dockwidget.log_message(QApplication.translate("AquadripPlugin", "✅ 模拟完成，观测值已更新"))

    def _on_silent_sim_error(self, err, bar_msg):
        """静默模拟错误回调"""
        self.iface.messageBar().clearWidgets()
        if self.dockwidget:
            self.dockwidget.log_message(QApplication.translate("AquadripPlugin", "❌ 校准模拟失败: {0}").format(err))

    def _on_calib_refresh(self):
        """校准 tab: 刷新模拟值 → 读取最新模拟历史（不重新模拟）"""
        from .tools.layer_utils import find_gpkg_path
        gpkg_path = find_gpkg_path(None, "aqd_fields")
        if not gpkg_path:
            self.iface.messageBar().pushWarning("aQuaDrip", QApplication.translate("AquadripPlugin", "未找到项目 GPKG"))
            return

        from .tools.sim_history import SimHistory
        records = SimHistory(gpkg_path).load()
        if not records:
            # 无历史记录 → 回退到运行模拟
            self.on_run_simulation()
            return

        record = records[0]

        # 轻量适配器：node_pressure 值包装为数组，
        # 兼容 dockwidget._find_nearest_pressure 的 p_arr[0] 访问
        class _SimAdapter:
            pass
        adapter = _SimAdapter()
        adapter.node_pressure = {
            nid: [float(v)] for nid, v in record.get("node_pressure", {}).items()
            if isinstance(v, (int, float))}

        if self.dockwidget:
            self.dockwidget.refresh_obs_points(adapter)
            ts = record.get("timestamp", "?")
            self.dockwidget.log_message(QApplication.translate("AquadripPlugin", "✅ 已加载最新模拟结果 ({0})，未重新模拟").format(ts))

    def _on_calib_run(self):
        """校准 tab: 弹出参数对话框 + 迭代校准"""
        if not self.dockwidget:
            return
        measured = self.dockwidget.get_measured_values()
        if not measured:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", QApplication.translate("AquadripPlugin", "请先在「校准」tab 中输入实测压力值"))
            return

        # 从 simhistory 读取最新模拟值 + 观测点坐标
        from .tools.layer_utils import find_gpkg_path
        gpkg_path = find_gpkg_path(None, "aqd_fields")
        if not gpkg_path:
            self.iface.messageBar().pushWarning("aQuaDrip", QApplication.translate("AquadripPlugin", "未找到项目 GPKG"))
            return

        from .tools.sim_history import SimHistory
        history = SimHistory(gpkg_path)
        records = history.load()
        if not records:
            self.iface.messageBar().pushWarning("aQuaDrip", QApplication.translate("AquadripPlugin", "请先运行模拟"))
            return
        latest = records[0]
        node_pressure = latest.get("node_pressure", {})
        node_coords = latest.get("node_coords", {})
        lg = latest.get("link_geometry", {})
        lf = latest.get("link_flow", {})
        ef = latest.get("emitter_flow", {})

        # 类型感知匹配(emitter→滴头出流,其他→管段流量)+ 匹配半径
        from .tools.calib_algorithm import nearest_sim_pressure, nearest_sim_flow

        # 构建 obs_data
        obs_data = {}
        obs_layer = self._find_obs_layer()
        if obs_layer is None:
            return
        # CRS 真值:避免启发式把局部米制坐标系误判为经纬度
        try:
            is_geo = obs_layer.crs().isGeographic()
        except Exception:
            is_geo = None
        for feat in obs_layer.getFeatures():
            name = str(feat.attribute("name") or f"obs_{feat.id()}")
            p_obs, q_obs = measured.get(name, (None, None))
            if p_obs is None and q_obs is None:
                continue
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            pt = geom.asPoint()
            ox, oy = pt.x(), pt.y()
            otype = str(feat.attribute("type") or "junction")
            sim_p, _dp = nearest_sim_pressure(
                ox, oy, node_pressure, node_coords, is_geo)
            sim_q, _dq = nearest_sim_flow(
                ox, oy, otype, lg, lf, ef, node_coords, is_geo)
            obs_data[name] = (ox, oy, sim_p, p_obs, sim_q, q_obs)

        # 弹出校准对话框
        from .ui.calibration_dialog import CalibrationDialog
        dlg = CalibrationDialog(obs_data, self.iface)
        self._calib_dlg = dlg
        dlg.sim_requested.connect(self._on_calib_sim_requested)
        # 「应用校准结果」→ 用校准后 C 值完整重新模拟(精度选择/进度/结果回写)
        dlg.apply_requested.connect(self.on_run_simulation)
        dlg.finished.connect(lambda: setattr(self, '_calib_dlg', None))
        dlg.show()

    def _on_calib_sim_requested(self, obs_data):
        """校准对话框请求异步模拟"""
        dlg = getattr(self, '_calib_dlg', None)
        if dlg is None: return
        from .tools.sync_manager import SyncManager
        from qgis.PyQt.QtCore import QThread
        from qgis.PyQt.QtWidgets import QProgressBar
        from .tools.simulation_worker import SimulationWorker

        sync = SyncManager(self.iface)
        net = sync.sync_qgis_to_network()
        sources = [n for n in net.nodes.values() if hasattr(n, "source_type")]
        if not sources or not net.links:
            dlg.on_sim_done(obs_data); return

        worker = SimulationWorker(net, precision="fast")
        thread = QThread()
        self._calib_worker = worker
        worker.moveToThread(thread)
        bar = QProgressBar(); bar.setValue(0)
        bar_msg = self.iface.messageBar().createMessage("aQuaDrip", QApplication.translate("AquadripPlugin", "校准模拟中..."))
        bar_msg.layout().addWidget(bar)
        self.iface.messageBar().pushWidget(bar_msg, level=0)
        worker.progress_changed.connect(lambda p, m: bar.setValue(p))
        worker.finished.connect(lambda r: self._calib_sim_done(sync, net, r, bar_msg, obs_data))
        worker.error_occurred.connect(lambda e: self.iface.messageBar().clearWidgets())
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.error_occurred.connect(thread.quit)
        self._track_thread(thread, worker)
        thread.start()

    def _calib_sim_done(self, sync, net, result, bar_msg, obs_data):
        self.iface.messageBar().clearWidgets()
        if result.success:
            sync.sync_from_network(net, result)
            flows = [float(arr[0]) for arr in result.emitter_flow.values() if len(arr) > 0]
            from wdrip.analysis import UniformityAnalyzer
            cu = UniformityAnalyzer.cu(flows) if flows else 0.0
            du = UniformityAnalyzer.du(flows) if flows else 0.0
            self._save_sim_history(net, result, cu, du)
            if self.dockwidget:
                self.dockwidget.refresh_obs_points(result)
        else:
            # 模拟失败:保留旧模拟值继续迭代,但必须让用户知道
            self.iface.messageBar().pushWarning(
                "aQuaDrip",
                QApplication.translate(
                    "AquadripPlugin",
                    "校准重模拟失败: {0}").format(
                        getattr(result, "message", "")),
                )
        dlg = getattr(self, '_calib_dlg', None)
        if dlg:
            dlg.on_sim_done(self._update_obs_from_sim(obs_data))

    def _update_obs_from_sim(self, obs_data):
        from .tools.layer_utils import find_gpkg_path
        gpkg_path = find_gpkg_path(None, "aqd_fields")
        if not gpkg_path: return obs_data
        from .tools.sim_history import SimHistory
        recs = SimHistory(gpkg_path).load()
        if not recs: return obs_data
        r = recs[0]
        npd, ncd = r.get("node_pressure", {}), r.get("node_coords", {})
        lfd, lgd = r.get("link_flow", {}), r.get("link_geometry", {})
        efd = r.get("emitter_flow", {})

        # 观测点类型(obs_data 的 key 是纯名称,需回图层查 type;
        # emitter 型的模拟流量匹配滴头出流,其他匹配管段流量)
        otype_map = {}
        obs_layer = self._find_obs_layer()
        if obs_layer is not None:
            for f in obs_layer.getFeatures():
                otype_map[str(f.attribute("name") or f"obs_{f.id()}")] = \
                    str(f.attribute("type") or "junction")

        from .tools.calib_algorithm import nearest_sim_pressure, nearest_sim_flow
        try:
            is_geo = obs_layer.crs().isGeographic() if obs_layer is not None else None
        except Exception:
            is_geo = None
        new = {}
        for lb, (ox, oy, _, po, _, qo) in obs_data.items():
            otype = otype_map.get(lb, "junction")
            sp, _dp = nearest_sim_pressure(ox, oy, npd, ncd, is_geo)
            sq, _dq = nearest_sim_flow(ox, oy, otype, lgd, lfd, efd, ncd, is_geo)
            new[lb] = (ox, oy, sp, po, sq, qo)
        return new

    def _find_obs_layer(self):
        from qgis.core import QgsProject
        from .tools.layer_utils import find_layer
        return find_layer(QgsProject.instance(), "aqd_obs_points")

    def on_open_project(self):
        """打开已有的 aQuaDrip GPKG 项目"""
        from .tools.project_io import load_layers
        load_layers(self.iface)

    def on_export_inp(self):
        """导出为 EPANET INP 文件"""
        from .tools.project_io import export_inp
        export_inp(self.iface)
