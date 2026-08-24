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
        QApplication.translate("ProjectIo", "导入 EPANET INP 文件"),
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
            iface.mainWindow(), QApplication.translate("ProjectIo", "aQuaDrip INP 导入"),
            QApplication.translate("ProjectIo", "WNTR 未安装。请运行: pip install wntr"))
        return False
    except Exception as e:
        QMessageBox.critical(
            iface.mainWindow(), QApplication.translate("ProjectIo", "aQuaDrip INP 导入"),
            QApplication.translate("ProjectIo", "INP 文件解析失败:\n{0}").format(e))
        return False

    # 1.5 读取 aQuaDrip 元数据段（pipe_type 恢复）
    aqd_pipe_types = _parse_aqd_section(inp_path)

    if not wn.node_name_list:
        QMessageBox.warning(
            iface.mainWindow(), QApplication.translate("ProjectIo", "aQuaDrip INP 导入"),
            QApplication.translate("ProjectIo", "INP 文件中没有节点数据"))
        return False

    # 2. 选择 GPKG 输出路径
    basename = os.path.splitext(os.path.basename(inp_path))[0]
    default_gpkg = os.path.join(
        os.path.dirname(inp_path), f"{basename}.gpkg")
    gpkg_path, _ = QFileDialog.getSaveFileName(
        iface.mainWindow(),
        QApplication.translate("ProjectIo", "选择 aQuaDrip 项目保存位置"),
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
            iface.mainWindow(), QApplication.translate("ProjectIo", "aQuaDrip INP 导入"),
            QApplication.translate("ProjectIo", "创建 GPKG 失败: {0}").format(gpkg_path))
        return False

    # 4. 找到刚创建的图层，写入 INP 数据
    project = QgsProject.instance()

    # ── 4.1 写入节点 ──
    # 所有节点（含毛管末端叶子节点）都写入 aqd_nodes，保证管道的
    # from_node/to_node 引用完整。之前跳过 refs<=1 的叶子节点会导致
    # 其管道端点坐标已写入但节点缺失，下次 sync 变成 auto_N，
    # 重新导入的 INP 不再是干净的 apd 图层。
    node_layer = _find_project_layer(project, "aqd_nodes")
    n_added = 0
    if node_layer:
        node_layer.startEditing()
        try:
            for name in wn.node_name_list:
                node = wn.get_node(name)
                if node is None:
                    continue
                ntype = type(node).__name__

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
        except Exception:
            node_layer.rollBack()
            raise
        else:
            if not node_layer.commitChanges():
                node_layer.rollBack()
                iface.messageBar().pushWarning(
                    "aQuaDrip", QApplication.translate("ProjectIo", "节点图层提交失败"))

    # ── 4.2 写入管道 ──
    pipe_layer = _find_project_layer(project, "aqd_pipes")
    p_added = 0
    if pipe_layer:
        pipe_layer.startEditing()
        try:
            for name in wn.pipe_name_list:
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
                feat.setAttribute("from_node", link.start_node_name)
                feat.setAttribute("to_node", link.end_node_name)
                feat.setAttribute("diameter", float(link.diameter) * 1000)
                feat.setAttribute("status", "open")
                feat.setAttribute("material", "PE")
                if hasattr(link, 'roughness'):
                    feat.setAttribute("roughness", float(link.roughness))

                # pipe_type：优先从 [AQD_PIPES] 元数据恢复
                if name in aqd_pipe_types:
                    feat.setAttribute("pipe_type", aqd_pipe_types[name])
                else:
                    d_mm = float(link.diameter) * 1000
                    if d_mm >= 50:
                        feat.setAttribute("pipe_type", "mainline")
                    elif d_mm >= 32:
                        feat.setAttribute("pipe_type", "submain")
                    else:
                        feat.setAttribute("pipe_type", "lateral")

                pipe_layer.addFeature(feat)
                p_added += 1
        except Exception:
            pipe_layer.rollBack()
            raise
        else:
            if not pipe_layer.commitChanges():
                pipe_layer.rollBack()
                iface.messageBar().pushWarning(
                    "aQuaDrip", QApplication.translate("ProjectIo", "管道图层提交失败"))

    # ── 4.3 写入水泵 ──
    pump_layer = _find_project_layer(project, "aqd_pumps")
    if pump_layer:
        pump_layer.startEditing()
        try:
            for name in wn.pump_name_list:
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

                feat = QgsFeature(pump_layer.fields())
                feat.setGeometry(QgsGeometry.fromPolylineXY([
                    QgsPointXY(float(fc[0]), float(fc[1])),
                    QgsPointXY(float(tc[0]), float(tc[1])),
                ]))
                feat.setAttribute("from_node", link.start_node_name)
                feat.setAttribute("to_node", link.end_node_name)
                feat.setAttribute("diameter", float(link.diameter) * 1000)
                feat.setAttribute("status", "open")
                # 提取 INP 中的泵参数：POWER 模式取功率，HEAD 模式取
                # Q-H 曲线设计点（中间点）——原先全部清零会丢失数据
                p_head, p_flow, p_power = 0.0, 0.0, 0.0
                try:
                    if str(getattr(link, 'pump_type', '')).upper() == 'POWER':
                        p_power = float(link.power or 0.0)
                    else:
                        cname = getattr(link, 'pump_curve_name', None)
                        curve = wn.get_curve(cname) if cname else None
                        if curve is not None and len(curve.points) > 0:
                            pts = curve.points  # [(flow m³/s, head m)]
                            fq, fh = pts[len(pts) // 2]
                            p_flow = float(fq) * 3600.0  # m³/s → m³/h
                            p_head = float(fh)
                except Exception:
                    pass
                feat.setAttribute("pump_head", p_head)
                feat.setAttribute("pump_flow", p_flow)
                feat.setAttribute("pump_power", p_power)
                p_added += 1
                pump_layer.addFeature(feat)
        except Exception:
            pump_layer.rollBack()
            raise
        else:
            if not pump_layer.commitChanges():
                pump_layer.rollBack()
                iface.messageBar().pushWarning(
                    "aQuaDrip", QApplication.translate("ProjectIo", "水泵图层提交失败"))

    # ── 4.4 写入阀门 ──
    valve_layer = _find_project_layer(project, "aqd_valves")
    if valve_layer:
        valve_layer.startEditing()
        try:
            for name in wn.valve_name_list:
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

                feat = QgsFeature(valve_layer.fields())
                feat.setGeometry(QgsGeometry.fromPolylineXY([
                    QgsPointXY(float(fc[0]), float(fc[1])),
                    QgsPointXY(float(tc[0]), float(tc[1])),
                ]))
                feat.setAttribute("from_node", link.start_node_name)
                feat.setAttribute("to_node", link.end_node_name)
                feat.setAttribute("diameter", float(link.diameter) * 1000)
                feat.setAttribute("status", "open")
                if hasattr(link, 'valve_type'):
                    feat.setAttribute("valve_type", str(link.valve_type))
                else:
                    feat.setAttribute("valve_type", "GATE")
                # setting=0 会把阀门当全关处理直接阻断水流：
                # 优先用 INP 中的 setting，缺失时回退字段默认值 10
                setting = 10.0
                try:
                    s = float(getattr(link, 'setting', 0) or 0)
                    if s > 0:
                        setting = s
                except (TypeError, ValueError):
                    pass
                feat.setAttribute("setting", setting)
                p_added += 1
                valve_layer.addFeature(feat)
        except Exception:
            valve_layer.rollBack()
            raise
        else:
            if not valve_layer.commitChanges():
                valve_layer.rollBack()
                iface.messageBar().pushWarning(
                    "aQuaDrip", QApplication.translate("ProjectIo", "阀门图层提交失败"))

    iface.messageBar().pushMessage(
        "aQuaDrip",
        QApplication.translate("ProjectIo", "已导入 {0}.inp（{1} 节点, {2} 管道） → {3}").format(basename, n_added, p_added, os.path.basename(gpkg_path)),
        level=0, duration=8)
    return True


def _find_project_layer(project: QgsProject, key: str):
    """从已加载项目图层中查找（按 name 或 source 匹配）"""
    from .layer_utils import find_layer
    return find_layer(project, key)
