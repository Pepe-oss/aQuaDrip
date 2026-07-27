"""ProjectStateMachine — 项目状态机

管理插件全局状态，控制 UI 按钮的启用/禁用。

状态流转:
  New ──→ FieldImported ──→ LayoutGenerated ──→ ParametersAssigned
                                                      │
                                                      ▼
                                              SimulationReady ──→ SimulationRunning ──→ SimulationFinished
                                                      │                              │
                                                      └── (参数修改) ──────────────┘
                                      
  SimulationFinished ──→ Export (导出)
  SimulationFinished ──→ Calibrating ──→ Calibrated ──→ ParametersAssigned (重新模拟)
"""

from enum import Enum, auto


class ProjectState(Enum):
    """项目状态"""
    NEW = "NEW"                       # 新建/空项目
    FIELD_IMPORTED = "FIELD_IMPORTED" # 已导入农田
    LAYOUT_GENERATED = "LAYOUT_GENERATED"  # 已生成管网
    PARAMETERS_ASSIGNED = "PARAMETERS_ASSIGNED"  # 已配置参数
    SIMULATION_READY = "SIMULATION_READY"      # 模拟就绪
    SIMULATION_RUNNING = "SIMULATION_RUNNING"  # 模拟运行中
    SIMULATION_FINISHED = "SIMULATION_FINISHED" # 模拟完成
    CALIBRATING = "CALIBRATING"       # 校准中
    CALIBRATED = "CALIBRATED"         # 校准完成
    EXPORTED = "EXPORTED"             # 已导出


class ProjectStateMachine:
    """项目状态机"""

    # 状态迁移表: {当前状态: [可迁移到的状态]}
    TRANSITIONS = {
        ProjectState.NEW: [ProjectState.FIELD_IMPORTED],
        ProjectState.FIELD_IMPORTED: [
            ProjectState.LAYOUT_GENERATED,
            ProjectState.NEW,  # 取消
        ],
        ProjectState.LAYOUT_GENERATED: [
            ProjectState.PARAMETERS_ASSIGNED,
            ProjectState.FIELD_IMPORTED,  # 重新导入
        ],
        ProjectState.PARAMETERS_ASSIGNED: [
            ProjectState.SIMULATION_READY,
            ProjectState.LAYOUT_GENERATED,  # 重新生成
        ],
        ProjectState.SIMULATION_READY: [
            ProjectState.SIMULATION_RUNNING,
            ProjectState.PARAMETERS_ASSIGNED,  # 修改参数
        ],
        ProjectState.SIMULATION_RUNNING: [
            ProjectState.SIMULATION_FINISHED,
            ProjectState.SIMULATION_READY,  # 取消运行
        ],
        ProjectState.SIMULATION_FINISHED: [
            ProjectState.EXPORTED,
            ProjectState.CALIBRATING,
            ProjectState.PARAMETERS_ASSIGNED,  # 修改参数重新模拟
        ],
        ProjectState.CALIBRATING: [
            ProjectState.CALIBRATED,
            ProjectState.SIMULATION_FINISHED,  # 取消校准
        ],
        ProjectState.CALIBRATED: [
            ProjectState.PARAMETERS_ASSIGNED,  # 应用校准后重新模拟
            ProjectState.SIMULATION_FINISHED,  # 放弃校准
        ],
        ProjectState.EXPORTED: [
            ProjectState.SIMULATION_FINISHED,  # 继续编辑
            ProjectState.NEW,  # 新建项目
        ],
    }

    def __init__(self):
        self._state = ProjectState.NEW
        self._listeners = []

    @property
    def state(self) -> ProjectState:
        return self._state

    def can_transition_to(self, target: ProjectState) -> bool:
        """检查是否能迁移到目标状态"""
        if target == self._state:
            return True
        return target in self.TRANSITIONS.get(self._state, [])

    def transition_to(self, target: ProjectState) -> bool:
        """迁移到目标状态"""
        if not self.can_transition_to(target):
            raise ValueError(
                f"不能从 {self._state.value} 迁移到 {target.value}"
            )
        old_state = self._state
        self._state = target
        self._notify(old_state, target)
        return True

    def reset(self):
        """重置到初始状态"""
        old = self._state
        self._state = ProjectState.NEW
        self._notify(old, self._state)

    # ---- 便捷方法 ----

    @property
    def is_new(self) -> bool:
        return self._state == ProjectState.NEW

    @property
    def has_field(self) -> bool:
        return self._state.value >= ProjectState.FIELD_IMPORTED.value

    @property
    def has_network(self) -> bool:
        return self._state.value >= ProjectState.LAYOUT_GENERATED.value

    @property
    def has_parameters(self) -> bool:
        return self._state.value >= ProjectState.PARAMETERS_ASSIGNED.value

    @property
    def can_simulate(self) -> bool:
        return self._state == ProjectState.SIMULATION_READY

    @property
    def is_simulating(self) -> bool:
        return self._state == ProjectState.SIMULATION_RUNNING

    @property
    def has_results(self) -> bool:
        return self._state.value >= ProjectState.SIMULATION_FINISHED.value

    # ---- 观察者 ----

    def add_listener(self, callback):
        """添加状态变化监听器
        
        Args:
            callback: fn(old_state, new_state)
        """
        self._listeners.append(callback)

    def remove_listener(self, callback):
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify(self, old_state: ProjectState, new_state: ProjectState):
        for cb in self._listeners:
            try:
                cb(old_state, new_state)
            except Exception as e:
                import traceback
                traceback.print_exc()
