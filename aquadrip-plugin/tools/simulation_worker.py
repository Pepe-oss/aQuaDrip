"""SimulationWorker — 后台模拟运行器

使用 QThread + QObject.moveToThread 模式，在后台线程运行 WNTR 模拟，
通过信号报告进度和结果，避免冻结 QGIS UI。
"""

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtWidgets import QApplication


class SimulationWorker(QObject):
    """后台模拟 Worker（必须在 QThread 中运行）"""

    progress_changed = pyqtSignal(int, str)   # (0-100, 描述)
    finished = pyqtSignal(object)              # SimulationResult
    error_occurred = pyqtSignal(str)           # 错误消息

    def __init__(self, net, precision: str = "fast", parent=None):
        """
        Args:
            net: DripNetwork 管网对象
            precision: "fast" / "standard" / "high"
        """
        super().__init__(parent)
        self._net = net
        self._precision = precision

    def run(self):
        """后台执行模拟（由 QThread.started 信号触发）"""
        try:
            # 1. 构建 WNTR 模型
            self.progress_changed.emit(2, QApplication.translate("SimulationWorker", "构建 WNTR 模型..."))
            from wdrip.simulation import DripSimulation
            sim = DripSimulation(self._net, precision=self._precision)

            # 2. 运行模拟（传入进度回调）
            result = sim.run(progress_callback=self._on_engine_progress)

            if result.success:
                self.finished.emit(result)
            else:
                self.error_occurred.emit(result.message)
        except Exception as e:
            import traceback
            self.error_occurred.emit(f"{e}\n{traceback.format_exc()}")

    def _on_engine_progress(self, pct: int, msg: str):
        """迭代引擎的进度回调 → 转发为信号（确保线程安全）"""
        self.progress_changed.emit(pct, msg)
