"""Calibrator — 兼容层，委托给 calib_algorithm

CalibrationDialog 直接调用 HazenWilliamsCalibrator，本文件保留为向后兼容。
"""

from .calib_algorithm import HazenWilliamsCalibrator

# 向后兼容的别名
Calibrator = HazenWilliamsCalibrator
