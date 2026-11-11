#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模拟精度档与计算耗时基准（fast / standard / high）

对两案例的代表性算例，用 wdrip 的三档精度各重复运行若干次（取最短耗时），
以 high 档结果为基准，统计低精度档的滴头平均流量与末端压力相对误差。

算例
----
* case1        — Sharu (2020) 毛管：100 个 PC 滴头
* case2-A/F/G  — Provenzano (2005) 的 A、F、G 三型（最大管径 / 最长毛管 /
                 中等规格，N=95~100）

要点
----
* 每档先预热一次再计时（首次运行含 WNTR 导入与缓存开销，会虚高十倍以上）。
* 重复 3 次取最短值，降低机器负载抖动。
* `fast` 档 max_iter=5，在部分算例上不足收敛，会出现可见误差。

输出：benchmarks/bench_precision.json
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "wdrip-core"))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/mplcfg")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sharu = load("sharu2020", os.path.join(HERE, "case1", "reproduce_sharu2020.py"))
prov = load("provenzano2005", os.path.join(HERE, "case2", "reproduce_provenzano2005.py"))

PRESETS = ["fast", "standard", "high"]
REPEAT = 3
OUT = os.path.join(HERE, "benchmarks", "bench_precision.json")


def run_case1(preset):
    net = sharu.build_lateral()
    _, res = sharu.run_lateral(net, precision=preset)
    p, q = sharu.profile(res)
    return {"q_mean": float(np.mean(q)), "p_end": float(p[-1])}


def run_case2(model):
    def _run(preset):
        r = prov.run_model(model, precision=preset)
        return {"q_mean": r["q_mean_sim"], "p_end": r["Hfin_sim"]}
    return _run


def timed(fn, repeat=REPEAT):
    fn()  # warm-up（不计时）
    best, res = None, None
    for _ in range(repeat):
        t0 = time.perf_counter()
        res = fn()
        dt = time.perf_counter() - t0
        best = dt if best is None else min(best, dt)
    return best, res


def main():
    cases = {
        "case1 (N=100)": run_case1,
        "case2-A (N=100)": run_case2("A"),
        "case2-F (N=96)": run_case2("F"),
        "case2-G (N=95)": run_case2("G"),
    }

    rows = []
    for name, fn in cases.items():
        per = {}
        for preset in PRESETS:
            t, res = timed(lambda p=preset: fn(p))
            per[preset] = {"time_s": t, "result": res}
        base = per["high"]["result"]
        base_t = per["high"]["time_s"]
        for preset in PRESETS:
            r = per[preset]["result"]
            rows.append({
                "case": name, "preset": preset,
                "time_s": per[preset]["time_s"],
                "rel_time": per[preset]["time_s"] / base_t,
                "q_mean": r["q_mean"],
                "q_err_pct": abs(r["q_mean"] - base["q_mean"]) / abs(base["q_mean"]) * 100.0,
                "p_end": r["p_end"],
                "p_err_m": abs(r["p_end"] - base["p_end"]),
            })

    hdr = (f"{'case':<18}{'preset':<10}{'time(s)':>9}{'rel':>7}"
           f"{'q_mean':>10}{'q_err%':>10}{'p_end':>9}{'p_err(m)':>10}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['case']:<18}{r['preset']:<10}{r['time_s']:>9.4f}{r['rel_time']:>7.2f}"
              f"{r['q_mean']:>10.4f}{r['q_err_pct']:>10.6f}{r['p_end']:>9.4f}{r['p_err_m']:>10.6f}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"presets": PRESETS, "repeat": REPEAT, "rows": rows},
                  f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {OUT}")


if __name__ == "__main__":
    main()
