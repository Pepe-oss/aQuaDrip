# -*- coding: utf-8 -*-
"""
aQuaDrip — 基于 QGIS + WNTR 的智能滴灌设计与水肥一体化分析平台
"""

import os
import sys

# 将 wdrip-core 加入 Python 路径（必须在导入 wdrip 之前）
_wdrip_core = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "wdrip-core")
_wdrip_core = os.path.abspath(_wdrip_core)

# 确保 wdrip-core 路径可访问
_fallback = "/Users/soarchen/开发/aQuaDrip/wdrip-core"

for _p in [_wdrip_core, _fallback]:
    if os.path.isdir(os.path.join(_p, "wdrip")) and _p not in sys.path:
        sys.path.insert(0, _p)

from .aquadrip_plugin import AQuaDripPlugin


def classFactory(iface):
    """QGIS 插件入口"""
    return AQuaDripPlugin(iface)
