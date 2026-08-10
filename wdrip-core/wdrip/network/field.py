"""农田信息与耕作参数"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class FieldInfo:
    """农田信息与耕作参数
    
    定义农田的几何边界、作物信息和种植模式。
    耕作模式（planting_pattern）影响毛管的生成算法：
    - "uniform": 等行距，由 row_spacings 的第一个值控制
    - "wide_narrow": 宽窄行交替，row_spacings = [宽行距, 窄行距]
    - "ridge_count": 按垄数计算，由 ridge_count 控制
    - "custom": 自定义行距，row_spacings 为逐行距离列表
    
    Attributes:
        geometry: 农田多边形几何（QgsGeometry 或 Shapely Polygon）
        area: 面积（m²）
        crop_type: 作物类型
        planting_pattern: 耕作模式
        row_spacings: 行距序列（m），不同模式含义不同
        ridge_count: 垄数（ridge_count 模式下使用）
        plant_spacing: 株距（m）
        lateral_spacing: 毛管间距（m），等行距模式下默认=行距
        row_direction: 种植行向（度，0=水平，90=垂直）
        irrigation_method: 灌溉方式（surface_drip=地表滴灌, subsurface=地下滴灌）
        emitter_spacing: 滴头间距（m）
    """
    geometry: object = None
    area: float = 0.0
    crop_type: str = ""
    planting_pattern: str = "uniform"  # uniform / wide_narrow / ridge_count / custom
    row_spacings: List[float] = field(default_factory=lambda: [0.5])
    ridge_count: Optional[int] = None
    plant_spacing: float = 0.3
    lateral_spacing: Optional[float] = None
    row_direction: float = 0.0
    irrigation_method: str = "surface_drip"
    emitter_spacing: float = 0.3

    def __post_init__(self):
        """初始化后处理"""
        if self.lateral_spacing is None and self.planting_pattern == "uniform":
            self.lateral_spacing = self.row_spacings[0]

    @property
    def effective_lateral_spacing(self) -> float:
        """实际毛管间距（m）"""
        if self.lateral_spacing is not None:
            return self.lateral_spacing
        return self.row_spacings[0]

    def validate(self) -> List[str]:
        """检查参数合法性，返回错误列表"""
        errors = []
        if self.area <= 0:
            errors.append("面积必须大于 0")
        if self.planting_pattern == "ridge_count":
            if not self.ridge_count or self.ridge_count <= 0:
                errors.append("垄数模式必须指定垄数（>0）")
        else:
            if not self.row_spacings or all(s <= 0 for s in self.row_spacings):
                errors.append("行距必须大于 0")
        if self.emitter_spacing <= 0:
            errors.append("滴头间距必须大于 0")
        return errors
