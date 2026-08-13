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

        # 校准 tab 按钮连接
        self.dockwidget._btn_refresh.clicked.connect(self._on_calib_refresh)
        self.dockwidget._btn_calibrate.clicked.connect(self._on_calib_run)
        # 轮灌 tab 按钮连接
        self.dockwidget._btn_rot_visualize.clicked.connect(self._on_rot_visualize)

        # 自定义图标路径
        from qgis.PyQt.QtGui import QIcon
        _icons = os.path.join(os.path.dirname(__file__), "icons")
        _icon = lambda name: QIcon(os.path.join(_icons, name))

        # 功能列表：(图标文件, 名称, handler, tooltip)
        entries = [
            ("generate_layers.svg", "生成图层", self.on_setup_layers,
             "创建 aQuaDrip 标准 GeoPackage 图层"),
            ("open_project.svg", "打开项目", self.on_open_project,
             "打开已有的 aQuaDrip GeoPackage 项目"),
            ("generate_laterals.svg", "毛管生成", self.on_generate_lateral,
             "选中农田地块后，设置农艺参数并生成毛管"),
            ("trim_pipe.svg", "切割管道", self.on_trim_lateral,
             "点击管道在任意位置将其分割为两段"),
            ("crossing_nodes.svg", "生成交叉节点", self.on_generate_crossing_nodes,
             "选中一条管道后，为其与所有不同类型管道的交叉点生成连接节点"),
            ("edit_properties.svg", "编辑属性", self.on_edit_property,
             "选中地块/管道/节点后，修改其内部参数"),
            ("run_simulation.svg", "运行模拟", self.on_run_simulation,
             "同步图层→构建管网→WNTR 水力模拟→结果回写"),
            ("visualize.svg", "可视化", self.on_visualize,
             "查看历史模拟记录，生成结果可视化图层"),
            ("zone_divide.svg", "分区划分", self.on_zone_divide,
             "根据阀门位置自动划分管网分区"),
            ("rotation.svg", "轮灌管理", self.on_rotation,
             "配置轮灌调度方案并逐轮次运行水力模拟"),
            ("pipe_pressure.svg", "管道承压", self.on_pipe_pressure_check,
             "根据模拟结果检测管道超压泄漏风险"),
            ("inp_tools.svg", "INP 处理", None,
             "导出当前管网为 EPANET INP 文件，或从 INP 文件导入为临时图层"),
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

        # "INP 处理"按钮设为下拉菜单（导出 / 导入）
        from qgis.PyQt.QtWidgets import QMenu, QToolButton
        inp_action = self.actions[-1]
        inp_menu = QMenu(self.iface.mainWindow())
        export_act = inp_menu.addAction("导出 INP...")
        import_act = inp_menu.addAction("导入 INP...")
        export_act.triggered.connect(self.on_export_inp)
        import_act.triggered.connect(self.on_import_inp)
        inp_action.setMenu(inp_menu)
        # 设置工具栏按钮为 InstantPopup（点击直接弹出菜单）
        btn = toolbar.widgetForAction(inp_action)
        if btn is not None:
            btn.setPopupMode(QToolButton.InstantPopup)

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
            "aQuaDrip", "正在创建图层...", level=0, duration=3)

        try:
            from .tools.layer_setup import LayerSetupAction

            setup = LayerSetupAction(self.iface)
            success = setup.setup_layers(gpkg_path, target_crs=target_crs)

            if not success:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "aQuaDrip",
                    "图层创建失败，请查看 Python 日志")
                return

            used_crs = setup._project_crs
            if self.dockwidget:
                self.dockwidget.log_message(
                    f"图层已创建: {gpkg_path} (CRS: {used_crs.authid()})")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.iface.messageBar().pushWarning(
                "aQuaDrip", f"创建失败: {e}")
            return

        # 2. 导入正射影像（可选）
        ortho_layer = self._add_raster_to_group(
            ortho_path, "正射影像") if ortho_path else None

        # 3. 导入 DEM（可选）
        dem_layer = self._add_raster_to_group(
            dem_path, "DEM 高程") if dem_path else None

        # 4. 保存 QGZ 项目文件
        try:
            from qgis.core import QgsProject
            # 设置项目 CRS 与图层一致（避免"无坐标系"提示）
            if target_crs is not None and target_crs.isValid():
                QgsProject.instance().setCrs(target_crs)
            QgsProject.instance().write(qgz_path)
            if self.dockwidget:
                self.dockwidget.log_message(f"项目已保存: {qgz_path}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.iface.messageBar().pushWarning(
                "aQuaDrip", f"保存 QGZ 失败: {e}")
            # 不阻断：GPKG 已创建，用户可手动保存

        # 5. 成功提示
        parts = [f"📁 GPKG: {gpkg_path}", f"📁 QGZ:  {qgz_path}"]
        if target_crs is not None:
            parts.append(f"🌐 CRS:  {target_crs.authid()}")
        loaded = ["农田地块 (aqd_fields)", "管道 (aqd_pipes)",
                  "节点 (aqd_nodes)", "观测点 (aqd_obs_points)"]
        if ortho_layer:
            loaded.append("正射影像")
        if dem_layer:
            loaded.append("DEM 高程")

        QMessageBox.information(
            self.iface.mainWindow(),
            "aQuaDrip",
            f"项目创建完成\n\n"
            f"{os.linesep.join(parts)}\n\n"
            f"已加载图层:\n"
            + "\n".join(f"  • {s}" for s in loaded) + "\n\n"
            f"下次可直接用 QGIS 打开 .qgz 文件，\n"
            f"或通过「打开项目」加载 .gpkg。")

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
                "aQuaDrip", f"无法加载栅格图层: {layer_name}")
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
                "aQuaDrip", "请先在图层面板选中 aqd_pipes 图层")
            return

        source = layer.source() if hasattr(layer, "source") else ""
        layer_name = layer.name() or ""
        is_link_layer = any(k in source or layer_name == k
                           for k in ("aqd_pipes", "aqd_pumps", "aqd_valves"))
        if not is_link_layer:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "当前活动图层不是 aqd_pipes / aqd_pumps / aqd_valves")
            return

        selected = layer.selectedFeatures()
        selected = list(selected)
        if len(selected) != 1:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "请恰好选中 1 条管道")
            return

        feat = selected[0]
        ptype = str(feat.attribute("pipe_type") or "")
        if not ptype:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "选中要素的 pipe_type 为空，请先设置管道类型")
            return

        try:
            from .tools.crossing_node_tool import CrossingNodeGenerator
            CrossingNodeGenerator(self.iface).generate(feat)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.iface.messageBar().pushWarning(
                "aQuaDrip", f"生成连接节点失败: {e}")

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
                "aQuaDrip", "请先在图层面板选中相应图层和要素")
            return None, None

        from .ui.property_dialog import PropertyDialog
        mode = PropertyDialog._mode_of_layer(layer)
        if mode is None:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "当前图层不是 aQuaDrip 图层（地块/管道/节点）")
            return None, None

        selected = list(layer.selectedFeatures())
        if not selected:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "请至少选中 1 个要素")
            return None, None

        # 多选时校验同类型
        if mode == "aqd_pipes" and len(selected) > 1:
            ptypes = {str(f.attribute("pipe_type") or "") for f in selected}
            if len(ptypes) > 1:
                self.iface.messageBar().pushWarning(
                    "aQuaDrip",
                    f"选中的要素包含多种管道类型（{', '.join(ptypes)}），"
                    f"请仅选择同一类型")
                return None, None
        elif mode == "aqd_nodes" and len(selected) > 1:
            ntypes = {str(f.attribute("node_type") or "junction") for f in selected}
            if len(ntypes) > 1:
                self.iface.messageBar().pushWarning(
                    "aQuaDrip",
                    f"选中的要素包含多种节点类型（{', '.join(ntypes)}），"
                    f"请仅选择同一类型")
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
                    "管网中没有水源节点。\n\n"
                    "请先用「添加水源」在地图上放置水源。")
                return
            if not net.links:
                QMessageBox.warning(
                    self.iface.mainWindow(), "aQuaDrip",
                    "管网中没有管道。")
                return

            errors = net.validate()
            if errors and self.dockwidget:
                for e in errors[:5]:
                    self.dockwidget.log_message(f"⚠️ 校验: {e}")

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
                "aQuaDrip", "正在模拟...")
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
                "aQuaDrip", f"模拟启动失败: {e}")

    def _on_sim_finished(self, net, sync, result, bar_msg, save_history):
        """模拟完成回调（主线程，安全访问 QGIS 图层）"""
        self.iface.messageBar().clearWidgets()

        if not result.success:
            QMessageBox.critical(
                self.iface.mainWindow(), "aQuaDrip",
                f"模拟失败：\n{result.message}")
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
            f"节点 {len(net.nodes)} / 管道 {len(net.links)} / 滴头 {len(flows)}",
        ]
        if flows:
            stats.append(
                f"滴头流量 {min(flows):.2f}~{max(flows):.2f} L/h")
            stats.append(f"CU = {cu:.1f}%   DU = {du:.1f}%")
        stats.append("结果已保存，可点击「可视化」工具查看")

        if self.dockwidget:
            for line in stats:
                self.dockwidget.log_message(line)
        QMessageBox.information(
            self.iface.mainWindow(), "aQuaDrip 模拟完成",
            "\n".join(stats))

    def _on_sim_error(self, err, bar_msg):
        """模拟错误回调（主线程）"""
        self.iface.messageBar().clearWidgets()
        import traceback
        traceback.print_exc()
        if self.dockwidget:
            self.dockwidget.log_message(f"❌ 模拟运行失败: {err}")
        self.iface.messageBar().pushWarning("aQuaDrip", f"模拟失败: {err}")

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
                self.dockwidget.log_message(f"⚠️ 模拟历史保存失败: {e}")

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
                "aQuaDrip", f"分区划分失败: {e}")

    def on_pipe_pressure_check(self):
        """检查管道承压：对比模拟压力与最大承压"""
        try:
            from .tools.pipe_pressure_check import PipePressureChecker
            PipePressureChecker(self.iface).check()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.iface.messageBar().pushWarning(
                "aQuaDrip", f"承压分析失败: {e}")

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
                "aQuaDrip", "未找到农田地块 (aqd_fields) 图层")
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
            self.iface.messageBar().pushWarning("aQuaDrip", "未配置有效的轮灌分区")
            dlg._on_stop()
            return

        worker = RotationWorker(scheduler, zones)
        thread = QThread()
        worker.moveToThread(thread)

        worker.progress_changed.connect(lambda p, m: dlg.on_progress(p, m))
        worker.finished.connect(lambda results: (
            dlg.on_done(results),
            self._show_rot_results(results, scheduler)
        ))
        worker.error_occurred.connect(
            lambda e: (dlg.on_progress(0, f"错误: {e}"), dlg._on_stop()))
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.error_occurred.connect(thread.quit)

        self._track_thread(thread, worker)
        thread.start()

    def _show_rot_results(self, results: list, scheduler):
        """直接在 dockwidget 展示轮灌结果"""
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
        bar_msg = self.iface.messageBar().createMessage("aQuaDrip", "正在重新模拟...")
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
                self.dockwidget.log_message(f"⚠️ 模拟失败: {result.message}")
            return
        sync.sync_from_network(net, result)
        from wdrip.analysis import UniformityAnalyzer
        flows = [float(arr[0]) for arr in result.emitter_flow.values() if len(arr) > 0]
        cu = UniformityAnalyzer.cu(flows) if flows else 0.0
        du = UniformityAnalyzer.du(flows) if flows else 0.0
        self._save_sim_history(net, result, cu, du)
        if self.dockwidget:
            self.dockwidget.refresh_obs_points(result)
            self.dockwidget.log_message("✅ 模拟完成，观测值已更新")

    def _on_silent_sim_error(self, err, bar_msg):
        """静默模拟错误回调"""
        self.iface.messageBar().clearWidgets()
        if self.dockwidget:
            self.dockwidget.log_message(f"❌ 校准模拟失败: {err}")

    def _on_calib_refresh(self):
        """校准 tab: 刷新模拟值 → 运行一次完整模拟"""
        self.on_run_simulation()

    def _on_calib_run(self):
        """校准 tab: 弹出参数对话框 + 迭代校准"""
        if not self.dockwidget:
            return
        measured = self.dockwidget.get_measured_values()
        if not measured:
            self.iface.messageBar().pushWarning(
                "aQuaDrip", "请先在「校准」tab 中输入实测压力值")
            return

        # 从 simhistory 读取最新模拟值 + 观测点坐标
        from .tools.layer_utils import find_gpkg_path
        gpkg_path = find_gpkg_path(None, "aqd_fields")
        if not gpkg_path:
            self.iface.messageBar().pushWarning("aQuaDrip", "未找到项目 GPKG")
            return

        from .tools.sim_history import SimHistory
        history = SimHistory(gpkg_path)
        records = history.load()
        if not records:
            self.iface.messageBar().pushWarning("aQuaDrip", "请先运行模拟")
            return
        latest = records[0]
        node_pressure = latest.get("node_pressure", {})
        node_coords = latest.get("node_coords", {})
        lg = latest.get("link_geometry", {})
        lf = latest.get("link_flow", {})

        # 构建 obs_data
        obs_data = {}
        obs_layer = self._find_obs_layer()
        if obs_layer is None:
            return
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
            # 找最近节点 → sim pressure
            best_d, sim_p = float('inf'), None
            for nid, p in node_pressure.items():
                c = node_coords.get(nid)
                if c is None or len(c) < 2: continue
                d = (ox-c[0])**2 + (oy-c[1])**2
                if d < best_d:
                    best_d = d
                    sim_p = float(p) if isinstance(p, (int, float)) else None
            # 找最近管段 → sim flow
            best_d, sim_q = float('inf'), None
            for lid, pts in lg.items():
                if not pts or len(pts) < 2: continue
                for i in range(len(pts)-1):
                    ax, ay = pts[i][0], pts[i][1]
                    bx, by = pts[i+1][0], pts[i+1][1]
                    dx, dy = bx-ax, by-ay
                    l2 = dx*dx+dy*dy
                    t = max(0, min(1, ((ox-ax)*dx+(oy-ay)*dy)/l2)) if l2>1e-20 else 0.5
                    px, py = ax+t*dx, ay+t*dy
                    d = ((ox-px)**2+(oy-py)**2)**0.5
                    if d < best_d:
                        best_d = d
                        f = lf.get(lid)
                        sim_q = abs(float(f)) if isinstance(f, (int, float)) else None
            obs_data[name] = (ox, oy, sim_p, p_obs, sim_q, q_obs)

        # 弹出校准对话框
        from .ui.calibration_dialog import CalibrationDialog
        dlg = CalibrationDialog(obs_data, self.iface)
        self._calib_dlg = dlg
        dlg.sim_requested.connect(self._on_calib_sim_requested)
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
        bar_msg = self.iface.messageBar().createMessage("aQuaDrip", "校准模拟中...")
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
        new = {}
        for lb, (ox, oy, _, po, _, qo) in obs_data.items():
            bd, sp = float('inf'), None
            for nid, p in npd.items():
                c = ncd.get(nid)
                if c is None or len(c) < 2: continue
                d = (ox-c[0])**2+(oy-c[1])**2
                if d < bd: bd = d; sp = float(p) if isinstance(p,(int,float)) else None
            bd, sq = float('inf'), None
            for lid, pts in lgd.items():
                if not pts or len(pts) < 2: continue
                for i in range(len(pts)-1):
                    ax,ay=pts[i][0],pts[i][1]; bx,by=pts[i+1][0],pts[i+1][1]
                    dx,dy=bx-ax,by-ay; l2=dx*dx+dy*dy
                    t=max(0,min(1,((ox-ax)*dx+(oy-ay)*dy)/l2)) if l2>1e-20 else 0.5
                    px,py=ax+t*dx,ay+t*dy; d=((ox-px)**2+(oy-py)**2)**0.5
                    if d<bd: bd=d; f=lfd.get(lid)
                    sq = abs(float(f)) if isinstance(f,(int,float)) else None
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

    def on_import_inp(self):
        """从 EPANET INP 文件导入为临时图层"""
        from .tools.project_io import import_inp
        import_inp(self.iface)
