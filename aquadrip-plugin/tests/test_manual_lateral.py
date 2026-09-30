# -*- coding: utf-8 -*-
"""手动放置毛管测试:无效几何 makeValid/断续行多段/选段/碎屑过滤

回归背景:
- 不规则手绘田块常带无效几何(自相交/环自触碰/重复点),GEOS 求交
  直接拓扑失败 → 预览/放置全部失效;
- 断续行(111·0000·1111111)只取最长段,短段无法放置;
- 分段按点击位置独立放置。
"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bootstrap import init_qgis, IF, LOGS

app, canvas = init_qgis()
IFi = IF()

from qgis.core import QgsGeometry, QgsPointXY, QgsWkbTypes
from tools.lateral_generator import LateralGenerator
from tools.manual_lateral_tool import ManualLateralTool


def P(x, y):
    return QgsPointXY(x, y)


ok = True


def check(name, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        ok = False


# ── 1. 各类几何的可放置性 ──
rect = QgsGeometry.fromPolygonXY([[P(0, 0), P(100, 0), P(100, 50), P(0, 50), P(0, 0)]])
lshape = QgsGeometry.fromPolygonXY([[P(0, 0), P(100, 0), P(100, 50), P(60, 50),
                                    P(60, 90), P(0, 90), P(0, 0)]])
holed = QgsGeometry.fromPolygonXY([[P(0, 0), P(100, 0), P(100, 90), P(0, 90), P(0, 0)],
                                   [P(40, 30), P(60, 30), P(60, 60), P(40, 60), P(40, 30)]])
bowtie = QgsGeometry.fromPolygonXY([[P(0, 0), P(100, 90), P(100, 0), P(0, 90), P(0, 0)]])
selftouch = QgsGeometry.fromPolygonXY([[P(0, 0), P(100, 0), P(100, 50), P(50, 50),
                                        P(50, 90), P(0, 90), P(0, 50), P(50, 50),
                                        P(0, 50), P(0, 0)]])
dupvert = QgsGeometry.fromPolygonXY([[P(0, 0), P(0, 0), P(100, 0), P(100, 50),
                                      P(0, 50), P(0, 0)]])
multi = QgsGeometry.fromMultiPolygonXY([[[P(0, 0), P(50, 0), P(50, 50), P(0, 50), P(0, 0)]],
                                        [[P(200, 0), P(260, 0), P(260, 40), P(200, 40), P(200, 0)]]])
angle = 0.0

cases = [
    ("rect 凸", rect, P(50, 25), True),
    ("L形 主体", lshape, P(80, 25), True),
    ("L形 竖臂", lshape, P(30, 70), True),
    ("带洞 洞右侧", holed, P(80, 45), True),
    ("multi 部件2", multi, P(230, 20), True),
    ("蝴蝶结 左三角区(无效几何)", bowtie, P(25, 15), True),
    ("蝴蝶结 右三角区(无效几何)", bowtie, P(75, 75), True),
    ("环自触碰 右臂(无效几何)", selftouch, P(75, 25), True),
    ("环自触碰 上臂(无效几何)", selftouch, P(25, 70), True),
    ("重复顶点 中心", dupvert, P(50, 25), True),
    ("rect 外部", rect, P(200, 200), None),   # 田块外必须仍 None
]
for name, g, pt, expect_some in cases:
    r = LateralGenerator.lateral_segment_at(pt, g, angle)
    got = r is not None and len(r) >= 1 and len(r[0]) >= 2
    check(name, got == bool(expect_some))

# ── 2. 断续行(111·0000·1111111):全部区段返回 + 按点击选段 ──
# 矩形 (0,20)-(100,50) 顶部挖缺口 x∈[20,70] 深至 y=22:
# 行 y=25 → 内 x∈[0,20](短段20) | 缺口 x∈(20,70) | 内 x∈[70,100](长段30)
ushape = QgsGeometry.fromPolygonXY([[P(0, 20), P(100, 20), P(100, 50), P(70, 50), P(70, 22),
                                     P(20, 22), P(20, 50), P(0, 50), P(0, 20)]])
segs = LateralGenerator.lateral_segment_at(P(50, 25), ushape, angle, min_len=0.0)
check("断续行返回 2 段", segs is not None and len(segs) == 2)
if segs:
    l1 = QgsGeometry.fromPolylineXY(segs[0]).length()
    l2 = QgsGeometry.fromPolylineXY(segs[1]).length()
    check("两段长度 20/30(短在前)", abs(l1 - 20) < 1e-6 and abs(l2 - 30) < 1e-6)

segs_f = LateralGenerator.lateral_segment_at(P(50, 25), ushape, angle, min_len=25.0)
check("min_len=25 过滤掉 20 段", segs_f is not None and len(segs_f) == 1)

# 选段:点短臂选短段,点长臂选长段(工具 _pick_segment 逻辑)
class _FakeTool:
    _pick_segment = ManualLateralTool._pick_segment
    _min_len = ManualLateralTool._min_len
    _layer_crs = staticmethod(lambda: None)
ft = _FakeTool()
check("点短臂→选短段", ft._pick_segment(segs, P(10, 25)) is segs[0])
check("点长臂→选长段", ft._pick_segment(segs, P(85, 25)) is segs[1])
check("无效 CRS → min_len=0", ft._min_len() == 0.0)
check("缺口点击 → 不在田块内", not ushape.intersects(QgsGeometry.fromPointXY(P(50, 25))))

# ── 3. min_len 单位换算(经纬度→度/投影→米/无效→0) ──
from qgis.core import QgsVectorLayer


class _T:
    _min_len = ManualLateralTool._min_len
    _layer_crs = staticmethod(lambda: None)


geo = QgsVectorLayer("polygon?crs=EPSG:4326", "g", "memory")
proj = QgsVectorLayer("polygon?crs=EPSG:32649", "p", "memory")
t = _T()
t._layer_crs = staticmethod(lambda: geo.crs())
v1 = t._min_len()
t._layer_crs = staticmethod(lambda: proj.crs())
v2 = t._min_len()
t._layer_crs = staticmethod(lambda: None)
v3 = t._min_len()
check("geographic min_len≈4.5e-6°(0.5m)", 4e-6 < v1 < 5e-6, f"{v1:.2e}")
check("projected min_len=0.5m", v2 == 0.5)
check("invalid CRS min_len=0(不过滤)", v3 == 0.0)

print()
print("ALL OK" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
