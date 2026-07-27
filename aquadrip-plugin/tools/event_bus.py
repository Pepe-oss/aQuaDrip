"""EventBus — 模块间事件总线

解耦插件各模块，通过事件通信而非直接调用。
"""

from typing import Callable, Dict, List, Any


class Event:
    """事件基类"""
    def __init__(self, name: str, data: Any = None):
        self.name = name
        self.data = data


# 预定义事件名称
FIELD_CHANGED = "field_changed"
NETWORK_CHANGED = "network_changed"
PARAMETERS_CHANGED = "parameters_changed"
SIMULATION_STARTED = "simulation_started"
SIMULATION_FINISHED = "simulation_finished"
SIMULATION_PROGRESS = "simulation_progress"
LAYER_UPDATED = "layer_updated"
PROJECT_SAVED = "project_saved"
PROJECT_LOADED = "project_loaded"
SELECTION_CHANGED = "selection_changed"
CALIBRATION_POINT_ADDED = "calibration_point_added"
CALIBRATION_COMPLETED = "calibration_completed"
LATERAL_DELETED = "lateral_deleted"
LATERAL_TRIMMED = "lateral_trimmed"
ZONE_CHANGED = "zone_changed"
ERROR_OCCURRED = "error_occurred"


class EventBus:
    """事件总线（单例）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._handlers: Dict[str, List[Callable]] = {}
        return cls._instance

    def on(self, event_name: str, handler: Callable):
        """注册事件监听"""
        if event_name not in self._handlers:
            self._handlers[event_name] = []
        self._handlers[event_name].append(handler)

    def off(self, event_name: str, handler: Callable = None):
        """取消事件监听"""
        if event_name not in self._handlers:
            return
        if handler is None:
            del self._handlers[event_name]
        else:
            self._handlers[event_name] = [
                h for h in self._handlers[event_name] if h != handler
            ]

    def emit(self, event_name: str, data: Any = None):
        """触发事件"""
        if event_name not in self._handlers:
            return
        for handler in self._handlers[event_name]:
            try:
                handler(data)
            except Exception as e:
                import traceback
                traceback.print_exc()

    def clear(self):
        """清除所有监听器"""
        self._handlers.clear()
