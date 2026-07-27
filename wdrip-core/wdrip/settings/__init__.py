"""SettingsManager — 全局配置管理

统一管理插件的默认设置，包括单位制、默认滴头型号、
默认管材、DEM 配置、语言和主题。
"""

import json
import os
from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class Settings:
    """配置数据类"""
    # 单位
    units: str = "SI"  # SI / US
    # 默认滴头
    default_emitter_key: str = "Netafim_DripperNet_16mm_1.6"
    # 默认管材
    default_pipe_material: str = "PE"
    default_pipe_roughness: float = 130.0
    # DEM
    use_dem: bool = False
    dem_raster_path: str = ""
    dem_band: int = 1
    # 布局
    default_planting_pattern: str = "uniform"
    default_row_spacing: float = 0.5
    default_emitter_spacing: float = 0.3
    # 模拟
    default_simulation_duration_hours: float = 2.0
    default_hydraulic_timestep: int = 3600
    # 界面
    language: str = "zh"
    # 文件路径
    last_project_path: str = ""


class SettingsManager:
    """配置管理器（单例模式）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._settings = Settings()
            cls._instance._config_dir = cls._get_config_dir()
            cls._instance._config_file = os.path.join(
                cls._instance._config_dir, "settings.json"
            )
        return cls._instance

    @staticmethod
    def _get_config_dir() -> str:
        """获取配置目录"""
        if os.name == "nt":
            base = os.environ.get("APPDATA", os.path.expanduser("~"))
        else:
            base = os.path.expanduser("~")
        config_dir = os.path.join(base, ".aquadrip")
        try:
            os.makedirs(config_dir, exist_ok=True)
        except (PermissionError, OSError):
            # 回退到临时目录
            import tempfile
            config_dir = os.path.join(tempfile.gettempdir(), ".aquadrip")
            os.makedirs(config_dir, exist_ok=True)
        return config_dir

    def load(self):
        """从文件加载配置"""
        try:
            if os.path.exists(self._config_file):
                with open(self._config_file, "r") as f:
                    data = json.load(f)
                for key, value in data.items():
                    if hasattr(self._settings, key):
                        setattr(self._settings, key, value)
        except (json.JSONDecodeError, IOError):
            pass

    def save(self):
        """保存配置到文件"""
        try:
            data = {
                k: v for k, v in self._settings.__dict__.items()
                if not k.startswith("_")
            }
            with open(self._config_file, "w") as f:
                json.dump(data, f, indent=2)
        except IOError:
            pass

    def get(self, key: str, default=None):
        """获取配置项"""
        return getattr(self._settings, key, default)

    def set(self, key: str, value):
        """设置配置项"""
        if hasattr(self._settings, key):
            setattr(self._settings, key, value)

    def reset(self):
        """重置为默认值"""
        self._settings = Settings()
