"""builder — 管网构建器

所有 Builder 输出 TopologyGraph，不是 Geometry。
几何由单独的 Geometry 层处理。
"""

from .base import LayoutBuilder, LayoutParams
from .rectangular import RectangularLayoutBuilder

__all__ = [
    "LayoutBuilder",
    "LayoutParams",
    "RectangularLayoutBuilder",
]
