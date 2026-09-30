# -*- coding: utf-8 -*-
"""切割工具测试:米制换算/长管比例阈值回归/折线各向异性/端部/仅分割

回归背景:
- 度/米混用(4326 下 2m 切除区间被钳位成整根)
- 650m 长管上 0.5% 比例阈值(3.25m)吞掉 2m 切除区间(切了没反应)
"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bootstrap import init_qgis, IF, LOGS

app, canvas = init_qgis()
IFi = IF(canvas)

from qgis.core import (QgsVectorLayer, QgsField, QgsFeature, QgsGeometry,
                       QgsPointXY, QgsDistanceArea, QgsProject,
                       QgsCoordinateReferenceSystem)
from qgis.PyQt.QtCore import QVariant
from tools.trim_tool import TrimTool

ok = True


def check(name, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        ok = False


def measure_m(ly, pts):
    da = QgsDistanceArea()
    da.setSourceCrs(ly.crs(), QgsProject.instance().transformContext())
    da.setEllipsoid("WGS84")
    return float(da.measureLine(pts))


def run_case(crs_id, start, delta, cut, positions):
    ly = QgsVectorLayer(f"LineString?crs={crs_id}", "pipes", "memory")
    ly.dataProvider().addAttributes([QgsField("pipe_type", QVariant.String)])
    ly.updateFields()
    end = QgsPointXY(start.x() + delta[0], start.y() + delta[1])
    pts = [start, end]
    f = QgsFeature(ly.fields())
    f.setGeometry(QgsGeometry.fromPolylineXY(pts))
    f.setAttribute("pipe_type", "lateral")
    ly.dataProvider().addFeatures([f])
    feat = next(ly.getFeatures())

    tool = TrimTool(IFi, pipe_types=["lateral"], cut_length=cut, mode="click")
    total_m = measure_m(ly, pts)
    ly.startEditing()
    n, rm = tool._do_split(ly, feat, positions)
    ly.commitChanges()
    kept = [measure_m(ly, ff.geometry().asPolyline()) for ff in ly.getFeatures()]
    return n, kept, total_m


LAT = 41.25
COS = math.cos(math.radians(LAT))

# ── EPSG:4326 东西向 100m,切 2m @中点 ──
deg = 100.0 / (111320.0 * COS)
n, kept, total = run_case("EPSG:4326", QgsPointXY(111.0, LAT), (deg, 0), 2.0, [0.5])
gap = total - sum(kept)
check("4326 东西向: 保留2段", len(kept) == 2 and n == 2)
check("4326 东西向: 缺口≈2m", abs(gap - 2.0) < 0.05, f"gap={gap:.3f}m total={total:.2f}")
check("4326 东西向: 段各≈(总-2)/2", all(abs(k - (total - 2.0) / 2) < 0.05 for k in kept))

# ── 4326 南北向(椭球无 x/y 失真) ──
deg_y = 100.0 / 111132.0
n, kept, total = run_case("EPSG:4326", QgsPointXY(111.0, LAT), (0, deg_y), 2.0, [0.5])
gap = total - sum(kept)
check("4326 南北向: 缺口≈2m", abs(gap - 2.0) < 0.05, f"gap={gap:.3f}m")

# ── 4326 偏击(0.25 处) ──
n, kept, total = run_case("EPSG:4326", QgsPointXY(111.0, LAT), (deg, 0), 2.0, [0.25])
gap = total - sum(kept)
check("4326 偏击@0.25: 缺口≈2m", abs(gap - 2.0) < 0.05)

# ── 4326 东西向 650m 长管切 2m(0.5% 比例阈值回归:3.25m>2m 曾整段丢弃) ──
deg650 = 650.0 / (111320.0 * COS)
n, kept, total = run_case("EPSG:4326", QgsPointXY(111.0, LAT), (deg650, 0), 2.0, [0.5])
gap = total - sum(kept)
check("4326 650m 长管切 2m: 缺口≈2m", abs(gap - 2.0) < 0.05,
      f"gap={gap:.4f}m (回归曾为 0.0000)")

# ── 4326 折线(东西50m+南北50m)在 0.75 处切 2m(层长↔米长换算) ──
dx = 50.0 / (111320.0 * COS)
dy = 50.0 / 111132.0
mem = QgsVectorLayer("LineString?crs=EPSG:4326", "m2", "memory")
mem.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
mem.dataProvider().addAttributes([QgsField("pipe_type", QVariant.String)])
mem.updateFields()
pts = [QgsPointXY(111.0, LAT), QgsPointXY(111.0 + dx, LAT), QgsPointXY(111.0 + dx, LAT + dy)]
f = QgsFeature(mem.fields())
f.setGeometry(QgsGeometry.fromPolylineXY(pts))
f.setAttribute("pipe_type", "lateral")
mem.dataProvider().addFeatures([f])
feat = next(mem.getFeatures())
total_m = measure_m(mem, pts)
tool = TrimTool(IFi, pipe_types=["lateral"], cut_length=2.0, mode="click")
mem.startEditing()
tool._do_split(mem, feat, [0.75])
mem.commitChanges()
kept = [measure_m(mem, ff.geometry().asPolyline()) for ff in mem.getFeatures()]
gap = total_m - sum(kept)
check("折线缺口也精确 2m", abs(gap - 2.0) < 0.05, f"total={total_m:.2f} gap={gap:.4f}")

# ── EPSG:32649 投影(回归:投影项目行为不变) ──
n, kept, total = run_case("EPSG:32649", QgsPointXY(500000, 4570000), (100.0, 0), 2.0, [0.5])
gap = total - sum(kept)
check("32649 投影: 缺口≈2m", abs(gap - 2.0) < 0.05)

# ── cut_length=0 仅分割(回归) ──
n, kept, total = run_case("EPSG:4326", QgsPointXY(111.0, LAT), (deg, 0), 0.0, [0.5])
check("cut=0 仅分割: 2段全长不变", len(kept) == 2 and abs(sum(kept) - total) < 0.01)

# ── 3m 短管切 2m:保留两端共≈1m ──
deg3 = 3.0 / (111320.0 * COS)
n, kept, total = run_case("EPSG:4326", QgsPointXY(111.0, LAT), (deg3, 0), 2.0, [0.5])
check("3m管切2m: 保留总长≈1m", abs(sum(kept) - (total - 2.0)) < 0.05)

# ── 末端点点击(区间越出端部只切1m) ──
n, kept, total = run_case("EPSG:4326", QgsPointXY(111.0, LAT), (deg, 0), 2.0, [1.0])
gap = total - sum(kept)
check("末端点点击: 切除≈1m", abs(gap - 1.0) < 0.1, f"gap={gap:.3f}m")

print()
print("ALL OK" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
