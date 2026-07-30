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
from qgis.PyQt.QtGui import QColor

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
    loaded = 0
    for key in SIGNATURE_LAYERS:
        uri = f"{path}|layername={key}"
        layer = QgsVectorLayer(uri, key, "ogr")
        if not layer.isValid():
            continue
        # 确保 CRS 正确：GPKG 内已存储 SRS，
        # 但某些情况下 QGIS 不会自动激活，此处显式设置
        if not layer.crs().isValid():
            project_crs = project.crs()
            if project_crs.isValid():
                layer.setCrs(project_crs)
        project.addMapLayer(layer)
        loaded += 1

    # 也尝试加载可选的观测点图层
    uri_obs = f"{path}|layername=aqd_obs_points"
    obs = QgsVectorLayer(uri_obs, "aqd_obs_points", "ogr")
    if obs.isValid():
        project.addMapLayer(obs)
        loaded += 1

    iface.messageBar().pushMessage(
        "aQuaDrip",
        f"已加载 {loaded} 个图层（{os.path.basename(path)}）",
        level=0, duration=5)
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
    """选择 .inp → WNTR 解析 → 生成 aQuaDrip 兼容图层（内存图层）

    导入的图层使用 aQuaDrip 字段名和类型，可以直接被 aQuaDrip
    工具（编辑属性、生成交叉节点、运行模拟）识别和编辑。

    Returns:
        True 表示导入成功，False 表示用户取消或解析失败
    """
    path, _ = QFileDialog.getOpenFileName(
        iface.mainWindow(),
        "导入 EPANET INP 文件",
        "",
        "EPANET INP (*.inp);;All Files (*)",
    )
    if not path:
        return False

    # 1. WNTR 读取
    try:
        import wntr
        wn = wntr.network.WaterNetworkModel(path)
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
    aqd_pipe_types = _parse_aqd_section(path)

    if not wn.node_name_list:
        QMessageBox.warning(
            iface.mainWindow(), "aQuaDrip INP 导入",
            "INP 文件中没有节点数据")
        return False

    basename = os.path.splitext(os.path.basename(path))[0]
    crs = QgsProject.instance().crs()
    project = QgsProject.instance()

    # ── 0. 统计节点引用次数（跳过毛管末端叶子节点）──
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

    # ── 节点图层（aQuaDrip 兼容字段）──
    # 跳过叶子节点（只被 1 条管道引用的末端节点），
    # 只保留连接节点（≥2 条管道）和水源节点
    node_layer = QgsVectorLayer(
        f"Point?crs={crs.authid()}", "aqd_nodes", "memory")
    node_provider = node_layer.dataProvider()
    node_provider.addAttributes([
        QgsField("node_type", QVariant.String),
        QgsField("source_type", QVariant.String),
        QgsField("head", QVariant.Double),
        QgsField("available_flow", QVariant.Double),
        QgsField("fertilizer_volume", QVariant.Double),
        QgsField("fertilizer_concentration", QVariant.Double),
        QgsField("elevation", QVariant.Double),
        QgsField("pressure", QVariant.Double),
    ])
    node_layer.updateFields()

    n_added = 0
    for name in wn.node_name_list:
        node = wn.get_node(name)
        if node is None:
            continue
        ntype = type(node).__name__

        # 跳过叶子节点（只被 1 条管道引用，通常是毛管/管段末端）
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

        node_provider.addFeature(feat)
        n_added += 1
    node_layer.updateExtents()
    project.addMapLayer(node_layer)

    # ── 管道图层（aQuaDrip 兼容字段）──
    pipe_layer = QgsVectorLayer(
        f"LineString?crs={crs.authid()}", "aqd_pipes", "memory")
    pipe_provider = pipe_layer.dataProvider()
    pipe_provider.addAttributes([
        QgsField("pipe_type", QVariant.String),
        QgsField("device", QVariant.String),
        QgsField("valve_type", QVariant.String),
        QgsField("status", QVariant.String),
        QgsField("diameter", QVariant.Double),
        QgsField("material", QVariant.String),
        QgsField("length", QVariant.Double),
        QgsField("roughness", QVariant.Double),
        QgsField("pump_head", QVariant.Double),
        QgsField("pump_flow", QVariant.Double),
        QgsField("pump_power", QVariant.Double),
        QgsField("minor_loss", QVariant.Double),
        QgsField("lateral_spacing", QVariant.Double),
        QgsField("emitter_spacing", QVariant.Double),
        QgsField("emitter_k", QVariant.Double),
        QgsField("emitter_x", QVariant.Double),
        QgsField("zone_id", QVariant.Int),
        QgsField("from_node", QVariant.String),
        QgsField("to_node", QVariant.String),
        QgsField("flow", QVariant.Double),
        QgsField("velocity", QVariant.Double),
    ])
    pipe_layer.updateFields()

    p_added = 0
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
            feat.setAttribute("diameter", float(link.diameter) * 1000)  # m→mm
            feat.setAttribute("status", "open")
            feat.setAttribute("material", "PE")

            if hasattr(link, 'length'):
                feat.setAttribute("length", float(link.length))
            if hasattr(link, 'roughness'):
                feat.setAttribute("roughness", float(link.roughness))
            if device == "valve" and hasattr(link, 'valve_type'):
                feat.setAttribute("valve_type", str(link.valve_type))
            if device == "pump":
                feat.setAttribute("pump_head", 0.0)
                feat.setAttribute("pump_flow", 0.0)
                feat.setAttribute("pump_power", 0.0)

            # pipe_type：优先从 [AQD_PIPES] 元数据恢复，
            # 无元数据时按管径启发式推断
            if name in aqd_pipe_types:
                feat.setAttribute("pipe_type", aqd_pipe_types[name])
            else:
                d_mm = float(link.diameter) * 1000
                if device == "pump" or device == "valve":
                    feat.setAttribute("pipe_type", "mainline")
                elif d_mm >= 50:
                    feat.setAttribute("pipe_type", "mainline")
                elif d_mm >= 32:
                    feat.setAttribute("pipe_type", "submain")
                else:
                    feat.setAttribute("pipe_type", "lateral")

            pipe_provider.addFeature(feat)
            p_added += 1

    pipe_layer.updateExtents()
    project.addMapLayer(pipe_layer)

    # ── 简单样式 ──
    _style_inp_layers(node_layer, pipe_layer)

    iface.messageBar().pushMessage(
        "aQuaDrip",
        f"已导入 {basename}.inp（{n_added} 节点, {p_added} 管道）"
        f" — 图层为内存图层，可直接编辑",
        level=0, duration=6)
    return True


def _style_inp_layers(node_layer: QgsVectorLayer, pipe_layer: QgsVectorLayer):
    """简单样式：节点按类型分色，管道按管径线宽"""
    # 节点：按 node_type 分色
    node_layer.renderer().symbol().setSize(2.5)
    # 管道：按管径分线宽（范围映射）
    pipe_layer.renderer().symbol().setWidth(1.0)
    pipe_layer.renderer().symbol().setColor(QColor(0, 120, 200))
