#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复现 case2：Provenzano, Pumo & Di Dio (2005)

"Simplified procedure to evaluate head losses in drip irrigation laterals"
Journal of Irrigation and Drainage Engineering, 131(6), 525-532.
DOI: 10.1061/(ASCE)0733-9437(2005)131:6(525)

对照对象
--------
论文表 4 给出 15 种商用共挤滴灌带（Model A~Q）的实测总水头损失 h_T,m
（= H_in − H_fin）与按式(5)(7)估算的 h_T,e。本脚本用 wdrip 重建每条毛管，
以表 1 的几何/滴头参数与表 4 的实测进口压力 H_in 为输入，预测总水头损失
h_T，与 h_T,m、h_T,e 对照。

论文模型（原文式 2/5/6/7）
--------------------------
* 摩阻（Blasius 型）：h_fp = 0.0235·ν^0.25·q^1.75/(D^4.75·S)
  → h_f = 0.0235·ν^0.25·q_av^1.75/(D^4.75·S)·Σ_{i=1}^{N-1} i^1.75
* 局部损失：h_Li = α·V_i²/(2g)，h_L = α·8/(gπ²D⁴)·q_av²·Σ_{i=1}^{N-1} i²
* 总损失：h_T = h_f + h_L

复现口径（重要）
----------------
1. wdrip 的 `_build_wntr_model` 固定用 Hazen-Williams，而论文用 Blasius。
   为使两者口径可比，脚本按"同流量分布下摩阻相等"解出**等效 H-W 糙率 C**
   （纯数学换算，不是对实测值的拟合）：
       10.67·S·Σ_j Q_j^1.852 / (C^1.852·D^4.871) = h_f,Blasius
   由于 H-W 与 Blasius 的流量指数不同（1.852 vs 1.75），单一 C 只在参考
   流量下严格等效，沿程流量递减会带来约 −5% 的残余偏差。
2. 局部损失 α 由表 4 的 h_L 反算（论文表 2 仅给出 M~Q 五型的实测 α，
   A~L 未列出）；反算值量级与论文 0.192~0.950 一致。
3. 管段长度直接用滴头间距 S（0.3~1.0 m）。此前 wdrip 的
   `length=max(link.length, 1)` 会把这些短管段放大，已修复；
   修复前该案例 12 型偏差达 +23%~+136%。

用法
----
    python reproduce_provenzano2005.py
    python reproduce_provenzano2005.py --out results.json
"""
from __future__ import annotations

import argparse
import json
import math
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

NU = 1.0e-6      # 运动黏度 m²/s
G = 9.81

# 表 1：几何与水力特性（ND mm, qn L/h, S m, N -, Lc m, D mm, Dg mm, Lg mm, K, x）
TABLE1 = {
    "A": dict(ND=16, qn=4.1, S=1.0, N=100, Lc=99.4, D=12.98, Dg=12.80, Lg=63.92, K=1.282, x=0.480),
    "B": dict(ND=16, qn=2.1, S=0.4, N=120, Lc=47.9, D=13.29, Dg=11.51, Lg=67.89, K=0.612, x=0.537),
    "C": dict(ND=16, qn=2.2, S=0.3, N=140, Lc=42.0, D=13.48, Dg=12.14, Lg=68.22, K=0.667, x=0.514),
    "D": dict(ND=16, qn=2.0, S=0.3, N=130, Lc=39.1, D=13.62, Dg=11.49, Lg=35.66, K=2.076, x=0.0),
    "E": dict(ND=16, qn=4.0, S=0.3, N=140, Lc=42.4, D=13.78, Dg=11.60, Lg=35.60, K=3.738, x=0.0),
    "F": dict(ND=16, qn=1.7, S=1.0, N=96, Lc=96.0, D=13.78, Dg=12.13, Lg=32.09, K=0.524, x=0.478),
    "G": dict(ND=20, qn=3.8, S=1.0, N=95, Lc=95.1, D=16.90, Dg=15.82, Lg=68.60, K=1.022, x=0.492),
    "H": dict(ND=16, qn=2.3, S=0.6, N=80, Lc=48.2, D=13.93, Dg=11.74, Lg=43.69, K=2.229, x=0.0),
    "I": dict(ND=16, qn=2.3, S=0.3, N=120, Lc=35.9, D=13.87, Dg=11.92, Lg=42.04, K=2.331, x=0.0),
    "L": dict(ND=20, qn=2.3, S=0.3, N=152, Lc=45.7, D=16.97, Dg=15.52, Lg=42.84, K=2.320, x=0.0),
    "M": dict(ND=17, qn=2.0, S=0.5, N=100, Lc=49.9, D=14.42, Dg=13.62, Lg=71.55, K=0.648, x=0.475),
    "N": dict(ND=20, qn=2.0, S=0.3, N=248, Lc=74.3, D=17.25, Dg=16.24, Lg=71.82, K=0.674, x=0.463),
    "O": dict(ND=20, qn=2.3, S=0.6, N=124, Lc=74.1, D=17.17, Dg=15.47, Lg=44.96, K=2.25, x=0.0),
    "P": dict(ND=16, qn=3.5, S=0.3, N=120, Lc=35.9, D=13.60, Dg=11.69, Lg=42.33, K=3.85, x=0.0),
    "Q": dict(ND=12, qn=2.5, S=0.3, N=120, Lc=35.5, D=9.76, Dg=9.35, Lg=34.82, K=0.672, x=0.471),
}

# 表 4：实测/估算（Qin L/h, Hin m, Hfin m, Hav m, qav L/h, hT,m m, hf m, hL m, hT,e m）
TABLE4 = {
    "A": dict(Qin=464.4, Hin=17.97, Hfin=13.89, Hav=14.83, qav=4.68, hTm=4.08, hf=3.87, hL=0.16, hTe=4.04),
    "B": dict(Qin=329.5, Hin=17.88, Hfin=16.48, Hav=16.80, qav=2.78, hTm=1.40, hf=0.92, hL=0.48, hTe=1.41),
    "C": dict(Qin=395.3, Hin=17.98, Hfin=16.00, Hav=16.46, qav=2.81, hTm=1.98, hf=1.02, hL=0.53, hTe=1.54),
    "D": dict(Qin=271.5, Hin=18.34, Hfin=17.13, Hav=17.41, qav=2.08, hTm=1.21, hf=0.46, hL=0.64, hTe=1.11),
    "E": dict(Qin=514.6, Hin=17.94, Hfin=13.90, Hav=14.83, qav=3.74, hTm=4.04, hf=1.51, hL=2.69, hTe=4.19),
    "F": dict(Qin=199.2, Hin=18.42, Hfin=17.67, Hav=17.84, qav=2.08, hTm=0.75, hf=0.65, hL=0.07, hTe=0.71),
    "G": dict(Qin=396.4, Hin=18.36, Hfin=17.23, Hav=17.49, qav=4.18, hTm=1.13, hf=0.80, hL=0.08, hTe=0.88),
    "H": dict(Qin=190.9, Hin=18.45, Hfin=17.95, Hav=18.07, qav=2.23, hTm=0.50, hf=0.25, hL=0.16, hTe=0.41),
    "I": dict(Qin=268.6, Hin=19.11, Hfin=18.22, Hav=18.42, qav=2.33, hTm=0.89, hf=0.41, hL=0.49, hTe=0.90),
    "L": dict(Qin=354.3, Hin=18.32, Hfin=17.83, Hav=17.94, qav=2.32, hTm=0.48, hf=0.30, hL=0.16, hTe=0.46),
    "M": dict(Qin=254.7, Hin=18.40, Hfin=17.88, Hav=18.00, qav=2.56, hTm=0.52, hf=0.41, hL=0.10, hTe=0.51),
    "N": dict(Qin=478.0, Hin=10.47, Hfin=9.31, Hav=9.58, qav=1.92, hTm=1.16, hf=0.77, hL=0.26, hTe=1.03),
    "O": dict(Qin=288.6, Hin=18.40, Hfin=17.93, Hav=18.04, qav=2.25, hTm=0.47, hf=0.31, hL=0.08, hTe=0.39),
    "P": dict(Qin=412.6, Hin=18.19, Hfin=15.86, Hav=16.40, qav=3.85, hTm=2.33, hf=1.09, hL=1.49, hTe=2.59),
    "Q": dict(Qin=293.7, Hin=18.09, Hfin=15.21, Hav=15.87, qav=2.47, hTm=2.88, hf=2.44, hL=0.71, hTe=3.15),
}


def blasius_hf(D, S, N, qav):
    """论文式(5)：首末滴头之间的总摩阻

    注意：式(4) 的分式排版为 hfi = 0.0235·ν^0.25·Qi^1.75·S / D^4.75
    （S 在分子——分段摩阻正比于段长）。PDF 文本提取把 S 错误地留在了
    分母，按分子计算后与表 4 的 h_f 吻合（A/B/C 三型误差 −2.3%/−1.2%/−2.5%）。
    """
    s1 = sum(i ** 1.75 for i in range(1, N))
    return 0.0235 * NU ** 0.25 * qav ** 1.75 * S / D ** 4.75 * s1


def alpha_from_local(D, N, qav, hL):
    """由表 4 的 h_L 反算局部损失系数 α（式 7）"""
    s2 = sum(i ** 2 for i in range(1, N))
    return hL * G * math.pi ** 2 * D ** 4 / (8.0 * qav ** 2 * s2)


def equivalent_C(D, S, N, qav, hf_target):
    """解出与 Blasius 摩阻等效的 Hazen-Williams 糙率 C"""
    q_sum = sum(((N - j) * qav) ** 1.852 for j in range(1, N))
    return (10.67 * S * q_sum / (hf_target * D ** 4.871)) ** (1.0 / 1.852)


def run_model(model, precision="high"):
    spec = TABLE1[model]
    ref = TABLE4[model]
    D_m = spec["D"] / 1000.0
    N = spec["N"]
    S = spec["S"]
    qav = ref["qav"] / 3600.0 / 1000.0        # L/h → m³/s
    hf_blasius = blasius_hf(D_m, S, N, qav)
    alpha = alpha_from_local(D_m, N, qav, ref["hL"])
    C = equivalent_C(D_m, S, N, qav, hf_blasius)

    net = DripNetwork(f"prov_{model}", field_info=FieldInfo(area=S * N))
    net.add_node(SourceNode("SRC", 0.0, 0.0, source_type="well", head=ref["Hin"]))
    prev = "SRC"
    for i in range(1, N + 1):
        nid = f"E{i:04d}"
        net.add_node(EmitterNode(nid, i * S, 0.0, elevation=0.0,
                                 emitter_k=spec["K"], emitter_x=spec["x"],
                                 lateral_id="LAT"))
        # 首段（SRC→E1）长度近似为 0；其余 N-1 段为滴头间距 S
        seg_len = 1e-6 if i == 1 else S
        # 局部损失只在滴头连接处（N-1 处）施加
        seg_minor = 0.0 if i == 1 else alpha
        net.add_link(Pipe(f"P{i:04d}", prev, nid, pipe_type="lateral",
                          diameter=spec["D"], length=seg_len,
                          roughness=C, minor_loss=seg_minor))
        prev = nid

    sim = DripSimulation(net, precision=precision)
    res = sim.run(duration=0)
    if not res.success:
        raise RuntimeError(f"{model} 模拟失败: {res.message}")

    p_in = float(res.node_pressure["E0001"][0])
    p_fin = float(res.node_pressure[f"E{N:04d}"][0])
    flows = np.array([float(res.emitter_flow[f"E{i:04d}"][0]) for i in range(1, N + 1)])
    return {
        "model": model, "S": S, "N": N, "D": spec["D"],
        "Hin_lit": ref["Hin"], "Hin_sim": p_in,
        "Hfin_lit": ref["Hfin"], "Hfin_sim": p_fin,
        "hT_m": ref["hTm"], "hT_e": ref["hTe"],
        "hT_sim": p_in - p_fin,
        "hf_blasius": hf_blasius, "alpha": alpha, "C_eq": C,
        "q_mean_sim": float(np.mean(flows)),
        "q_mean_lit": ref["qav"],
        "CU": UniformityAnalyzer.cu(flows),
    }


def summarize(rows, key):
    errs = [(r["hT_sim"] - r[key]) / r[key] * 100.0 for r in rows]
    e = np.array(errs)
    return {"MAPE": float(np.mean(np.abs(e))), "MBE": float(np.mean(e)),
            "RMSE": float(np.sqrt(np.mean(e ** 2))), "max_abs": float(np.max(np.abs(e)))}


def main():
    ap = argparse.ArgumentParser(description="Provenzano 2005 毛管水头损失复现")
    ap.add_argument("--out", default=os.path.join(HERE, "provenzano2005_results.json"))
    args = ap.parse_args()

    rows = []
    print(f"{'型':>2} {'S(m)':>5} {'N':>4} {'hT,m':>6} {'hT,e':>6} {'wdrip':>6} "
          f"{'vs实测%':>8} {'vs估算%':>8}")
    for m in TABLE1:
        r = run_model(m)
        r["err_vs_m"] = (r["hT_sim"] - r["hT_m"]) / r["hT_m"] * 100.0
        r["err_vs_e"] = (r["hT_sim"] - r["hT_e"]) / r["hT_e"] * 100.0
        rows.append(r)
        print(f"{m:>2} {r['S']:>5.1f} {r['N']:>4} {r['hT_m']:>6.2f} {r['hT_e']:>6.2f} "
              f"{r['hT_sim']:>6.2f} {r['err_vs_m']:>+8.2f} {r['err_vs_e']:>+8.2f}")

    s_m = summarize(rows, "hT_m")
    s_e = summarize(rows, "hT_e")
    print("\n对照实测 h_T,m ：MAPE %.2f%%  MBE %+.2f%%  RMSE %.2f%%  最大 %.2f%%"
          % (s_m["MAPE"], s_m["MBE"], s_m["RMSE"], s_m["max_abs"]))
    print("对照估算 h_T,e ：MAPE %.2f%%  MBE %+.2f%%  RMSE %.2f%%  最大 %.2f%%"
          % (s_e["MAPE"], s_e["MBE"], s_e["RMSE"], s_e["max_abs"]))

    n_neg = sum(1 for r in rows if r["err_vs_m"] < 0)
    print(f"逐型偏差符号：{n_neg} 个负偏 / {len(rows) - n_neg} 个正偏")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"paper": "Provenzano, Pumo & Di Dio (2005), J. Irrig. Drain. Eng. 131(6):525-532",
                   "rows": rows,
                   "stats_vs_measured": s_m, "stats_vs_estimated": s_e,
                   "notes": "等效 C 由 Blasius 摩阻换算；alpha 由表4的 hL 反算；"
                            "短管段长度依赖 wdrip 的 length 修复"},
                  f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {args.out}")


if __name__ == "__main__":
    main()
