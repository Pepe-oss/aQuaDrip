"""CalibrationDialog — 校准参数设置 + 迭代结果展示"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QSpinBox, QDoubleSpinBox, QTextEdit, QPushButton,
    QProgressBar, QLabel, QComboBox,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal

from ..tools.calib_algorithm import ALGORITHMS, CalibrationAlgorithm
from qgis.PyQt.QtWidgets import QApplication


class CalibrationDialog(QDialog):
    """校准参数对话框"""

    sim_requested = pyqtSignal(dict)
    apply_requested = pyqtSignal()  # 请求用校准后参数重新模拟(完整入口)

    def __init__(self, obs_data: dict, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self._obs_data = obs_data
        self._iteration = 0
        self._running = False
        self._prev_rmse = None

        self.setWindowTitle(QApplication.translate("CalibrationDialog", "aQuaDrip 校准"))
        self.setMinimumWidth(480)
        self.setMinimumHeight(440)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # ── 算法选择 ──
        algo_layout = QHBoxLayout()
        algo_layout.addWidget(QLabel(QApplication.translate("CalibrationDialog", "校准算法:")))
        self._combo_algo = QComboBox()
        for name, cls in ALGORITHMS.items():
            self._combo_algo.addItem(cls.label, name)
        algo_layout.addWidget(self._combo_algo)
        layout.addLayout(algo_layout)

        # ── 参数 ──
        form = QFormLayout()
        self._spin_iter = QSpinBox()
        self._spin_iter.setRange(1, 50)
        self._spin_iter.setValue(3)
        form.addRow(QApplication.translate("CalibrationDialog", "最大迭代次数:"), self._spin_iter)
        self._spin_lr = QDoubleSpinBox()
        self._spin_lr.setRange(0.05, 1.0)
        self._spin_lr.setSingleStep(0.05)
        self._spin_lr.setValue(0.30)
        form.addRow(QApplication.translate("CalibrationDialog", "学习率:"), self._spin_lr)
        layout.addLayout(form)

        # ── C 限值（按管道类型）──
        c_group = QGroupBox(QApplication.translate("CalibrationDialog", "C 限值 (Hazen-Williams)"))
        c_form = QFormLayout(c_group)
        self._c_spins = {}
        for key, label, dlo, dhi in [
            ("mainline", QApplication.translate("CalibrationDialog", "主/干管"), 100, 150),
            ("submain", QApplication.translate("CalibrationDialog", "支管"), 90, 140),
            ("lateral", QApplication.translate("CalibrationDialog", "毛管"), 80, 130),
        ]:
            row = QHBoxLayout()
            slo = QDoubleSpinBox()
            slo.setRange(50, 200); slo.setValue(dlo)
            row.addWidget(slo)
            row.addWidget(QLabel("~"))
            shi = QDoubleSpinBox()
            shi.setRange(50, 200); shi.setValue(dhi)
            row.addWidget(shi)
            c_form.addRow(f"{label}:", row)
            self._c_spins[key] = (slo, shi)
        layout.addWidget(c_group)

        # ── 结果区 ──
        layout.addWidget(QLabel(QApplication.translate("CalibrationDialog", "校准结果:")))
        self._result_text = QTextEdit()
        self._result_text.setReadOnly(True)
        self._result_text.setPlaceholderText(QApplication.translate("CalibrationDialog", "点击「开始校准」后显示迭代结果..."))
        layout.addWidget(self._result_text, stretch=1)

        # ── 进度 ──
        self._progress = QProgressBar()
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        # ── 按钮 ──
        btn = QHBoxLayout()
        self._btn_start = QPushButton(QApplication.translate("CalibrationDialog", "▶ 开始校准"))
        self._btn_start.setStyleSheet("font-weight: bold;")
        self._btn_start.clicked.connect(self._on_start)
        btn.addWidget(self._btn_start)
        self._btn_stop = QPushButton(QApplication.translate("CalibrationDialog", "⏹ 停止"))
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop)
        btn.addWidget(self._btn_stop)
        self._btn_apply = QPushButton(QApplication.translate("CalibrationDialog", "✅ 应用校准结果"))
        self._btn_apply.setEnabled(False)
        self._btn_apply.clicked.connect(self._on_apply)
        btn.addWidget(self._btn_apply)
        btn.addStretch()
        btn_close = QPushButton(QApplication.translate("CalibrationDialog", "关闭"))
        btn_close.clicked.connect(self.reject)
        btn.addWidget(btn_close)
        layout.addLayout(btn)

    def reject(self):
        """关闭对话框时停止运行中的校准"""
        self._running = False
        super().reject()

    # ── 获取算法参数 ──

    def _get_params(self) -> dict:
        return {
            "learning_rate": self._spin_lr.value(),
            "c_limits": {k: (slo.value(), shi.value())
                         for k, (slo, shi) in self._c_spins.items()},
        }

    def _get_algorithm(self) -> CalibrationAlgorithm:
        name = self._combo_algo.currentData()
        cls = ALGORITHMS.get(name)
        if cls is None:
            cls = list(ALGORITHMS.values())[0]
        return cls(self.iface, self._get_params())

    # ── 迭代控制 ──

    def _on_start(self):
        self._running = True
        self._iteration = 0
        self._prev_rmse = None
        self._result_text.clear()
        self._result_text.append(
            QApplication.translate("CalibrationDialog",
                "提示: 每轮显示的 RMSE 为该轮校准前(上一次模拟)的误差; "
                "校准前请确认高程/水源水头/滴头参数正确——"
                "C 值校准只应吸收管路损失部分的误差。"))
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._btn_apply.setEnabled(False)
        self._progress.setMaximum(self._spin_iter.value())
        self._progress.setValue(0)
        self._run_one_iteration()

    def _on_stop(self):
        self._running = False
        self._finish()

    def _finish(self):
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._btn_apply.setEnabled(self._iteration > 0)
        if self._iteration > 0:
            self._result_text.append(
                QApplication.translate("CalibrationDialog", "\n── 校准{0}，共 {1} 次迭代 ──").format('完成' if not self._running else '已停止', self._iteration))

    def _on_apply(self):
        """应用校准结果:C 值已在每轮迭代中写入 aqd_pipes.roughness,
        此处触发完整重新模拟,让校准效果(压力/流量/均匀度)可见。
        """
        self._result_text.append(
            QApplication.translate("CalibrationDialog",
                "\n✅ 校准的 C 值已写入管道图层，正在用校准后参数重新模拟..."))
        self._btn_apply.setEnabled(False)
        self.apply_requested.emit()

    def _run_one_iteration(self):
        if not self._running:
            self._finish(); return
        self._iteration += 1
        self._progress.setValue(self._iteration)

        try:
            algo = self._get_algorithm()
            result = algo.calibrate(self._obs_data)
            rmse = result["rmse"]
            details = result.get("details", [])
            type_stats = result.get("type_stats", {})

            self._result_text.append(
                QApplication.translate("CalibrationDialog", "\n── 迭代 {0}  RMSE = {1:.2f} m  ({2} 条管道)  [{3}]").format(self._iteration, rmse, len(details), algo.label))

            # 距管网过远被跳过的观测点(放错位置的观测点不参与校准)
            for lb, dist in result.get("skipped_obs", []):
                # 地理坐标(度)粗略换算为米显示
                shown = f"{dist * 111000:.0f}m" if dist < 0.01 else f"{dist:.1f}m"
                self._result_text.append(
                    QApplication.translate("CalibrationDialog",
                        "  ⚠️ 观测点 {0} 距管网 {1} 超过匹配半径，已跳过").format(lb, shown))

            for lid, pt, old_c, new_c, delta in details:
                sign = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
                # 小变化时显示更多小数位，避免 130→130(↓0) 的迷惑显示
                if abs(delta) < 0.5:
                    self._result_text.append(
                        f"  {lid} [{pt}] C: {old_c:.2f} → {new_c:.2f} ({sign}{abs(delta):.2f})")
                else:
                    self._result_text.append(
                        f"  {lid} [{pt}] C: {old_c:.0f} → {new_c:.0f} ({sign}{abs(delta):.0f})")

            # 分类型统计：显示各管道类型的 hf² 权重和平均调整量
            if type_stats:
                type_names = {"mainline": QApplication.translate("CalibrationDialog", "干管"), "submain": QApplication.translate("CalibrationDialog", "支管"),
                              "lateral": QApplication.translate("CalibrationDialog", "毛管")}
                parts = []
                for pt in ("mainline", "submain", "lateral"):
                    ts = type_stats.get(pt)
                    if ts and ts["count"] > 0:
                        w = ts.get("hf2_weight", 0)
                        avg_d = ts.get("avg_delta", 0)
                        sign = "↑" if avg_d > 0 else ("↓" if avg_d < 0 else "→")
                        parts.append(
                            QApplication.translate("CalibrationDialog", "{0} {1}条(hf²={2:.0f}% {3}{4:.1f})").format(type_names.get(pt, pt), ts['count'], w*100, sign, abs(avg_d)))
                if parts:
                    self._result_text.append(
                        QApplication.translate("CalibrationDialog", "  📊 分型: ").format() + " | ".join(parts))

            # 收敛判据：RMSE 变化 < 0.02 且本次参数无实际变化
            has_change = any(abs(d) > 0.05 for _, _, _, _, d in details)
            if self._prev_rmse is not None and abs(rmse - self._prev_rmse) < 0.02:
                if not has_change:
                    self._result_text.append(QApplication.translate("CalibrationDialog", "  ✓ 已收敛 (参数无变化)")); self._finish(); return
            if rmse < 0.1:
                self._result_text.append("  ✓ RMSE < 0.1m"); self._finish(); return
            if self._iteration >= self._spin_iter.value():
                self._result_text.append(QApplication.translate("CalibrationDialog", "  ✓ 达到最大迭代次数")); self._finish(); return
            self._prev_rmse = rmse
        except Exception as e:
            import traceback
            self._result_text.append(QApplication.translate("CalibrationDialog", "\n❌ 迭代 {0} 失败: {1}\n{2}").format(self._iteration, e, traceback.format_exc()))
            self._finish(); return

        self.sim_requested.emit(self._obs_data)

    def on_sim_done(self, new_obs_data: dict):
        self._obs_data = new_obs_data
        if self._running:
            self._run_one_iteration()
