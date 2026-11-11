#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复现 case1：Sharu & Ab Razak (2020) Water 12(8):2295

"Hydraulic Performance and Modelling of Pressurized Drip Irrigation System"

用 aQuaDrip/wdrip 复现论文的 EPANET 毛管(Lateral)水力模型，对照其
实测/建模的压力分布与统计误差(RMSE/MBE/MAPE)。

论文关键参数（§2.3–2.6、表3、表4）
-----------------------------------
* 毛管：LDPE，标称 Ø20 mm，**内径 17.5 mm**，长 **31 m**
* 滴头间距 60 cm（左右两侧各挂一个 → 沿管轴向相邻滴头约 31/100 = 0.31 m）
  每根毛管 **100 个滴头**
* 滴头：**压力补偿式(PC)**，模型恒定 **2 L/h**（15.3–40.8 m 区间）
* 地形：**水平**（无坡度）
* 实测 4 个工作压力：P1=15.3, P2=20.4, P3=25.5, P4=28.6 m
* 摩擦：Darcy–Weisbach，f = 0.302·Re^(-0.25)；
  局部损失 k = 0.056·[(Dg/Di)^17.83 − 1]
* 对照锚点（毛管入口/manifold 压力 26.03 m）：
    Lateral1 : 滴头#4  模型 25.54 / 实测 24.46 ；末端#100 模型 21.40 / 实测 21.77
    Lateral2 : 首端     模型 25.67 / 实测 24.46 ；末端     模型 21.54 / 实测 20.89
* 论文模型报告的累计水头损失(L1)：前端 0.49 m → 末端 4.63 m
* 统计误差（表4）：压力 RMSE 0.61(L1)/0.79(L2) m、MAPE 2.2%/3.0%、MBE 0.51/0.68 m
                    流量 RMSE 0.04 L/h、MAPE 1.7%、MBE 0.03/0.02 L/h

复现口径与假设（重要）
----------------------
1. 本机 EPANET C 库在 macOS 下崩溃（SIGKILL），wdrip 自动回退
   `IterativeWNTRSimulatorEngine`（迭代逼近 emitter 出水的 WNTR 求解器）。
2. wdrip 的 `_build_wntr_model` 固定使用 **Hazen–Williams**，而论文用
   Darcy–Weisbach。脚本用 H-W 糙率 C 近似，并把论文中占主导的滴头插入
   局部损失折算为每段的 `minor_loss`(K)。
3. 论文未给出滴头"spaghetti"微管的几何(Dg)，局部损失因此无法精确重现，
   K 为**等效拟合值**——目标是对齐论文报告的沿程累计水头损失量级。

用法
----
    python reproduce_sharu2020.py                 # 默认参数 C=150, K=50
    python reproduce_sharu2020.py --sweep         # 扫描 C/K 拟合损失
    python reproduce_sharu2020.py --C 150 --K 50
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "wdrip-core"))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/mplcfg")

from wdrip.network import DripNetwork, SourceNode, EmitterNode, Pipe, FieldInfo  # noqa: E402
from wdrip.simulation import DripSimulation  # noqa: E402
from wdrip.analysis.uniformity import UniformityAnalyzer  # noqa: E402

N_EMITTERS = 100
LATERAL_LENGTH = 31.0          # m
LATERAL_ID_MM = 17.5           # 内径 mm
EMITTER_KC = 2.0               # PC 滴头恒定流量 L/h
EMITTER_XC = 0.0               # 流态指数 0 → 压力补偿
MANIFOLD_HEAD = 26.03          # m，论文实测毛管入口(manifold)压力

ANCHORS = {
    "L1_emitter4": {"pos": 4, "measured": 24.46, "paper_model": 25.54},
    "L1_emitter100": {"pos": 100, "measured": 21.77, "paper_model": 21.40},
    "L2_front": {"pos": 1, "measured": 24.46, "paper_model": 25.67},
    "L2_end": {"pos": 100, "measured": 20.89, "paper_model": 21.54},
}
PAPER_ERRORS = {  # 表 4
    "pressure": {"L1": {"rmse": 0.61, "mape": 2.2, "mbe": 0.51},
                 "L2": {"rmse": 0.79, "mape": 3.0, "mbe": 0.68}},
    "discharge": {"L1": {"rmse": 0.04, "mape": 1.7, "mbe": 0.03},
                  "L2": {"rmse": 0.04, "mape": 1.7, "mbe": 0.02}},
}


def build_lateral(n=N_EMITTERS, length=LATERAL_LENGTH, diameter=LATERAL_ID_MM,
                  roughness=150.0, minor_loss=50.0, head=MANIFOLD_HEAD,
                  k=EMITTER_KC, x=EMITTER_XC, slope=0.0):
    net = DripNetwork(f"sharu_L{n}", field_info=FieldInfo(area=length))
    net.add_node(SourceNode("SRC", 0.0, 0.0, source_type="well", head=head))
    seg = length / n
    prev = "SRC"
    for i in range(1, n + 1):
        nid = f"E{i:03d}"
        elev = slope * (i * seg)
        net.add_node(EmitterNode(nid, i * seg, 0.0, elevation=elev,
                                 emitter_k=k, emitter_x=x, lateral_id="LAT"))
        net.add_link(Pipe(f"P{i:03d}", prev, nid, pipe_type="lateral",
                          diameter=diameter, length=seg, roughness=roughness,
                          minor_loss=minor_loss))
        prev = nid
    return net


def run_lateral(net, precision="high"):
    sim = DripSimulation(net, precision=precision)
    res = sim.run(duration=0)
    if not res.success:
        raise RuntimeError(f"模拟失败: {res.message}")
    return sim, res


def profile(res, n=N_EMITTERS):
    press, flow = [], []
    for i in range(1, n + 1):
        nid = f"E{i:03d}"
        press.append(float(res.node_pressure[nid][0]))
        flow.append(float(res.emitter_flow[nid][0]) if nid in res.emitter_flow else np.nan)
    return np.array(press), np.array(flow)


def report(net, tag="L1"):
    sim, res = run_lateral(net)
    p, q = profile(res)
    inlet, end = p[0], p[-1]
    print(f"\n=== {tag}  (engine={sim.engine_name}) ===")
    print(f"  入口压力 {inlet:.2f} m ; 末端压力 {end:.2f} m ; 沿程压降 {inlet-end:.2f} m")
    print(f"  末端流量 {q[-1]:.3f} L/h ; 平均流量 {np.nanmean(q):.3f} L/h")
    for name, a in ANCHORS.items():
        if not name.startswith(tag):
            continue
        pos = a["pos"]
        sim_p = p[pos - 1]
        print(f"  [{name}] pos{pos}: 本模型 {sim_p:.2f} m | 论文模型 {a['paper_model']:.2f} m "
              f"| 实测 {a['measured']:.2f} m | 累计水头损失 {inlet-sim_p:.2f} m")
    return sim, res, p, q


def main():
    ap = argparse.ArgumentParser(description="Sharu 2020 毛管水力复现")
    ap.add_argument("--C", type=float, default=150.0, help="Hazen-Williams 糙率 C")
    ap.add_argument("--K", type=float, default=51.3, help="每段(滴头)局部损失系数 minor_loss")
    ap.add_argument("--head", type=float, default=MANIFOLD_HEAD, help="毛管入口压力水头 m")
    ap.add_argument("--sweep", action="store_true", help="扫描 C/K 拟合论文累计损失")
    ap.add_argument("--out", default=os.path.join(HERE, "sharu2020_profile.json"))
    args = ap.parse_args()

    if args.sweep:
        print("扫描 C × K（目标：L1 末端累计水头损失 ≈ 4.63 m，末端压力 ≈ 21.40 m）")
        print(f"{'C':>6} {'K':>7} {'入口':>8} {'末端':>8} {'压降':>8}")
        best = None
        for C in (100, 120, 140, 150):
            for K in (0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 80.0):
                net = build_lateral(roughness=C, minor_loss=K, head=args.head)
                _, res = run_lateral(net)
                p, _ = profile(res)
                drop = p[0] - p[-1]
                print(f"{C:>6} {K:>7.2f} {p[0]:>8.2f} {p[-1]:>8.2f} {drop:>8.2f}")
                score = abs(drop - 4.63)
                if best is None or score < best[0]:
                    best = (score, C, K, p[-1])
        print(f"\n最接近(压降→4.63m)：C={best[1]} K={best[2]} → 末端 {best[3]:.2f} m")
        args.C, args.K = best[1], best[2]

    print(f"参数: C={args.C} K={args.K} head={args.head} m"
          f"（滴头 PC {EMITTER_KC} L/h, 内径 {LATERAL_ID_MM} mm, 长 {LATERAL_LENGTH} m）")
    net = build_lateral(roughness=args.C, minor_loss=args.K, head=args.head)
    sim, res, p, q = report(net, tag="L1")

    cu = UniformityAnalyzer.cu(q)
    print(f"\n  模型流量 CU = {cu:.2f}%（PC 滴头→应≈100%）")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({
            "params": {"C": args.C, "K": args.K, "head": args.head,
                       "n": N_EMITTERS, "length": LATERAL_LENGTH,
                       "diameter_mm": LATERAL_ID_MM},
            "pressure_m": p.tolist(), "emitter_flow_Lh": q.tolist(),
            "anchors": ANCHORS, "paper_errors": PAPER_ERRORS,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n剖面已保存: {args.out}")


if __name__ == "__main__":
    main()
