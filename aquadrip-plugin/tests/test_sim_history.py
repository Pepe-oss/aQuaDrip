# -*- coding: utf-8 -*-
"""SimHistory v2 分片存储测试(纯 stdlib,任意 python3 可运行)

覆盖:add O(1)/summaries/latest/get/load/delete/purge/容量裁剪/
v1 流式迁移/损坏容错/索引重建/v2 后又出现 v1 文件的追加合并/
大记录性能。
"""
import sys, types, os, json, shutil, tempfile, time

# stub qgis.PyQt.QtWidgets.QApplication(summary() 函数内导入)
_qgis = types.ModuleType("qgis")
_pyqt = types.ModuleType("qgis.PyQt")
_qtwidgets = types.ModuleType("qgis.PyQt.QtWidgets")


class _QA:
    @staticmethod
    def translate(ctx, s):
        return s


_qtwidgets.QApplication = _QA
sys.modules["qgis"] = _qgis
sys.modules["qgis.PyQt"] = _pyqt
sys.modules["qgis.PyQt.QtWidgets"] = _qtwidgets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.sim_history import SimHistory, _iter_json_array


def make_payload(i, n=50):
    return dict(
        cu=90.0 + i, du=85.0 + i,
        node_pressure={f"N{j}": 10.0 + j for j in range(n)},
        link_flow={f"L{j}": 1e-5 * j for j in range(n)},
        link_velocity={f"L{j}": 0.1 * j for j in range(n)},
        emitter_flow={f"E{j}": 1.5 + j * 0.01 for j in range(n)},
        node_coords={f"N{j}": [104.0 + j * 1e-5, 30.0 + j * 1e-5] for j in range(n)},
        message=f"sim {i}",
        link_endpoints={f"L{j}": [f"N{j}", f"N{j+1}"] for j in range(n)},
        link_geometry={f"L{j}": [[104.0, 30.0], [104.1, 30.1]] for j in range(n)},
        rotation_id=("rot1" if i % 2 else None),
        shift_index=(i if i % 2 else None),
    )


tmp = tempfile.mkdtemp(prefix="simhist_test_")
gpkg = os.path.join(tmp, "proj.gpkg")

passed = []


def check(name, cond):
    passed.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


# ── 1. 空历史 ──
h = SimHistory(gpkg)
check("empty summaries", h.summaries() == [])
check("empty latest", h.latest() is None)
check("empty count", h.count == 0)

# ── 2. add ×3 ──
for i in range(3):
    h.add(**make_payload(i), timestamp=f"2026-09-08 10:0{i}:00")
check("count=3", h.count == 3)
ss = h.summaries()
check("summaries newest first", ss[0]["timestamp"] == "2026-09-08 10:02:00")
check("summaries light", all("node_pressure" not in s and "link_flow" not in s for s in ss))
lat = h.latest()
check("latest full record", lat["timestamp"] == "2026-09-08 10:02:00" and lat["node_count"] == 50)
check("units L/h", abs(lat["link_flow"]["L1"] - 1e-5 * 3600 * 1000) < 1e-9)

h2 = SimHistory(gpkg)
check("re-open count", h2.count == 3)
check("get(1) middle", h2.get(1)["timestamp"] == "2026-09-08 10:01:00")
full = h2.load()
check("load() newest first len=3", len(full) == 3 and full[0]["timestamp"].endswith("10:02:00"))

# ── 3. delete ──
check("delete(0) newest", h2.delete(0) is True)
check("count=2 after delete", h2.count == 2)
check("new newest is 10:01", h2.latest()["timestamp"] == "2026-09-08 10:01:00")
check("delete out of range", h2.delete(5) is False)

# ── 4. MAX_RECORDS 裁剪 ──
SimHistory.MAX_RECORDS = 5
h3 = SimHistory(gpkg)
for i in range(10):
    h3.add(**make_payload(100 + i), timestamp=f"2026-09-08 11:{i:02d}:00")
check("cap trim count=5", h3.count == 5)
ss3 = h3.summaries()
check("cap keeps newest",
      ss3[0]["timestamp"] == "2026-09-08 11:09:00" and ss3[-1]["timestamp"] == "2026-09-08 11:05:00")
SimHistory.MAX_RECORDS = 100

# ── 5. purge_all ──
n0 = h3.count
check("purge returns count", h3.purge_all() == n0)
check("purged empty", h3.count == 0 and h3.latest() is None)


# ── 6. v1 迁移 ──
def to_v1(i):
    p = make_payload(i)
    return {"timestamp": f"2026-09-07 0{i}:00:00", "cu": 70.0 + i, "du": 60.0 + i,
            "message": f"v1 rec {i}", "node_count": 50, "pipe_count": 50,
            "emitter_count": 50, "rotation_id": None, "shift_index": None,
            "node_pressure": p["node_pressure"],
            "link_flow": {k: v * 3600 * 1000 for k, v in p["link_flow"].items()},
            "link_velocity": p["link_velocity"], "emitter_flow": p["emitter_flow"],
            "node_coords": p["node_coords"], "link_endpoints": p["link_endpoints"],
            "link_geometry": p["link_geometry"]}


tmp2 = tempfile.mkdtemp(prefix="simhist_legacy_")
gpkg2 = os.path.join(tmp2, "old.gpkg")
legacy = os.path.join(tmp2, "old.simhistory")
with open(legacy, "w", encoding="utf-8") as f:
    json.dump([to_v1(i) for i in range(3)], f, ensure_ascii=False, indent=2)
hl = SimHistory(gpkg2)
ss = hl.summaries()
check("legacy migrated count=3", len(ss) == 3)
check("legacy newest first", ss[0]["timestamp"] == "2026-09-07 02:00:00")
lat = hl.latest()
check("legacy latest data intact", lat["cu"] == 72.0 and lat["node_count"] == 50)
check("legacy renamed .bak", os.path.exists(legacy + ".bak") and not os.path.exists(legacy))
hl.add(**make_payload(99), timestamp="2026-09-08 12:00:00")
check("post-migration add", hl.count == 4 and hl.latest()["timestamp"] == "2026-09-08 12:00:00")

# ── 7. 损坏 v1 容错 ──
tmp3 = tempfile.mkdtemp(prefix="simhist_corrupt_")
gpkg3 = os.path.join(tmp3, "bad.gpkg")
legacy3 = os.path.join(tmp3, "bad.simhistory")
with open(legacy3, "w", encoding="utf-8") as f:
    json.dump([to_v1(0), to_v1(1)], f, ensure_ascii=False, indent=2)
    f.truncate(os.path.getsize(legacy3) - 5000)
hc = SimHistory(gpkg3)
check("corrupt keeps salvageable", len(hc.summaries()) >= 1)
check("corrupt renamed .corrupt.bak", os.path.exists(legacy3 + ".corrupt.bak"))

# ── 8. 索引损坏自愈 ──
with open(hl.index_path, "w") as f:
    f.write("{broken json")
hr = SimHistory(gpkg2)
check("index rebuild", hr.count == 4)

# ── 9. 性能:大记录(20 万元素) ──
tmp4 = tempfile.mkdtemp(prefix="simhist_perf_")
gpkg4 = os.path.join(tmp4, "perf.gpkg")
hp = SimHistory(gpkg4)
big = dict(
    cu=90.0, du=85.0,
    node_pressure={f"N{j}": 10.0 + j * 0.001 for j in range(200_000)},
    link_flow={f"L{j}_p{k}": 1e-6 * j for j in range(20_000) for k in (1, 2, 3)},
    link_velocity={f"L{j}_p{k}": 0.01 * j for j in range(20_000) for k in (1, 2, 3)},
    emitter_flow={f"E_L{j}_p{k}_{n:03d}": 1.5 + n * 0.001
                  for j in range(500) for k in (1, 2) for n in range(200)},
    node_coords={f"N{j}": [round(104.0 + j * 1e-6, 7), round(30.0 + j * 1e-6, 7)]
                 for j in range(200_000)},
    message="perf", link_endpoints=None, link_geometry=None)
t0 = time.time(); hp.add(**big, timestamp="T1"); t_add = time.time() - t0
t0 = time.time(); hp.summaries(); t_sum = time.time() - t0
t0 = time.time(); lat = hp.latest(); t_lat = time.time() - t0
check("big add < 10s", t_add < 10)
check("summaries < 50ms", t_sum < 0.05)
check("big latest < 3s", t_lat < 3)
check("big latest intact", lat["node_count"] == 200_000)

# ── 10. v2 已存在 + 后出现的 legacy 文件 → 追加合并 ──
tmp5 = tempfile.mkdtemp(prefix="simhist_merge_")
gpkg5 = os.path.join(tmp5, "m.gpkg")
hm = SimHistory(gpkg5)
hm.add(**make_payload(1), timestamp="2026-09-08 20:00:00")
hm.add(**make_payload(2), timestamp="2026-09-08 20:01:00")
legacy5 = os.path.join(tmp5, "m.simhistory")
_recs = [to_v1(9)]
_recs[0]["timestamp"] = "2026-09-08 21:00:00"
with open(legacy5, "w", encoding="utf-8") as f:
    json.dump(_recs, f, ensure_ascii=False, indent=2)
hm2 = SimHistory(gpkg5)
ss = hm2.summaries()
check("merge count=3", len(ss) == 3)
check("merge newest is legacy rec", ss[0]["timestamp"] == "2026-09-08 21:00:00")
check("merge keeps old v2", ss[2]["timestamp"] == "2026-09-08 20:00:00")
check("merge legacy renamed", not os.path.exists(legacy5))

for d in (tmp, tmp2, tmp3, tmp4, tmp5):
    shutil.rmtree(d, ignore_errors=True)

fails = [n for n, c in passed if not c]
print(f"\n{len(passed) - len(fails)}/{len(passed)} passed"
      + (f", FAILED: {fails}" if fails else ""))
sys.exit(1 if fails else 0)
