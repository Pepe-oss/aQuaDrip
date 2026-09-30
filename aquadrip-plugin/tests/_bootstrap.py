# -*- coding: utf-8 -*-
"""headless QGIS 测试引导——统一环境初始化与通用桩

每个 QGIS 相关测试的开头:

    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _bootstrap import init_qgis, IF, LOGS, REPO_ROOT, PLUGIN_DIR

纯 stdlib 的测试(如 test_sim_history)不需要本模块。

平台说明见 tests/README.md。环境变量:
    QGIS_PREFIX_PATH  QGIS 安装前缀(默认 /Applications/QGIS.app/Contents/Resources)
    PROJ_LIB          proj 数据库目录(macOS QGIS.app 下会自动探测)
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(HERE)                 # aquadrip-plugin/
REPO_ROOT = os.path.dirname(PLUGIN_DIR)            # aQuaDrip/
WDRIP_CORE = os.path.join(REPO_ROOT, "wdrip-core")

# messageBar 桩的输出收集(每个测试自行清理)
LOGS = []


class _Bar:
    def pushMessage(self, *a, **k):
        LOGS.append(("msg", str(a[-1] if len(a) > 1 else a[0])))

    def pushWarning(self, *a, **k):
        LOGS.append(("warn", str(a[-1] if len(a) > 1 else a[0])))


class IF:
    """iface 桩:messageBar 输出进 LOGS 供断言;可选持有画布"""

    def __init__(self, canvas=None):
        self._canvas = canvas

    def mainWindow(self):
        return None

    def messageBar(self):
        return _Bar()

    def mapCanvas(self):
        return self._canvas


_QGIS_APP = None


def init_qgis(canvas_crs: str = "EPSG:4326"):
    """初始化 headless QgsApplication(幂等),返回 (app, canvas)"""
    global _QGIS_APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    # macOS QGIS.app 的 proj 数据库(存在才设置;其他平台由系统提供)
    _mac_proj = "/Applications/QGIS.app/Contents/Resources/qgis/proj"
    if os.path.isdir(_mac_proj):
        os.environ.setdefault("PROJ_LIB", _mac_proj)
        os.environ.setdefault("PROJ_DATA", _mac_proj)

    for p in (WDRIP_CORE, PLUGIN_DIR):
        if p not in sys.path:
            sys.path.insert(0, p)

    from qgis.core import QgsApplication, QgsCoordinateReferenceSystem
    from qgis.gui import QgsMapCanvas

    if _QGIS_APP is None:
        prefix = os.environ.get("QGIS_PREFIX_PATH") \
            or "/Applications/QGIS.app/Contents/Resources"
        QgsApplication.setPrefixPath(prefix, True)
        _QGIS_APP = QgsApplication([], False)
        _QGIS_APP.initQgis()

    canvas = QgsMapCanvas()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem(canvas_crs))
    return _QGIS_APP, canvas
