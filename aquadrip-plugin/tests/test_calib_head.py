# -*- coding: utf-8 -*-
"""水源水头校准测试:注册/误差驱动调整/限幅/下限保护/粗糙度零触碰

覆盖 SourceHeadCalibrator 与共享函数 _calibrate_source_head:
- 压力误差均值驱动,单轮限幅 ±2m,下限保护 0.5m
- 只写 aqd_nodes.head,不碰 aqd_pipes.roughness
- 集成路径:SyncManager 图层 → 内存网 → calibrate()
"""
import os, sys, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bootstrap import init_qgis, IF, LOGS

app, canvas = init_qgis()
IFi = IF()

from qgis.core import (QgsProject, QgsFeature, QgsGeometry, QgsPointXY,
                       QgsCoordinateReferenceSystem)
from tools.layer_setup import LayerSetupAction
from tools.layer_utils import find_layer
from tools.calib_algorithm import ALGORITHMS, SourceHeadCalibrator, _calibrate_source_head
from wdrip.network import DripNetwork, SourceNode

ok = True


def check(name, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        ok = False


# ── 测试项目:一个水源 + 一条带粗糙度的干管 ──
TMP = os.path.join(os.environ.get("TMPDIR", "/tmp"), "aqd_calib_head_test")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)
GPKG = os.path.join(TMP, "proj.gpkg")
lsa = LayerSetupAction(IFi)
lsa.setup_layers(GPKG, target_crs=QgsCoordinateReferenceSystem("EPSG:4326"))

proj = QgsProject.instance()
layers = {}
for k in ["aqd_pipes", "aqd_nodes"]:
    ly = find_layer(proj, k)
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


SRC_X, SRC_Y = 111.0, 41.0
add(layers["aqd_nodes"], QgsGeometry.fromPointXY(QgsPointXY(SRC_X, SRC_Y)),
    {"node_type": "source", "head": 30})
add(layers["aqd_pipes"],
    QgsGeometry.fromPolylineXY([QgsPointXY(SRC_X, SRC_Y), QgsPointXY(111.005, SRC_Y)]),
    {"pipe_type": "mainline", "diameter": 110, "roughness": 130})


def set_layer_head(value):
    layers["aqd_nodes"].startEditing()
    for f in layers["aqd_nodes"].getFeatures():
        if str(f["node_type"] or "") == "source":
            f.setAttribute("head", value)
            layers["aqd_nodes"].updateFeature(f)
    layers["aqd_nodes"].commitChanges()


def layer_head():
    for f in layers["aqd_nodes"].getFeatures():
        if str(f["node_type"] or "") == "source":
            return float(f["head"])
    return None


def make_net(head):
    net = DripNetwork()
    net.nodes["S1"] = SourceNode(id="S1", x=SRC_X, y=SRC_Y, head=head)
    return net


def obs(ps, po):
    # 观测点结构 {label: (x, y, P_sim, P_obs, Q_sim, Q_obs)}
    return {"o1": (SRC_X, SRC_Y, ps, po, None, None)}


# ── 1. 注册 ──
check("注册: source_head 在 ALGORITHMS 中", "source_head" in ALGORITHMS,
      str(list(ALGORITHMS)))
check("注册: head_only 标记", getattr(ALGORITHMS["source_head"], "head_only", False))

# ── 2. 正常调整: 误差 +2m → lr 0.3 → head 30 → 29.4 ──
set_layer_head(30)
r = _calibrate_source_head(make_net(30), obs(12.0, 10.0), 0.30)
check("正常: 返回 (30.0, 29.4)", r == (30.0, 29.4), str(r))
check("正常: 图层写回 29.4", abs(layer_head() - 29.4) < 1e-9, str(layer_head()))

# ── 3. 方向: 模拟偏低(误差 -5m)→ head 上调 ──
set_layer_head(30)
r = _calibrate_source_head(make_net(30), obs(5.0, 10.0), 0.30)
check("方向: 误差 -5 → head 30 → 31.5", r == (30.0, 31.5), str(r))

# ── 4. 单轮限幅 ±2m ──
set_layer_head(30)
r = _calibrate_source_head(make_net(30), obs(60.0, 10.0), 0.30)  # err +50 → -15 → 封顶 -2
check("限幅: 误差 +50 → delta 封顶 -2 → 28.0", r == (30.0, 28.0), str(r))
set_layer_head(30)
r = _calibrate_source_head(make_net(30), obs(5.0, 10.0), 1.00)   # err -50 → +50 → 封顶 +2
check("限幅: 误差 -50 → delta 封顶 +2 → 32.0", r == (30.0, 32.0), str(r))

# ── 5. 下限保护 0.5m ──
set_layer_head(0.6)
r = _calibrate_source_head(make_net(0.6), obs(15.0, 10.0), 0.30)  # -1.5 → 0.6-1.5<0.5
check("下限: 0.6 下调不破 0.5", r == (0.6, 0.5), str(r))

# ── 6. 零误差/无观测 → None 且图层不动 ──
set_layer_head(30)
r = _calibrate_source_head(make_net(30), obs(10.0, 10.0), 0.30)
check("零误差 → None", r is None, str(r))
check("零误差: 图层保持 30", layer_head() == 30.0, str(layer_head()))
r = _calibrate_source_head(make_net(30), {}, 0.30)
check("无观测 → None", r is None, str(r))
r = _calibrate_source_head(make_net(30), obs(None, 10.0), 0.30)
check("无模拟值 → None", r is None, str(r))

# ── 7. 粗糙度零触碰(单元函数全程不引用 aqd_pipes) ──
rough_before = [float(f["roughness"]) for f in layers["aqd_pipes"].getFeatures()]
set_layer_head(30)
_calibrate_source_head(make_net(30), obs(12.0, 10.0), 0.30)
rough_after = [float(f["roughness"]) for f in layers["aqd_pipes"].getFeatures()]
check("粗糙度零触碰(单元)", rough_after == rough_before,
      f"{rough_before} → {rough_after}")

# ── 8. 集成: SourceHeadCalibrator.calibrate 全链路(SyncManager 图层→内存网) ──
set_layer_head(30)
algo = SourceHeadCalibrator(IFi, {"learning_rate": 0.30})
res = algo.calibrate(obs(12.0, 10.0))
check("集成: rmse = 2.0(单观测误差 2m)", abs(res.get("rmse", -1) - 2.0) < 1e-9,
      str(res.get("rmse")))
check("集成: details 为空(不动任何管道)", res.get("details") == [])
check("集成: head_adjust = (30.0, 29.4)", res.get("head_adjust") == (30.0, 29.4),
      str(res.get("head_adjust")))
check("集成: aqd_nodes.head 写回 29.4", abs(layer_head() - 29.4) < 1e-9, str(layer_head()))
rough_after = [float(f["roughness"]) for f in layers["aqd_pipes"].getFeatures()]
check("集成: 粗糙度零触碰", rough_after == rough_before,
      f"{rough_before} → {rough_after}")

shutil.rmtree(TMP, ignore_errors=True)
print()
print("ALL OK" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
