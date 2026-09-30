# -*- coding: utf-8 -*-
"""分区工具测试:单阀细分/手动标签/多阀合并/按流量编组/轮灌联动

覆盖通用分区原语:
- 分区 = 同标签阀门集合等价类;管道归属 = 下游子树并集
- 下游侧按水源可达性判定(与画线/存储方向无关,含反向画线回归)
- 轮灌调度按 zone 字符串分组:同标签多阀 = 一个轮灌组同开
"""
import os, sys, math, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bootstrap import init_qgis, IF, LOGS

app, canvas = init_qgis()
IFi = IF()

from qgis.core import (QgsProject, QgsFeature, QgsGeometry, QgsPointXY,
                       QgsCoordinateReferenceSystem)
from tools.layer_setup import LayerSetupAction
from tools.layer_utils import find_layer
from tools.zone_divider import ZoneDivider
from tools.rotation_scheduler import RotationScheduler
from collections import Counter

ok = True


def check(name, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        ok = False


# ── 建测试项目:3 条带阀门的支管,每条 支管+3 毛管 ──
TMP = os.path.join(os.environ.get("TMPDIR", "/tmp"), "aqd_zone_test")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)
GPKG = os.path.join(TMP, "proj.gpkg")
lsa = LayerSetupAction(IFi)
lsa.setup_layers(GPKG, target_crs=QgsCoordinateReferenceSystem("EPSG:4326"))

proj = QgsProject.instance()
layers = {}
for k in ["aqd_fields", "aqd_pipes", "aqd_pumps", "aqd_valves", "aqd_nodes", "aqd_obs_points"]:
    ly = find_layer(proj, k)   # setup_layers 已加入项目(名为 Fields/Valves 等)
    assert ly is not None, k
    ly.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    layers[k] = ly


def add(layer, geom, attrs):
    layer.startEditing()
    f = QgsFeature(layer.fields())
    f.setGeometry(geom)
    for k, v in attrs.items():
        f.setAttribute(k, v)
    layer.addFeature(f)
    layer.commitChanges()


M = 1.0 / (111320.0 * math.cos(math.radians(41.0)))
add(layers["aqd_nodes"], QgsGeometry.fromPointXY(QgsPointXY(111.0, 41.0)),
    {"node_type": "source", "head": 20})
add(layers["aqd_pipes"],
    QgsGeometry.fromPolylineXY([QgsPointXY(111.0, 41.0), QgsPointXY(111.0 + 300 * M, 41.0)]),
    {"pipe_type": "mainline", "diameter": 110})
for i, xm in enumerate([100, 200, 300]):
    x0 = 111.0 + xm * M
    if i == 2:
        # 第三条带阀门反着画(支管侧→干管侧):下游判定不依赖存储方向
        vg = QgsGeometry.fromPolylineXY([QgsPointXY(x0, 41.0 + 5 * M), QgsPointXY(x0, 41.0)])
    else:
        vg = QgsGeometry.fromPolylineXY([QgsPointXY(x0, 41.0), QgsPointXY(x0, 41.0 + 5 * M)])
    add(layers["aqd_valves"], vg,
        {"valve_type": "PRV", "status": "open", "diameter": 110, "setting": 20})
    add(layers["aqd_pipes"],
        QgsGeometry.fromPolylineXY([QgsPointXY(x0, 41.0 + 5 * M), QgsPointXY(x0, 41.0 + 95 * M)]),
        {"pipe_type": "submain", "diameter": 110})
    for ym in [30, 55, 80]:
        add(layers["aqd_pipes"],
            QgsGeometry.fromPolylineXY([QgsPointXY(x0, 41.0 + ym * M),
                                        QgsPointXY(x0 + 60 * M, 41.0 + ym * M)]),
            {"pipe_type": "lateral", "diameter": 16, "emitter_spacing": 0.3})

zd = ZoneDivider(IFi)

# ── 1. 单阀细分 ──
LOGS.clear()
r = zd.divide()
valves = {f.id(): str(f["zone"]) for f in layers["aqd_valves"].getFeatures()}
check("单阀细分: 3 阀各自成区+公共区", r.get("zones") == 4 and len(valves) == 3
      and len(set(valves.values())) == 3, str(valves))

# ── 2. 手动标签分区(选中 2 阀指定「一区」) ──
vlist = sorted(valves.keys())[:2]
v3 = [i for i in valves if i not in vlist][0]
layer_v = layers["aqd_valves"]
layer_v.selectByIds(vlist)
LOGS.clear()
r2 = zd.assign_zone_to_valves("一区")
valves2 = {f.id(): str(f["zone"]) for f in layer_v.getFeatures()}
check("手动标签: 两阀同标签「一区」", valves2[vlist[0]] == valves2[vlist[1]] == "一区", str(valves2))
check("第三阀不变", valves2[v3] == valves[v3])
g1 = "一区"
pipe_zones = [str(f["zone"]) for f in layers["aqd_pipes"].getFeatures()]
check("支管/毛管重标记", pipe_zones.count(g1) == 8, f"{g1}: {pipe_zones.count(g1)} 段(期望8)")
check("干管为公共区 0", pipe_zones.count("0") >= 1)

# ── 3. 轮灌联动 ──
fl = layers["aqd_fields"]
add(fl, QgsGeometry.fromPolygonXY([
    [QgsPointXY(111.0, 41.0), QgsPointXY(111.0 + 400 * M, 41.0),
     QgsPointXY(111.0 + 400 * M, 41.0 + 100 * M), QgsPointXY(111.0, 41.0 + 100 * M),
     QgsPointXY(111.0, 41.0)]]), {"crop_type": "maize"})
field_feat = next(fl.getFeatures())
plan = RotationScheduler(IFi).collect_field_data(field_feat)
zones_in_plan = {z["zone"]: z["valves"] for z in plan["zones"]}
check("轮灌联动: 「一区」含 2 个阀门", len(zones_in_plan.get(g1, [])) == 2, str(zones_in_plan.get(g1)))

# ── 4. 按流量自动编组(几何估算,无模拟历史) ──
# 每条带: 3 毛管 × (60m/0.3m × 0.506×10^0.5) ≈ 960 L/h;目标 2000 → 前两阀一组
LOGS.clear()
r4 = zd.auto_group_by_flow(2000.0)
valves4 = {f.id(): str(f["zone"]) for f in layer_v.getFeatures()}
check("编组: 组数=2", len(set(valves4.values())) == 2, str(sorted(set(valves4.values()))))
check("编组: 前两阀同组", valves4[vlist[0]] == valves4[vlist[1]])
check("编组: 第三阀独立组", valves4[v3] != valves4[vlist[0]])
g_flow = {g["zone"]: g["flow_lph"] for g in r4.get("groups", [])}
g2v = {v: k for k, vs in [(g["zone"], g["valves"]) for g in r4.get("groups", [])] for v in vs}
# 每阀需求 ≈960 L/h → 组流量 = 阀数 × 960
check("编组: 组流量=阀数×~960 L/h",
      all(abs(g_flow[z] - 960.0 * len(r4["groups"][i]["valves"])) < 60
          for i, z in enumerate(g_flow)), str(g_flow))

# ── 5. 手动标签边界 ──
LOGS.clear()
layer_v.selectByIds([v3])
r7 = zd.assign_zone_to_valves("北带")
valves7 = {f.id(): str(f["zone"]) for f in layer_v.getFeatures()}
check("单阀指派标签", r7.get("zone") == "北带" and valves7[v3] == "北带", str(valves7))
layer_v.selectByIds(vlist)
r8 = zd.assign_zone_to_valves("")
check("空标签 → 自动 G*", r8.get("zone", "").startswith("G"), str(r8))
LOGS.clear()
r9 = zd.assign_zone_to_valves("0")
check("标签 0 → 拒绝", r9.get("valves") == 0 and any(m[0] == "warn" for m in LOGS))
LOGS.clear()
layer_v.removeSelection()
r10 = zd.assign_zone_to_valves("y")
check("未选阀门 → 拒绝", r10.get("valves") == 0 and any(m[0] == "warn" for m in LOGS))

shutil.rmtree(TMP, ignore_errors=True)
print()
print("ALL OK" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
