# -*- coding: utf-8 -*-
"""
aQuaDrip — 基于 QGIS + WNTR 的智能滴灌设计与水肥一体化分析平台
"""

import os
import sys

# 将 wdrip-core 加入 Python 路径（插件与 wdrip-core 同级目录部署）
_wdrip_core = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "wdrip-core")
_wdrip_core = os.path.abspath(_wdrip_core)
if os.path.isdir(os.path.join(_wdrip_core, "wdrip")) and _wdrip_core not in sys.path:
    sys.path.insert(0, _wdrip_core)

from .aquadrip_plugin import AQuaDripPlugin


def classFactory(iface):
    """QGIS 插件入口"""
    return AQuaDripPlugin(iface)
