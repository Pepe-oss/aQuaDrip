# -*- coding: utf-8 -*-
"""
aQuaDrip — 基于 QGIS + WNTR 的智能滴灌设计与水肥一体化分析平台
"""

from aquadrip_plugin import AQuaDripPlugin


def classFactory(iface):
    """QGIS 插件入口"""
    return AQuaDripPlugin(iface)
