"""ProjectIO — 项目打开 / 另存为 / INP 导出

- is_aquadrip_gpkg(path): 校验 GPKG 是否为 aQuaDrip 项目
- load_layers(iface): 选择 .gpkg → 校验 → 一键加载 4 个图层到 QGIS
- save_project_as(iface): WAL 安全复制 GPKG + 模拟历史 → 重指图层 → 另存 .qgz
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


# 另存为时随迁的数据图层（签名层 + 观测点）
_ALL_AQD_LAYERS = SIGNATURE_LAYERS + ["aqd_obs_points"]


def save_project_as(iface) -> bool:
    """项目另存为：复制 GPKG（WAL 安全）+ 模拟历史 → 重指图层 → 另存 .qgz

    流程：
      1. 定位当前项目 GPKG；未提交的编辑缓冲先确认提交（否则不进副本）
      2. 选目标路径；同名中止，已存在确认覆盖
      3. sqlite backup API 复制 GPKG——读穿 WAL 日志得到一致性快照，
         无需关闭图层（shutil 直接复制会漏 WAL 中未合并的数据）
      4. 随迁 .simhistory.d/ 历史分片目录与旧版 .simhistory 单文件
      5. 图层原地重指 datasource（保留样式/分组/选中），CRS 保持不变
         （部分项目 GPKG 的 srs 元数据损坏，重开后 CRS 会丢，需回填）；
         下游（SimHistory/校准/承压/可视化）经 find_gpkg_path 自动生效
      6. QgsProject.write(新路径.qgz) —— 与新建项目一致，当前会话切换到新工程

    Returns:
        True 另存成功，False 用户取消或失败
    """
    import shutil

    from .layer_utils import find_gpkg_path, find_layer

    src = find_gpkg_path(None, "aqd_fields")
    if not src:
        iface.messageBar().pushWarning(
            "aQuaDrip", QApplication.translate("ProjectIo", "未找到当前项目 GPKG，请先打开或新建项目"))
        return False

    # ── 1. 未提交更改防护：编辑缓冲在 QGIS 内存里，不提交不会进副本 ──
    project = QgsProject.instance()
    dirty = [ly for key in _ALL_AQD_LAYERS
             if (ly := find_layer(project, key)) is not None and ly.isEditable()]
    if dirty:
        ret = QMessageBox.question(
            iface.mainWindow(), "aQuaDrip",
            QApplication.translate("ProjectIo",
                                   "有 {0} 个图层处于编辑状态且可能包含未提交的更改。\n"
                                   "另存为只会复制已提交到 GPKG 的数据。\n\n"
                                   "提交更改并继续？").format(len(dirty)),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return False
        for ly in dirty:
            if not ly.commitChanges():
                iface.messageBar().pushWarning(
                    "aQuaDrip",
                    QApplication.translate("ProjectIo", "图层 {0} 提交失败: {1}").format(
                        ly.name(), "; ".join(ly.commitErrors())))
                return False

    # ── 2. 目标路径 ──
    src_base = src[:-5] if src.endswith(".gpkg") else src
    default = os.path.join(
        os.path.dirname(src),
        os.path.basename(src_base) + "_copy.gpkg")
    dst, _ = QFileDialog.getSaveFileName(
        iface.mainWindow(),
        QApplication.translate("ProjectIo", "项目另存为"),
        default, "GeoPackage (*.gpkg)")
    if not dst:
        return False
    if not dst.endswith(".gpkg"):
        dst += ".gpkg"
    dst = os.path.abspath(dst)
    if dst == os.path.abspath(src):
        iface.messageBar().pushWarning(
            "aQuaDrip", QApplication.translate("ProjectIo", "目标路径与当前项目相同，已取消"))
        return False
    dst_base = dst[:-5]
    dst_qgz = dst_base + ".qgz"

    # 目标已存在 → 确认覆盖（连带清理旧 sidecar）
    if os.path.exists(dst) or os.path.exists(dst_qgz) \
            or os.path.exists(dst_base + ".simhistory.d"):
        ret = QMessageBox.question(
            iface.mainWindow(), "aQuaDrip",
            QApplication.translate("ProjectIo",
                                   "目标已存在，覆盖？\n{0}").format(dst),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return False
        for p in (dst, dst_qgz):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        try:
            if os.path.exists(dst_base + ".simhistory.d"):
                shutil.rmtree(dst_base + ".simhistory.d")
        except OSError:
            pass

    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)

    # ── 3. WAL 安全复制 GPKG（sqlite backup 读穿 WAL，一致性快照） ──
    created = []  # 半成品清理清单
    try:
        src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        try:
            dst_conn = sqlite3.connect(dst)
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
        finally:
            src_conn.close()
        created.append(dst)

        if not is_aquadrip_gpkg(dst):
            raise ValueError(QApplication.translate("ProjectIo", "复制后的 GPKG 完整性校验失败"))

        # ── 4. 随迁模拟历史 ──
        n_hist = 0
        src_dir = src_base + ".simhistory.d"
        if os.path.isdir(src_dir):
            shutil.copytree(src_dir, dst_base + ".simhistory.d")
            created.append(dst_base + ".simhistory.d")
            try:
                with open(os.path.join(dst_base + ".simhistory.d", "index.json"),
                          encoding="utf-8") as f:
                    import json
                    n_hist = len(json.load(f).get("records", []))
            except (OSError, ValueError):
                pass
        src_legacy = src_base + ".simhistory"
        if os.path.isfile(src_legacy):
            shutil.copy2(src_legacy, dst_base + ".simhistory")
            created.append(dst_base + ".simhistory")

        # ── 5. 图层原地重指 datasource（保留样式/分组/选中） ──
        # 按 source 路径匹配（而非按图层名）：覆盖用户重命名的图层、
        # 以及同一路径被多次加载产生的重复图层——全部指向新文件
        remapped = 0
        for ly in list(project.mapLayers().values()):
            if not isinstance(ly, QgsVectorLayer):
                continue
            src_uri = ly.source() or ""
            try:
                same_file = os.path.abspath(src_uri.split("|")[0]) \
                    == os.path.abspath(src)
            except (OSError, ValueError):
                continue
            if not same_file:
                continue
            key = None
            for part in src_uri.split("|"):
                if part.startswith("layername="):
                    key = part[len("layername="):]
            if not key:
                continue
            old_crs = ly.crs()
            ly.setDataSource(f"{dst}|layername={key}", ly.name(), "ogr")
            # 部分 GPKG 的 srs 元数据损坏（如手工修复过的项目），
            # 重开后 CRS 会失效——数据没变，回填原 CRS
            if old_crs is not None and old_crs.isValid():
                ly.setCrs(old_crs)
            ly.triggerRepaint()
            remapped += 1

        # ── 6. 另存 .qgz 并切换当前会话 ──
        if not project.write(dst_qgz):
            raise ValueError(QApplication.translate("ProjectIo", "写入工程文件失败: {0}").format(dst_qgz))
        created.append(dst_qgz)

    except Exception as e:
        # 失败清理半成品，当前项目图层不动
        for p in created:
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p)
                elif os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        import traceback
        traceback.print_exc()
        iface.messageBar().pushWarning(
            "aQuaDrip",
            QApplication.translate("ProjectIo", "另存为失败: {0}").format(e))
        return False

    iface.messageBar().pushMessage(
        "aQuaDrip",
        QApplication.translate("ProjectIo",
                               "项目已另存为: {0}（图层 {1} 个，模拟历史 {2} 条）").format(
                                   dst, remapped, n_hist),
        level=0, duration=8)
    return True


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
