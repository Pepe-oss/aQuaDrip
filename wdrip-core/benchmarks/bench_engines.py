# -*- coding: utf-8 -*-
"""wdrip-core 求解引擎基准(论文引用数字的复现脚本)

四类场景(各 ~100 节点,Ø16mm 毛管 100 滴头/间距0.3m,水源水头 15m,
滴头额定 2 L/h @ 10m):
  simple  平坡简单毛管
  sloped  10% 逆坡毛管(首末端高差 3m)
  mixed   压力补偿(x=0.05)与非补偿(x=0.5)滴头交替
  valve   双支管网,一支 PRV 关闭

指标:
  - 质量守恒残差 = |水源管流量 − Σ滴头出流| / 水源管流量
  - fast/high 精度档间压力与流量最大偏差(收敛一致性)
  - 收敛迭代数、单次求解耗时

运行(需要已安装 wntr 的解释器,如项目 venv):
  python benchmarks/bench_engines.py
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wdrip.network import (DripNetwork, SourceNode, Junction, EmitterNode,
                           Pipe, Valve, ValveType, ValveStatus)
from wdrip.simulation import DripSimulation


def _k_at10(x):
    """10 m 工作压力下出流 2 L/h 的流量系数"""
    return 2.0 / (10.0 ** x)


def _lateral(net, prefix, start_node, x_fn, elev_fn, n=100, s=0.3):
    prev = start_node
    for i in range(n):
        nid = f"{prefix}E{i:03d}"
        net.add_node(EmitterNode(nid, i * s + 1, (i % 10) * 0.5,
                                 elevation=elev_fn(i),
                                 emitter_k=_k_at10(x_fn(i)), emitter_x=x_fn(i)))
        net.add_link(Pipe(f"{prefix}P{i:03d}", prev, nid, pipe_type="lateral",
                          diameter=16, length=s, roughness=140))
        prev = nid
    return prev


def make_net(scenario):
    net = DripNetwork(name=f"bench_{scenario}")
    net.add_node(SourceNode("SRC", 0, 0, elevation=0, head=15))
    if scenario in ("simple", "sloped", "mixed"):
        net.add_node(Junction("J0", 1, 0))
        net.add_link(Pipe("MAIN", "SRC", "J0", pipe_type="mainline",
                          diameter=63, length=2, roughness=140))
        if scenario == "simple":
            _lateral(net, "L", "J0", lambda i: 0.5, lambda i: 0.0)
        elif scenario == "sloped":
            _lateral(net, "L", "J0", lambda i: 0.5, lambda i: i * 0.03)
        else:
            _lateral(net, "L", "J0",
                     lambda i: 0.05 if i % 2 else 0.5, lambda i: 0.0)
    elif scenario == "valve":
        net.add_node(Junction("JM", 1, 0))
        net.add_link(Pipe("MAIN", "SRC", "JM", pipe_type="mainline",
                          diameter=63, length=5, roughness=140))
        for b, closed in ((1, False), (2, True)):
            net.add_node(Junction(f"JB{b}", 2, b))
            net.add_link(Valve(f"V{b}", "JM", f"JB{b}", valve_type=ValveType.PRV,
                               diameter=63, setting=20.0,
                               status=ValveStatus.CLOSED if closed else ValveStatus.OPEN))
            _lateral(net, f"L{b}_", f"JB{b}", lambda i: 0.5, lambda i: 0.0, n=50)
    return net


def _f(v):
    return float(v[0]) if hasattr(v, "__len__") else float(v)


def run_case(scenario):
    out = {"scenario": scenario}
    results = {}
    for prec in ("fast", "high"):
        net = make_net(scenario)
        iters = [0]

        def cb(pct, msg):
            m = re.search(r"迭代\s*(\d+)/", str(msg))
            if m:
                iters[0] = max(iters[0], int(m.group(1)))

        sim = DripSimulation(net, precision=prec)
        t0 = time.time()
        res = sim.run(progress_callback=cb)
        assert res.success, res.message
        results[prec] = (res, time.time() - t0, iters[0])
        out[f"t_{prec}"] = time.time() - t0
        out[f"iters_{prec}"] = iters[0]
        out["nodes"] = len(net.nodes)

    fast, high = results["fast"][0], results["high"][0]

    def _resid(res):
        qs = abs(_f(res.link_flow.get("MAIN", 0))) * 3.6e6
        qe = sum(_f(v) for v in res.emitter_flow.values())
        return abs(qs - qe) / max(qs, 1e-9), qs, qe

    out["resid"], out["q_src"], out["q_emit"] = _resid(fast)
    out["resid_high"], _, _ = _resid(high)

    common = set(fast.node_pressure) & set(high.node_pressure)
    out["dp_max"] = max(abs(_f(fast.node_pressure[k]) - _f(high.node_pressure[k]))
                        for k in common)
    ce = set(fast.emitter_flow) & set(high.emitter_flow)
    out["dq_max"] = max(abs(_f(fast.emitter_flow[k]) - _f(high.emitter_flow[k]))
                        for k in ce)
    out["dq_rel"] = out["dq_max"] / max(1e-9, max(abs(_f(v)) for v in fast.emitter_flow.values()))

    ps = [_f(fast.node_pressure[k]) for k in fast.emitter_flow]
    out["p_min"], out["p_max"] = min(ps), max(ps)

    if scenario == "valve":
        out["q_closed_branch"] = sum(
            _f(fast.emitter_flow.get(f"L2_E{i:03d}", [0])) for i in range(50))
    return out


def main():
    # 预热(消除 wntr 首次导入耗时)
    DripSimulation(make_net("simple"), precision="fast").run()

    print(f"{'场景':10} {'节点':>5} {'耗时fast':>8} {'耗时high':>9} {'迭代f/h':>7} "
          f"{'守恒残差':>10} {'Δp_max(m)':>9} {'Δq_max(L/h)':>11} {'Δq相对':>8}")
    for sc in ("simple", "sloped", "mixed", "valve"):
        r = run_case(sc)
        print(f"{sc:10} {r['nodes']:>5} {r['t_fast']:>7.1f}s {r['t_high']:>8.1f}s "
              f"{r['iters_fast']}/{r['iters_high']:>3} {r['resid']:>10.2e} "
              f"{r['dp_max']:>9.4f} {r['dq_max']:>11.4f} {r['dq_rel']*100:>7.3f}%")
        extra = (f"   守恒残差 high={r['resid_high']:.2e}  "
                 f"源流量={r['q_src']:.1f} L/h Σ滴头={r['q_emit']:.1f} L/h "
                 f"P∈[{r['p_min']:.2f},{r['p_max']:.2f}]m")
        if sc == "valve":
            extra += f" 关闭支Σq={r['q_closed_branch']:.3f} L/h"
        print(extra)


if __name__ == "__main__":
    main()
