# -*- coding: utf-8 -*-
"""
aQuaDrip — 基于 QGIS + WNTR 的智能滴灌设计与水肥一体化分析平台
"""

import os
import sys

# 定位 wdrip 核心库,两种布局按优先级查找:
#   1. 随插件分发的 wdrip 包(单一 ZIP 安装布局:<plugin>/wdrip)
#   2. 开发布局:插件目录同级的 wdrip-core 仓库
#      (<repo>/aquadrip-plugin 与 <repo>/wdrip-core,软链部署时
#       realpath 会正确解析到仓库真实路径)
_here = os.path.dirname(os.path.realpath(__file__))
_wdrip_core = os.path.abspath(os.path.join(_here, "..", "wdrip-core"))
if os.path.isdir(os.path.join(_here, "wdrip")):
    _wdrip_root = _here
elif os.path.isdir(os.path.join(_wdrip_core, "wdrip")):
    _wdrip_root = _wdrip_core
else:
    _wdrip_root = None
if _wdrip_root and _wdrip_root not in sys.path:
    sys.path.insert(0, _wdrip_root)

from .aquadrip_plugin import AQuaDripPlugin


def classFactory(iface):
    """QGIS 插件入口"""
    # 必须在实例化插件(创建任何 UI)之前安装翻译器,
    # 否则首个会话的界面字符串会以源语言(中文)显示。
    # 翻译层任何异常都不阻断插件加载(回退中文源语言)。
    try:
        from .tools.i18n import install_translator
        install_translator()
    except Exception:
        import traceback
        traceback.print_exc()
    return AQuaDripPlugin(iface)
