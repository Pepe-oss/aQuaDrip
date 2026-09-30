# -*- coding: utf-8 -*-
"""项目另存为测试:WAL 安全复制/历史随迁/图层重指/边界路径

覆盖:
- sqlite backup API 读穿 WAL(不关闭图层拿到一致性快照)
- .simhistory.d/ 分片目录随迁
- 图层按 source 路径匹配原地重指(含重复图层),name/CRS 保持
- 同路径中止 / 无项目警告 边界
"""
import os, sys, shutil, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bootstrap import init_qgis, IF, LOGS

app, canvas = init_qgis()
IFi = IF()

from qgis.core import (QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
                       QgsPointXY, QgsField, QgsCoordinateReferenceSystem)
from qgis.PyQt.QtCore import QVariant
from tools.layer_setup import LayerSetupAction
from tools.sim_history import SimHistory
from tools.project_io import save_project_as, is_aquadrip_gpkg
from tools.layer_utils import find_gpkg_path
import qgis.PyQt.QtWidgets as QW

# stub 文件对话框与确认框
TARGET = {"path": ""}
QW.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (TARGET["path"], ""))
QW.QMessageBox.question = staticmethod(lambda *a, **k: QW.QMessageBox.Yes)

ok = True


def check(name, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        ok = False


TMP = os.path.join(os.environ.get("TMPDIR", "/tmp"), "aqd_saveas_test")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)
SRC = os.path.join(TMP, "proj.gpkg")
lsa = LayerSetupAction(IFi)
lsa.setup_layers(SRC, target_crs=QgsCoordinateReferenceSystem("EPSG:4326"))

proj = QgsProject.instance()
layer_keys = ["aqd_fields", "aqd_pipes", "aqd_pumps", "aqd_valves", "aqd_nodes", "aqd_obs_points"]
for k in layer_keys:
    ly = QgsVectorLayer(f"{SRC}|layername={k}", k, "ogr")
    ly.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    proj.addMapLayer(ly)

fl = QgsProject.instance().mapLayersByName("aqd_fields")[0]
fl.startEditing()
f = QgsFeature(fl.fields())
f.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(111, 41), QgsPointXY(111.001, 41),
                                          QgsPointXY(111.001, 41.001), QgsPointXY(111, 41)]]))
f.setAttribute("crop_type", "maize")
fl.addFeature(f)
fl.commitChanges()

# WAL 场景:保持一个写连接不关,数据只进 -wal 文件
wal_conn = sqlite3.connect(SRC)
wal_conn.execute("PRAGMA journal_mode=WAL")
wal_conn.execute("UPDATE aqd_fields SET crop_type='wal_only_marker' WHERE fid=1")
wal_conn.commit()

# 写 2 条模拟历史
h = SimHistory(SRC)
h.add(cu=90, du=85, node_pressure={"N1": 1.0}, link_flow={}, link_velocity={},
      emitter_flow={}, node_coords={"N1": [111.0, 41.0]}, message="t1")
h.add(cu=91, du=86, node_pressure={"N1": 1.1}, link_flow={}, link_velocity={},
      emitter_flow={}, node_coords={"N1": [111.0, 41.0]}, message="t2")

# ── 执行另存为 ──
TARGET["path"] = os.path.join(TMP, "proj_copy.gpkg")
LOGS.clear()
ret = save_project_as(IFi)
check("另存为返回 True", ret is True)
check("无失败警告", all(m[0] != "warn" for m in LOGS), str(LOGS[-1] if LOGS else ""))

DST = TARGET["path"]
DST_BASE = DST[:-5]
check("新 GPKG 存在且签名校验通过", os.path.exists(DST) and is_aquadrip_gpkg(DST))
check("新 .qgz 存在", os.path.exists(DST_BASE + ".qgz"))

c = sqlite3.connect(f"file:{DST}?mode=ro", uri=True)
row = c.execute("SELECT crop_type FROM aqd_fields WHERE fid=1").fetchone()
c.close()
check("WAL 未合并数据在副本中", row and row[0] == "wal_only_marker", str(row))

h2 = SimHistory(DST)
check("历史 2 条随迁", h2.count == 2)

check("find_gpkg_path → 新路径", find_gpkg_path(None, "aqd_fields") == DST,
      find_gpkg_path(None, "aqd_fields"))
ly = proj.mapLayersByName("aqd_fields")[0]
check("图层 name 保持 aqd_fields", ly.name() == "aqd_fields")
check("图层 CRS 保持 4326", ly.crs().authid() == "EPSG:4326", ly.crs().authid())
stale = [l.name() for l in proj.mapLayers().values()
         if os.path.abspath((l.source() or "").split("|")[0]) == os.path.abspath(SRC)]
check("全部图层 source 指向新文件", not stale, f"残留: {stale}")

c = sqlite3.connect(f"file:{SRC}?mode=ro", uri=True)
row = c.execute("SELECT crop_type FROM aqd_fields WHERE fid=1").fetchone()
c.close()
check("源项目数据未变", row and row[0] == "wal_only_marker", str(row))
check("源历史目录仍在", os.path.isdir(SRC[:-5] + ".simhistory.d"))
wal_conn.close()

# ── 边界:同路径 → 取消 ──
TARGET["path"] = DST
LOGS.clear()
ret = save_project_as(IFi)
check("同路径 → False+警告", ret is False and any("相同" in m[1] for m in LOGS if m[0] == "warn"))

# ── 边界:无项目(移除全部相关图层后) ──
for lid, l in list(proj.mapLayers().items()):
    if os.path.abspath((l.source() or "").split("|")[0]) in (os.path.abspath(SRC), os.path.abspath(DST)):
        proj.removeMapLayer(lid)
LOGS.clear()
ret = save_project_as(IFi)
check("无项目 → False+警告", ret is False and any("GPKG" in m[1] for m in LOGS if m[0] == "warn"))

shutil.rmtree(TMP, ignore_errors=True)
print()
print("ALL OK" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
