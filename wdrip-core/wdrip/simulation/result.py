"""SimulationResult — 模拟结果数据类"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class SimulationResult:
    """模拟结果
    
    封装 WNTR 模拟结果，提供滴灌专用分析接口。
    
    Attributes:
        success: 是否成功
        message: 消息（错误信息等）
        node_pressure: 节点压力 {node_id: np.ndarray} (m)
        node_demand: 节点需水量 {node_id: np.ndarray} (m³/s)
        link_flow: 管段流量 {link_id: np.ndarray} (m³/s)
        link_velocity: 管段流速 {link_id: np.ndarray} (m/s)
        emitter_flow: 滴头流量 {node_id: np.ndarray} (L/h)
        node_quality: 节点水质 {node_id: np.ndarray}（水肥模拟用）
        time_steps: 时间步（seconds）
        duration_seconds: 模拟时长（seconds）
    """
    success: bool = False
    message: str = ""
    node_pressure: Dict[str, np.ndarray] = field(default_factory=dict)
    node_demand: Dict[str, np.ndarray] = field(default_factory=dict)
    link_flow: Dict[str, np.ndarray] = field(default_factory=dict)
    link_velocity: Dict[str, np.ndarray] = field(default_factory=dict)
    emitter_flow: Dict[str, np.ndarray] = field(default_factory=dict)
    node_quality: Dict[str, np.ndarray] = field(default_factory=dict)
    time_steps: np.ndarray = field(default_factory=lambda: np.array([0]))
    duration_seconds: int = 0

    def get_pressure_at(self, node_id: str, timestep: int = 0) -> Optional[float]:
        """获取指定节点在指定时间步的压力"""
        arr = self.node_pressure.get(node_id)
        if arr is not None and len(arr) > timestep:
            return float(arr[timestep])
        return None

    def get_flow_at(self, link_id: str, timestep: int = 0) -> Optional[float]:
        """获取指定管段在指定时间步的流量"""
        arr = self.link_flow.get(link_id)
        if arr is not None and len(arr) > timestep:
            return float(abs(arr[timestep]))
        return None

    def get_emitter_flow_at(self, node_id: str, timestep: int = 0) -> Optional[float]:
        """获取指定滴头在指定时间步的流量"""
        arr = self.emitter_flow.get(node_id)
        if arr is not None and len(arr) > timestep:
            return float(arr[timestep])
        return None

    @property
    def emitter_flows_summary(self) -> Dict[str, float]:
        """滴头流量统计"""
        flows = []
        for arr in self.emitter_flow.values():
            if len(arr) > 0:
                flows.extend(arr)
        if not flows:
            return {"min": 0, "max": 0, "avg": 0, "count": 0}
        return {
            "min": float(np.min(flows)),
            "max": float(np.max(flows)),
            "avg": float(np.mean(flows)),
            "count": len(flows),
        }
