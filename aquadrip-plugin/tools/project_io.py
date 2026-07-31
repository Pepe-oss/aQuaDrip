"""ProjectIO — 项目打开 / INP 处理

- is_aquadrip_gpkg(path): 校验 GPKG 是否为 aQuaDrip 项目
- load_layers(iface): 选择 .gpkg → 校验 → 一键加载 4 个图层到 QGIS
- export_inp(iface): sync → 构建 WNTR 模型 → write_inpfile()
- import_inp(iface): 选择 .inp → WNTR 解析 → 生成临时矢量图层
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

# 必须是这些图层中的核心三层才算 aQuaDrip 项目
SIGNATURE_LAYERS = ["aqd_fields", "aqd_pipes", "aqd_nodes"]

# 核心字段检查（每个签名图层至少包含以下字段之一）
SIGNATURE_FIELDS = {
    "aqd_fields": ["planting_pattern", "emitter_spacing"],
    "aqd_pipes": ["pipe_type", "diameter"],
    "aqd_nodes": ["node_type", "elevation"],
}


def is_aquadrip_gpkg(path: str) -> bool:
    """校验 GPKG 是否包含 aQuaDrip 项目的签名图层和字段"""
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        # 检查 gpkg_contents 中的图层
        cur.execute("SELECT table_name FROM gpkg_contents")
        tables = {row[0] for row in cur.fetchall()}
        for sig in SIGNATURE_LAYERS:
            if sig not in tables:
                conn.close()
                return False
        # 检查每个签名图层的字段
        for sig in SIGNATURE_LAYERS:
            cur.execute(f"PRAGMA table_info(\"{sig}\")")
            columns = {row[1] for row in cur.fetchall()}
            if not any(f in columns for f in SIGNATURE_FIELDS[sig]):
                conn.close()
                return False
        conn.close()
        return True
    except (sqlite3.Error, OSError):
        return False


def load_layers(iface) -> bool:
    """打开 QFileDialog → 校验 aQuaDrip GPKG → 加载图层到 QGIS 项目

    Returns:
        True 表示加载成功，False 表示用户取消或校验失败
    """
    path, _ = QFileDialog.getOpenFileName(
        iface.mainWindow(),
        "打开 aQuaDrip 项目",
        "",
        "GeoPackage (*.gpkg);;All Files (*)",
    )
    if not path:
        return False

    if not is_aquadrip_gpkg(path):
        QMessageBox.warning(
            iface.mainWindow(),
            "aQuaDrip",
            f"该文件不是 aQuaDrip 项目 GPKG：\n{path}\n\n"
            f"aQuaDrip 项目必须包含 {', '.join(SIGNATURE_LAYERS)} 图层。")
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
            f"项目 CRS 已设为 {gpkg_crs.authid()}（来自 GPKG）",
            level=0, duration=4)

    iface.messageBar().pushMessage(
        "aQuaDrip",
        f"已加载 {loaded} 个图层（{os.path.basename(path)}）",
        level=0, duration=5)
    return True


def _read_gpkg_crs(path: str):
    """从 GPKG 的 gpkg_contents/gpkg_spatial_ref_sys 读取 CRS

    OGR 加载时空图层可能不自动识别 CRS，这里直接从元数据表读取。
    """
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute(
            "SELECT srs_id FROM gpkg_contents "
            "WHERE srs_id IS NOT NULL LIMIT 1")
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            from qgis.core import QgsCoordinateReferenceSystem
            crs = QgsCoordinateReferenceSystem.fromEpsgId(row[0])
            if crs.isValid():
                return crs
    except (sqlite3.Error, OSError):
        pass
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
            iface.mainWindow(), "aQuaDrip INP 导出",
            f"同步管网失败:\n{e}")
        return None

    if not net.nodes or not net.links:
        QMessageBox.warning(
            iface.mainWindow(), "aQuaDrip INP 导出",
            "管网为空，无法导出。请先绘制管道和节点。")
        return None

    # 2. 选择保存路径
    path, _ = QFileDialog.getSaveFileName(
        iface.mainWindow(),
        "导出 EPANET INP 文件",
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
            iface.mainWindow(), "aQuaDrip INP 导出",
            f"构建 WNTR 模型失败:\n{e}")
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
            iface.mainWindow(), "aQuaDrip INP 导出",
            f"写入 INP 文件失败:\n{e}")
        return None

    iface.messageBar().pushMessage(
        "aQuaDrip",
        f"INP 已导出: {os.path.basename(path)}"
        f"（节点 {len(wn.junction_name_list)}，管道 {len(wn.pipe_name_list)}）",
        level=0, duration=6)
    return path


def _parse_aqd_section(path: str) -> dict:
    """从 INP 文件读取 [AQD_PIPES] 自定义段，恢复 pipe_type

    Returns:
        {pipe_id: pipe_type}，文件无此段时返回空字典
    """
    result = {}
    try:
        in_section = False
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line == "[AQD_PIPES]":
                    in_section = True
                    continue
                if in_section:
                    if line.startswith("["):
                        break  # 遇到下一个段，结束
                    if not line or line.startswith(";"):
                        continue  # 跳过空行和注释
                    parts = line.split()
                    if len(parts) >= 2:
                        result[parts[0]] = parts[1]
    except OSError:
        pass
    return result


def import_inp(iface) -> bool:
    """选择 .inp → WNTR 解析 → 创建标准 aQuaDrip GPKG 项目

    先用 LayerSetupAction 创建标准 GPKG（含完整字段/CRS/元数据），
    再把 INP 数据写入。导入后是真正的 aQuaDrip 项目，可被所有工具编辑。

    Returns:
        True 表示导入成功，False 表示用户取消或解析失败
    """
    inp_path, _ = QFileDialog.getOpenFileName(
        iface.mainWindow(),
        "导入 EPANET INP 文件",
        "",
        "EPANET INP (*.inp);;All Files (*)",
    )
    if not inp_path:
        return False

    # 1. WNTR 读取
    try:
        import wntr
        wn = wntr.network.WaterNetworkModel(inp_path)
    except ImportError:
        QMessageBox.critical(
            iface.mainWindow(), "aQuaDrip INP 导入",
            "WNTR 未安装。请运行: pip install wntr")
        return False
    except Exception as e:
        QMessageBox.critical(
            iface.mainWindow(), "aQuaDrip INP 导入",
            f"INP 文件解析失败:\n{e}")
        return False

    # 1.5 读取 aQuaDrip 元数据段（pipe_type 恢复）
    aqd_pipe_types = _parse_aqd_section(inp_path)

    if not wn.node_name_list:
        QMessageBox.warning(
            iface.mainWindow(), "aQuaDrip INP 导入",
            "INP 文件中没有节点数据")
        return False

    # 2. 选择 GPKG 输出路径
    basename = os.path.splitext(os.path.basename(inp_path))[0]
    default_gpkg = os.path.join(
        os.path.dirname(inp_path), f"{basename}.gpkg")
    gpkg_path, _ = QFileDialog.getSaveFileName(
        iface.mainWindow(),
        "选择 aQuaDrip 项目保存位置",
        default_gpkg,
        "GeoPackage (*.gpkg);;All Files (*)",
    )
    if not gpkg_path:
        return False

    # 3. 创建标准 aQuaDrip GPKG 项目（复用 layer_setup 的完整建表逻辑）
    from .layer_setup import LayerSetupAction
    setup = LayerSetupAction(iface)
    if not setup.setup_layers(gpkg_path):
        QMessageBox.critical(
            iface.mainWindow(), "aQuaDrip INP 导入",
            f"创建 GPKG 失败: {gpkg_path}")
        return False

    # 4. 找到刚创建的图层，写入 INP 数据
    project = QgsProject.instance()

    # ── 4.1 统计节点引用次数（跳过毛管末端叶子节点）──
    node_refs = {}
    for link_list in [wn.pipe_name_list, wn.pump_name_list, wn.valve_name_list]:
        for name in link_list:
            link = wn.get_link(name)
            if link is None:
                continue
            node_refs[link.start_node_name] = \
                node_refs.get(link.start_node_name, 0) + 1
            node_refs[link.end_node_name] = \
                node_refs.get(link.end_node_name, 0) + 1

    # ── 4.2 写入节点 ──
    node_layer = _find_project_layer(project, "aqd_nodes")
    n_added = 0
    if node_layer:
        node_layer.startEditing()
        for name in wn.node_name_list:
            node = wn.get_node(name)
            if node is None:
                continue
            ntype = type(node).__name__

            # 跳过叶子节点（只被 1 条管道引用的末端）
            refs = node_refs.get(name, 0)
            if ntype != "Reservoir" and refs <= 1:
                continue

            coords = getattr(node, 'coordinates', (0, 0))
            if coords is None or len(coords) < 2:
                continue

            feat = QgsFeature(node_layer.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(
                QgsPointXY(float(coords[0]), float(coords[1]))))

            if ntype == "Reservoir":
                feat.setAttribute("node_type", "source")
                feat.setAttribute("head", float(node.base_head))
                feat.setAttribute("source_type", "reservoir")
            elif ntype == "Junction":
                feat.setAttribute("node_type", "junction")
                feat.setAttribute("elevation", float(node.elevation))
            elif ntype == "Tank":
                feat.setAttribute("node_type", "junction")
                feat.setAttribute("elevation", float(node.elevation))
            else:
                feat.setAttribute("node_type", "junction")

            node_layer.addFeature(feat)
            n_added += 1
        node_layer.commitChanges()

    # ── 4.3 写入管道 ──
    pipe_layer = _find_project_layer(project, "aqd_pipes")
    p_added = 0
    if pipe_layer:
        pipe_layer.startEditing()
        for link_list, device in [
            (wn.pipe_name_list, "none"),
            (wn.pump_name_list, "pump"),
            (wn.valve_name_list, "valve"),
        ]:
            for name in link_list:
                link = wn.get_link(name)
                if link is None:
                    continue
                from_node = wn.get_node(link.start_node_name)
                to_node = wn.get_node(link.end_node_name)
                if from_node is None or to_node is None:
                    continue
                fc = getattr(from_node, 'coordinates', (0, 0))
                tc = getattr(to_node, 'coordinates', (0, 0))
                if fc is None or tc is None or len(fc) < 2 or len(tc) < 2:
                    continue

                feat = QgsFeature(pipe_layer.fields())
                feat.setGeometry(QgsGeometry.fromPolylineXY([
                    QgsPointXY(float(fc[0]), float(fc[1])),
                    QgsPointXY(float(tc[0]), float(tc[1])),
                ]))
                feat.setAttribute("device", device)
                feat.setAttribute("from_node", link.start_node_name)
                feat.setAttribute("to_node", link.end_node_name)
                feat.setAttribute("diameter", float(link.diameter) * 1000)
                feat.setAttribute("status", "open")
                feat.setAttribute("material", "PE")
                # aqd_pipes 无 length 字段（长度由几何自动计算）
                if hasattr(link, 'roughness'):
                    feat.setAttribute("roughness", float(link.roughness))
                if device == "valve" and hasattr(link, 'valve_type'):
                    feat.setAttribute("valve_type", str(link.valve_type))
                if device == "pump":
                    feat.setAttribute("pump_head", 0.0)
                    feat.setAttribute("pump_flow", 0.0)
                    feat.setAttribute("pump_power", 0.0)

                # pipe_type：优先从 [AQD_PIPES] 元数据恢复
                if name in aqd_pipe_types:
                    feat.setAttribute("pipe_type", aqd_pipe_types[name])
                else:
                    d_mm = float(link.diameter) * 1000
                    if device in ("pump", "valve"):
                        feat.setAttribute("pipe_type", "mainline")
                    elif d_mm >= 50:
                        feat.setAttribute("pipe_type", "mainline")
                    elif d_mm >= 32:
                        feat.setAttribute("pipe_type", "submain")
                    else:
                        feat.setAttribute("pipe_type", "lateral")

                pipe_layer.addFeature(feat)
                p_added += 1
        pipe_layer.commitChanges()

    iface.messageBar().pushMessage(
        "aQuaDrip",
        f"已导入 {basename}.inp（{n_added} 节点, {p_added} 管道）"
        f" → {os.path.basename(gpkg_path)}",
        level=0, duration=8)
    return True


def _find_project_layer(project: QgsProject, key: str):
    """从已加载项目图层中查找（按 name 或 source 匹配）"""
    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        s = layer.source() if hasattr(layer, "source") else ""
        if key in s or layer.name() == key:
            return layer
    return None
