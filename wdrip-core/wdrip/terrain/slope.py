"""坡度计算 / 压力分区 / PRV 推荐"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from wdrip.network import DripNetwork


@dataclass
class SlopeResult:
    """管段坡度计算结果"""
    link_id: str
    from_node: str
    to_node: str
    from_elevation: float
    to_elevation: float
    length: float
    elevation_diff: float       # 高差 (m)，正=上坡，负=下坡
    slope_percent: float        # 坡度百分比 (%)
    slope_degree: float         # 坡度角度 (°)

    @property
    def is_uphill(self) -> bool:
        """是否上坡（水流方向）"""
        return self.elevation_diff > 0

    @property
    def is_steep(self) -> bool:
        """是否陡坡（>10%）"""
        return abs(self.slope_percent) > 10


@dataclass
class PressureZone:
    """压力分区"""
    name: str
    node_ids: List[str]
    avg_elevation: float
    min_elevation: float
    max_elevation: float
    elevation_range: float
    suggested_prv: Optional[str] = None  # 建议 PRV 位置


@dataclass
class PrvRecommendation:
    """PRV 减压阀推荐"""
    position_node: str        # 安装位置（节点ID）
    upstream_pressure: float  # 上游压力 (m)
    downstream_pressure: float  # 目标下游压力 (m)
    reason: str               # 推荐原因


class SlopeAnalyzer:
    """坡度分析器
    
    基于节点高程计算每条管段的坡度。
    """
    
    def analyze(self, network: 'DripNetwork') -> List[SlopeResult]:
        """分析管网中所有管段的坡度"""
        results = []
        for lid, link in network.links.items():
            from_node = network.nodes.get(link.from_node)
            to_node = network.nodes.get(link.to_node)
            if not from_node or not to_node:
                continue
            
            elev_diff = to_node.elevation - from_node.elevation
            length = getattr(link, "length", 0)
            
            slope_pct = 0.0
            slope_deg = 0.0
            if length > 0:
                slope_pct = (elev_diff / length) * 100
                slope_deg = math.degrees(math.atan(elev_diff / length))
            
            results.append(SlopeResult(
                link_id=lid,
                from_node=link.from_node,
                to_node=link.to_node,
                from_elevation=from_node.elevation,
                to_elevation=to_node.elevation,
                length=length,
                elevation_diff=elev_diff,
                slope_percent=round(slope_pct, 3),
                slope_degree=round(slope_deg, 2),
            ))
        
        return results
    
    def get_summary(self, results: List[SlopeResult]) -> dict:
        """坡度统计摘要"""
        if not results:
            return {"max_slope": 0, "avg_slope": 0, "steep_count": 0}
        
        slopes = [abs(r.slope_percent) for r in results]
        return {
            "max_slope": round(max(slopes), 2),
            "min_slope": round(min(slopes), 2),
            "avg_slope": round(sum(slopes) / len(slopes), 2),
            "steep_count": sum(1 for r in results if r.is_steep),
            "uphill_count": sum(1 for r in results if r.is_uphill),
            "total_links": len(results),
        }


class PressureZoneAnalyzer:
    """压力分区分析器
    
    基于高程变化将管网划分为多个压力分区，
    每个分区内高程变化较小，适合统一压力管理。
    """
    
    def __init__(self, max_elevation_range: float = 10.0):
        """
        Args:
            max_elevation_range: 每个分区允许的最大高差 (m)
        """
        self.max_elevation_range = max_elevation_range
    
    def analyze(self, network: 'DripNetwork') -> List[PressureZone]:
        """分析压力分区"""
        if not network.nodes:
            return []
        
        # 按高程对节点分组
        nodes_by_elevation = sorted(
            [(nid, node.elevation) for nid, node in network.nodes.items()],
            key=lambda x: x[1],
        )
        
        zones = []
        current_zone_nodes = []
        current_min = float("inf")
        current_max = float("-inf")
        
        for nid, elev in nodes_by_elevation:
            current_min = min(current_min, elev)
            current_max = max(current_max, elev)
            
            if current_max - current_min > self.max_elevation_range:
                # 当前分区结束，开始新分区
                if current_zone_nodes:
                    zones.append(self._make_zone(zones, current_zone_nodes, current_min, current_max))
                current_zone_nodes = []
                current_min = elev
                current_max = elev
            
            current_zone_nodes.append(nid)
        
        if current_zone_nodes:
            zones.append(self._make_zone(zones, current_zone_nodes, current_min, current_max))
        
        return zones
    
    def _make_zone(self, existing: list, node_ids: list,
                   min_elev: float, max_elev: float) -> PressureZone:
        return PressureZone(
            name=f"Zone{len(existing) + 1}",
            node_ids=node_ids,
            avg_elevation=round((min_elev + max_elev) / 2, 2),
            min_elevation=round(min_elev, 2),
            max_elevation=round(max_elev, 2),
            elevation_range=round(max_elev - min_elev, 2),
        )


class PrvRecommender:
    """PRV 减压阀位置推荐
    
    基于坡度分析结果，在高程差大的位置推荐安装 PRV。
    """
    
    def __init__(self, max_pressure_drop: float = 30.0):
        """
        Args:
            max_pressure_drop: 允许的最大压力差 (m)
        """
        self.max_pressure_drop = max_pressure_drop
    
    def recommend(self, network: 'DripNetwork',
                  slope_results: List[SlopeResult]) -> List[PrvRecommendation]:
        """推荐 PRV 安装位置"""
        recommendations = []
        
        # 策略：在陡坡（下坡）管段的上游节点推荐 PRV
        for sr in slope_results:
            if sr.is_steep and not sr.is_uphill:
                # 陡下坡，需要考虑减压
                pressure_drop = abs(sr.elevation_diff)
                if pressure_drop > self.max_pressure_drop:
                    recommendations.append(PrvRecommendation(
                        position_node=sr.from_node,
                        upstream_pressure=round(pressure_drop, 1),
                        downstream_pressure=round(self.max_pressure_drop, 1),
                        reason=(
                            f"坡度 {sr.slope_percent}%，高差 {abs(sr.elevation_diff):.1f}m，"
                            f"超过建议值 {self.max_pressure_drop}m"
                        ),
                    ))
        
        # 按压力差排序
        recommendations.sort(key=lambda r: r.upstream_pressure, reverse=True)
        return recommendations
