"""灌溉制度与轮灌分组"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class IrrigationCycle:
    """灌水周期
    
    Attributes:
        name: 周期名称
        start_hour: 开始时间（小时，0~24）
        duration_hours: 持续时长（小时）
    """
    name: str = ""
    start_hour: float = 0.0
    duration_hours: float = 6.0


@dataclass
class ShiftGroup:
    """轮灌分组
    
    定义阀门开启时间表，实现分区轮灌。
    例如阀门1在 0~0.5h 开启，阀门2在 0.5~1h 开启。
    
    Attributes:
        name: 分组名称
        valve_ids: 本组关联的阀门 ID 列表
        open_start: 开启起始时间（小时，相对灌溉周期起点）
        open_end: 开启结束时间（小时）
    """
    name: str = ""
    valve_ids: List[str] = field(default_factory=list)
    open_start: float = 0.0
    open_end: float = 1.0

    @property
    def duration_hours(self) -> float:
        """本组灌水时长（小时）"""
        return max(0, self.open_end - self.open_start)


@dataclass
class IrrigationSchedule:
    """灌溉制度
    
    定义整个灌溉系统的运行计划，包括灌水周期和轮灌分组。
    在 WNTR 中通过 TimePattern 和 Valve.status 实现。
    
    Attributes:
        name: 制度名称
        cycles: 灌水周期列表
        shift_groups: 轮灌分组列表
        total_duration_hours: 总模拟时长（小时）
    """
    name: str = "default"
    cycles: List[IrrigationCycle] = field(default_factory=list)
    shift_groups: List[ShiftGroup] = field(default_factory=list)
    total_duration_hours: float = 24.0

    def add_shift_group(self, name: str, valve_ids: List[str],
                        start: float, end: float) -> ShiftGroup:
        """添加轮灌分组"""
        group = ShiftGroup(
            name=name,
            valve_ids=valve_ids,
            open_start=start,
            open_end=end,
        )
        self.shift_groups.append(group)
        return group

    def get_valve_schedule(self, valve_id: str) -> Optional[Tuple[float, float]]:
        """获取指定阀门的开启时间段
        
        Returns:
            (start, end) 或 None（未找到）
        """
        for group in self.shift_groups:
            if valve_id in group.valve_ids:
                return (group.open_start, group.open_end)
        return None

    def validate(self) -> List[str]:
        """检查参数合法性"""
        errors = []
        # 检查轮灌组时间是否重叠
        times = [(g.open_start, g.open_end) for g in self.shift_groups]
        for i, (s1, e1) in enumerate(times):
            for j, (s2, e2) in enumerate(times):
                if i < j and s1 < e2 and s2 < e1:
                    errors.append(
                        f"轮灌组 {self.shift_groups[i].name} 和 "
                        f"{self.shift_groups[j].name} 的时间重叠"
                    )
        return errors
