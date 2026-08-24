"""ProjectIO — 项目打开 / INP 导出

- is_aquadrip_gpkg(path): 校验 GPKG 是否为 aQuaDrip 项目
- load_layers(iface): 选择 .gpkg → 校验 → 一键加载 4 个图层到 QGIS
- export_inp(iface): sync → 构建 WNTR 模型 → write_inpfile()

(INP 导入功能已移除——如需恢复见 git 历史 import_inp)
"""

import os
import sqlite3
from typing import Optional, List

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsField, QgsFeature,
    QgsGeometry, QgsPointXY, QgsCoordinateReferenceSystem,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox
from qgis.PyQt.QtWidgets import QApplication

# 必须是这些图层中的核心五层才算 aQuaDrip 项目
SIGNATURE_LAYERS = ["aqd_fields", "aqd_pipes", "aqd_pumps", "aqd_valves", "aqd_nodes"]

# 核心字段检查（每个签名图层至少包含以下字段之一）
SIGNATURE_FIELDS = {
    "aqd_fields": ["planting_pattern", "emitter_spacing"],
    "aqd_pipes": ["pipe_type", "diameter"],
    "aqd_pumps": ["pump_head", "pump_flow"],
    "aqd_valves": ["valve_type", "diameter"],
    "aqd_nodes": ["node_type", "elevation"],
}


def is_aquadrip_gpkg(path: str) -> bool:
    """校验 GPKG 是否包含 aQuaDrip 项目的签名图层和字段"""
    conn = None
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        # 检查 gpkg_contents 中的图层
        cur.execute("SELECT table_name FROM gpkg_contents")
        tables = {row[0] for row in cur.fetchall()}
        for sig in SIGNATURE_LAYERS:
            if sig not in tables:
                return False
        # 检查每个签名图层的字段
        for sig in SIGNATURE_LAYERS:
            cur.execute(f"PRAGMA table_info(\"{sig}\")")
            columns = {row[1] for row in cur.fetchall()}
            if not any(f in columns for f in SIGNATURE_FIELDS[sig]):
                return False
        return True
    except (sqlite3.Error, OSError):
        return False
    finally:
        if conn is not None:
            conn.close()


def load_layers(iface) -> bool:
    """打开 QFileDialog → 校验 aQuaDrip GPKG → 加载图层到 QGIS 项目

    Returns:
        True 表示加载成功，False 表示用户取消或校验失败
    """
    path, _ = QFileDialog.getOpenFileName(
        iface.mainWindow(),
        QApplication.translate("ProjectIo", "打开 aQuaDrip 项目"),
        "",
        "GeoPackage (*.gpkg);;All Files (*)",
    )
    if not path:
        return False

    if not is_aquadrip_gpkg(path):
        QMessageBox.warning(
            iface.mainWindow(),
            "aQuaDrip",
            QApplication.translate("ProjectIo", "该文件不是 aQuaDrip 项目 GPKG：\n{0}\n\naQuaDrip 项目必须包含 {1} 图层。").format(path, ', '.join(SIGNATURE_LAYERS)))
        return False

    project = QgsProject.instance()

    # 从 GPKG 元数据读取原始 CRS（避免依赖当前项目 CRS）
    gpkg_crs = _read_gpkg_crs(path)

    loaded = 0
    for key in SIGNATURE_LAYERS + ["aqd_obs_points"]:
        uri = f"{path}|layername={key}"
        layer = QgsVectorLayer(uri, key, "ogr")
        if not layer.isValid():
            continue
        # 显式设置 CRS：优先 GPKG 元数据 CRS，回退项目 CRS
        if gpkg_crs and gpkg_crs.isValid():
            layer.setCrs(gpkg_crs)
        elif not layer.crs().isValid():
            project_crs = project.crs()
            if project_crs.isValid():
                layer.setCrs(project_crs)
        project.addMapLayer(layer)
        loaded += 1

    # 设置项目 CRS 与 GPKG 一致（避免"无坐标系"显示问题）
    if gpkg_crs and gpkg_crs.isValid():
        project.setCrs(gpkg_crs)
        iface.messageBar().pushMessage(
            "aQuaDrip",
            QApplication.translate("ProjectIo", "项目 CRS 已设为 {0}（来自 GPKG）").format(gpkg_crs.authid()),
            level=0, duration=4)

    iface.messageBar().pushMessage(
        "aQuaDrip",
        QApplication.translate("ProjectIo", "已加载 {0} 个图层（{1}）").format(loaded, os.path.basename(path)),
        level=0, duration=5)
    return True


def _read_gpkg_crs(path: str):
    """从 GPKG 的 gpkg_contents/gpkg_spatial_ref_sys 读取 CRS

    OGR 加载时空图层可能不自动识别 CRS，这里直接从元数据表读取。
    """
    conn = None
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute(
            "SELECT srs_id FROM gpkg_contents "
            "WHERE srs_id IS NOT NULL LIMIT 1")
        row = cur.fetchone()
        if row and row[0]:
            from qgis.core import QgsCoordinateReferenceSystem
            crs = QgsCoordinateReferenceSystem.fromEpsgId(row[0])
            if crs.isValid():
                return crs
    except (sqlite3.Error, OSError):
        pass
    finally:
        if conn is not None:
            conn.close()
    return None


def export_inp(iface) -> Optional[str]:
    """sync → 构建 WNTR 模型 → 导出为 EPANET INP 文件

    Returns:
        导出的文件路径，失败返回 None
    """
    from ..tools.sync_manager import SyncManager
    from wdrip.simulation import DripSimulation

    # 1. 同步到 DripNetwork（不展开毛管，保留原始管网结构；
    #    split_vertices=True 在折线每个顶点处分割，生成 INP junction）
    sync = SyncManager(iface)
    try:
        net = sync.sync_qgis_to_network(expand=False, split_vertices=True)
    except Exception as e:
        QMessageBox.critical(
            iface.mainWindow(), QApplication.translate("ProjectIo", "aQuaDrip INP 导出"),
            QApplication.translate("ProjectIo", "同步管网失败:\n{0}").format(e))
        return None

    if not net.nodes or not net.links:
        QMessageBox.warning(
            iface.mainWindow(), QApplication.translate("ProjectIo", "aQuaDrip INP 导出"),
            QApplication.translate("ProjectIo", "管网为空，无法导出。请先绘制管道和节点。"))
        return None

    # 2. 选择保存路径
    path, _ = QFileDialog.getSaveFileName(
        iface.mainWindow(),
        QApplication.translate("ProjectIo", "导出 EPANET INP 文件"),
        "",
        "EPANET INP (*.inp);;All Files (*)",
    )
    if not path:
        return None

    # 3. 构建 WNTR 模型
    try:
        sim = DripSimulation(net)
        wn = sim.build_wntr_model()
    except Exception as e:
        QMessageBox.critical(
            iface.mainWindow(), QApplication.translate("ProjectIo", "aQuaDrip INP 导出"),
            QApplication.translate("ProjectIo", "构建 WNTR 模型失败:\n{0}").format(e))
        return None

    # 4. 导出
    try:
        import wntr
        wntr.network.write_inpfile(wn, path)

        # 追加 aQuaDrip 元数据段：保留 pipe_type（EPANET 不支持此概念）
        with open(path, "a") as f:
            f.write("\n[AQD_PIPES]\n")
            f.write(";PipeID    PipeType\n")
            for lid, link in net.links.items():
                ptype = getattr(link, "pipe_type", "mainline")
                f.write(f"{lid}    {ptype}\n")
            f.write("[END]\n")
    except Exception as e:
        QMessageBox.critical(
            iface.mainWindow(), QApplication.translate("ProjectIo", "aQuaDrip INP 导出"),
            QApplication.translate("ProjectIo", "写入 INP 文件失败:\n{0}").format(e))
        return None

    iface.messageBar().pushMessage(
        "aQuaDrip",
        QApplication.translate("ProjectIo", "INP 已导出: {0}（节点 {1}，管道 {2}）").format(os.path.basename(path), len(wn.junction_name_list), len(wn.pipe_name_list)),
        level=0, duration=6)
    return path
