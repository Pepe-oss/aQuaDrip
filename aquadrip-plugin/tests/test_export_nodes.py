# -*- coding: utf-8 -*-
"""节点矢量导出测试:三格式字段值/NULL 语义/is_emitter/CRS 兜底

覆盖:
- GPKG/GeoJSON/Shapefile 三种格式的要素数与字段值一致
- 字段名 ≤10 字符(Shapefile 不截断,三格式字段一致)
- is_emitter 区分「滴头流量 0」与「非滴头 NULL」
- 空记录报错;results_nodes 临时图层同源(pressure_m/is_emitter)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bootstrap import init_qgis, IF, LOGS

app, canvas = init_qgis()
IFi = IF()

from qgis.core import QgsVectorLayer
from tools.visualize import Visualizer

ok = True


def check(name, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        ok = False


record = {
    "node_pressure": {"N1": 10.5, "N2": 8.2, "E_L1_001": 9.1, "N9": 5.0},
    "emitter_flow": {"E_L1_001": 1.52, "E_L1_002": 1.48},
    "node_coords": {"N1": [111.0, 41.0], "N2": [111.001, 41.0],
                    "E_L1_001": [111.0, 41.001], "E_L1_002": [111.001, 41.001]},
}
viz = Visualizer(IFi)

OUT = os.path.join(os.environ.get("TMPDIR", "/tmp"), "exp_nodes_test")
for ext in (".gpkg", ".geojson", ".shp"):
    out = OUT + ext
    if os.path.exists(out):
        os.remove(out)
    n = viz.export_nodes(record, out)
    ly = QgsVectorLayer(out, "t", "ogr")
    check(f"{ext[1:]}: 写出节点数=图层要素数", ly.isValid() and ly.featureCount() == n)
    feats = {f["node_id"]: f for f in ly.getFeatures()}
    check(f"{ext[1:]}: N1 压力/无滴头流量",
          abs(feats["N1"]["pressure_m"] - 10.5) < 1e-9 and not feats["N1"]["emit_flow"])
    check(f"{ext[1:]}: E_L1_001 压力+滴头流量",
          abs(feats["E_L1_001"]["pressure_m"] - 9.1) < 1e-9
          and abs(feats["E_L1_001"]["emit_flow"] - 1.52) < 1e-9)
    check(f"{ext[1:]}: E_L1_002 仅滴头流量",
          not feats["E_L1_002"]["pressure_m"]
          and abs(feats["E_L1_002"]["emit_flow"] - 1.48) < 1e-9)
    check(f"{ext[1:]}: 缺坐标 N9 被跳过", "N9" not in feats)
    check(f"{ext[1:]}: is_emitter 滴头=1 接点=0",
          feats["N1"]["is_emitter"] == 0 and feats["E_L1_001"]["is_emitter"] == 1
          and feats["E_L1_002"]["is_emitter"] == 1)

# CRS 兜底(空项目 → 4326)
ly = QgsVectorLayer(OUT + ".gpkg", "t", "ogr")
check("CRS 兜底 EPSG:4326", ly.crs().authid() == "EPSG:4326")

# 空记录报错
try:
    viz.export_nodes({"node_pressure": {}, "emitter_flow": {}, "node_coords": {}},
                     OUT + "_x.gpkg")
    check("空记录 raises ValueError", False)
except ValueError:
    check("空记录 raises ValueError", True)

# results_nodes 临时图层同源(含 pressure_m 与 is_emitter 字段)
nl = viz._create_node_layer(record, "EPSG:4326", "pressure")
names = nl.fields().names()
check("results_nodes 含 pressure_m 字段", "pressure_m" in names and "pressure_mpa" in names)
check("results_nodes 含 is_emitter 字段", "is_emitter" in names)

for ext in (".gpkg", ".geojson", ".shp"):
    p = OUT + ext
    if os.path.exists(p):
        os.remove(p)

print()
print("ALL OK" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
