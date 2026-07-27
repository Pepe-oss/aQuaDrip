"""analysis — 结果分析模块

包含：
- UniformityAnalyzer: CU/DU/EU 均匀度计算
- FertigationAnalyzer: 水肥浓度运移分析
- CalibrationAnalyzer: 实测vs模拟对比 + 参数校正
"""

from .uniformity import UniformityAnalyzer
from .fertigation import FertigationAnalyzer
from .calibration import CalibrationAnalyzer

__all__ = [
    "UniformityAnalyzer",
    "FertigationAnalyzer",
    "CalibrationAnalyzer",
]
