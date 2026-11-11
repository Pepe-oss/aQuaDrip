#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成验证案例的管网布置图（双子图，全英文，SCI 投稿用）

子图 (a) — Sharu & Ab Razak (2020)：2 条 PVC manifold 各接 2 条 LDPE
           毛管（Ø20 mm / ID 17.5 mm，长 31 m，100 个 PC 滴头，间距 0.60 m）。
子图 (b) — Provenzano et al. (2005)：1 条 manifold 接 15 条共挤滴灌带
           （Model A~Q，间距 0.3~1.0 m、滴头数 80~248、管径 9.76~17.25 mm）。

仅绘制四类要素：manifold、滴灌带(lateral)、阀门、观测点（滴头以细点示意）。
输出 PNG(300 dpi) + PDF(矢量)。
"""
from __future__ import annotations

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(HERE, "figures")
os.makedirs(FIG, exist_ok=True)

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "DejaVu Serif", "STIXGeneral"],
    "font.size": 9,
    "axes.linewidth": 0.8,
})

# ---- 样式 ----
C_MANIFOLD = "#1f4e79"
C_LATERAL = "#2e75b6"
C_EMITTER = "#9dc3e6"
C_VALVE = "#c00000"
C_OBS = "#000000"

# Provenzano 表 1（S m, N, D mm, Lc m）
PROV = {
    "A": (1.0, 100, 12.98, 99.4), "B": (0.4, 120, 13.29, 47.9),
    "C": (0.3, 140, 13.48, 42.0), "D": (0.3, 130, 13.62, 39.1),
    "E": (0.3, 140, 13.78, 42.4), "F": (1.0, 96, 13.78, 96.0),
    "G": (1.0, 95, 16.90, 95.1), "H": (0.6, 80, 13.93, 48.2),
    "I": (0.3, 120, 13.87, 35.9), "L": (0.3, 152, 16.97, 45.7),
    "M": (0.5, 100, 14.42, 49.9), "N": (0.3, 248, 17.25, 74.3),
    "O": (0.6, 124, 17.17, 74.1), "P": (0.3, 120, 13.60, 35.9),
    "Q": (0.3, 120, 9.76, 35.5),
}


def valve(ax, x, y, size=0.11):
    """阀门符号：实心圆 + 白色十字"""
    ax.plot(x, y, "o", ms=7, mfc=C_VALVE, mec=C_VALVE, zorder=6)
    ax.plot([x - size * 0.5, x + size * 0.5], [y, y], color="white", lw=0.9, zorder=7)
    ax.plot([x, x], [y - size * 0.5, y + size * 0.5], color="white", lw=0.9, zorder=7)


def panel_a(ax):
    """Sharu 2020：2 manifold × 2 lateral，每带 100 个 PC 滴头"""
    lat_len = 3.3          # 绘图长度（代表 31 m）
    top = 4.15
    obs_l1 = [1, 13, 24, 26, 31, 47, 60, 69, 80, 99]
    obs_l2 = [4, 13, 24, 33, 40, 49, 64, 73, 84, 100]

    groups = [
        # (manifold x0, x1, lateral xs, label)
        (0.35, 3.15, [0.85, 2.65], "Manifold 1"),
        (3.95, 6.75, [4.45, 6.25], "Manifold 2"),
    ]
    for mi, (x0, x1, lxs, mlabel) in enumerate(groups):
        ax.plot([x0, x1], [top, top], color=C_MANIFOLD, lw=3.0,
                solid_capstyle="round", zorder=4)
        ax.text((x0 + x1) / 2, top + 0.22, mlabel, ha="center", va="bottom",
                fontsize=9, color=C_MANIFOLD, fontweight="bold")
        valve(ax, x0 - 0.10, top)
        for li, lx in enumerate(lxs):
            # 毛管
            ax.plot([lx, lx], [top, top - lat_len], color=C_LATERAL, lw=1.6, zorder=3)
            valve(ax, lx, top - 0.10, size=0.09)
            # 滴头（示意，等距）
            n_dots = 34
            for k in range(n_dots):
                yy = top - 0.16 - k * (lat_len - 0.20) / (n_dots - 1)
                ax.plot(lx, yy, "o", ms=1.6, mfc=C_EMITTER, mec="none", zorder=2)
            # 观测点（按论文编号比例定位）
            obs = obs_l1 if li == 0 else obs_l2
            for idx in obs:
                frac = (idx - 1) / 99.0
                yy = top - 0.08 - frac * (lat_len - 0.08)
                ax.plot(lx, yy, "s", ms=3.0, mfc="white", mec=C_OBS, mew=0.8, zorder=8)
            # 编号
            lbl = f"Lateral {mi*2 + li + 1}"
            ax.text(lx, top - lat_len - 0.16, lbl, ha="center", va="top", fontsize=7.5)

    # 尺寸标注
    ax.annotate("", xy=(0.85, top - lat_len - 0.55), xytext=(0.85, top - 0.08),
                arrowprops=dict(arrowstyle="<->", lw=0.7, color="0.3"))
    ax.text(0.72, top - lat_len / 2 - 0.05, "31 m", rotation=90,
            ha="right", va="center", fontsize=8)
    ax.annotate("", xy=(0.35, top + 0.55), xytext=(3.15, top + 0.55),
                arrowprops=dict(arrowstyle="<->", lw=0.7, color="0.3"))
    ax.text(1.75, top + 0.60, "PVC ø28 mm", ha="center", va="bottom", fontsize=7.5)
    ax.text(5.35, top + 0.60, "PVC ø28 mm", ha="center", va="bottom", fontsize=7.5)

    ax.set_title("(a) Sharu & Ab Razak (2020)", fontsize=10.5, fontweight="bold", pad=8)
    ax.text(0.5, -0.06, "4 laterals × 100 PC emitters (2.0 L/h), spacing 0.60 m",
            transform=ax.transAxes, ha="center", va="top", fontsize=7.8, color="0.25")
    ax.set_xlim(0.0, 7.1)
    ax.set_ylim(-0.6, top + 1.0)
    ax.set_aspect("equal")
    ax.axis("off")


def panel_b(ax):
    """Provenzano 2005：1 manifold 接 15 条滴灌带（Model A~Q）"""
    top = 4.3
    models = list(PROV.keys())
    x0, x1 = 0.35, 9.05
    ax.plot([x0, x1], [top, top], color=C_MANIFOLD, lw=3.0,
            solid_capstyle="round", zorder=4)
    ax.text((x0 + x1) / 2, top + 0.24, "Manifold", ha="center", va="bottom",
            fontsize=9, color=C_MANIFOLD, fontweight="bold")
    valve(ax, x0 - 0.12, top)

    lc_max = max(v[3] for v in PROV.values())
    span = x1 - x0 - 0.5
    dx = span / (len(models) - 1)

    for i, m in enumerate(models):
        S, N, D, Lc = PROV[m]
        lx = x0 + 0.25 + i * dx
        lat_len = 3.55 * Lc / lc_max
        ax.plot([lx, lx], [top, top - lat_len], color=C_LATERAL, lw=1.5, zorder=3)
        valve(ax, lx, top - 0.10, size=0.085)
        # 滴头示意（按间距密度：S 越小点越密）
        n_dots = max(10, min(26, int(round(0.55 / S * 12))))
        for k in range(n_dots):
            yy = top - 0.18 - k * (lat_len - 0.22) / (n_dots - 1)
            ax.plot(lx, yy, "o", ms=1.5, mfc=C_EMITTER, mec="none", zorder=2)
        # 观测点：0/25/50/75/100% 五处测压
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            yy = top - 0.10 - frac * (lat_len - 0.10)
            ax.plot(lx, yy, "s", ms=2.6, mfc="white", mec=C_OBS, mew=0.7, zorder=8)
        ax.text(lx, top - lat_len - 0.14, m, ha="center", va="top",
                fontsize=7.5, fontweight="bold")

    # 尺寸标注（最长与最短各一条）
    lx_first = x0 + 0.25
    ax.annotate("", xy=(lx_first - 0.16, top - 0.10), xytext=(lx_first - 0.16, top - 3.55),
                arrowprops=dict(arrowstyle="<->", lw=0.7, color="0.3"))
    ax.text(lx_first - 0.24, top - 1.85, "Lc 35.5–99.4 m", rotation=90,
            ha="right", va="center", fontsize=7.5)

    ax.set_title("(b) Provenzano et al. (2005)", fontsize=10.5, fontweight="bold", pad=8)
    ax.text(0.5, -0.06, "15 coextruded drip lines (A–Q), spacing 0.3–1.0 m, "
                        "80–248 emitters, ID 9.76–17.25 mm",
            transform=ax.transAxes, ha="center", va="top", fontsize=7.8, color="0.25")
    ax.set_xlim(0.0, 9.4)
    ax.set_ylim(-0.6, top + 1.0)
    ax.set_aspect("equal")
    ax.axis("off")


def main():
    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(13.4, 5.15), gridspec_kw={"width_ratios": [1.0, 1.32]})
    panel_a(ax1)
    panel_b(ax2)

    handles = [
        Line2D([], [], color=C_MANIFOLD, lw=3.0, label="Manifold"),
        Line2D([], [], color=C_LATERAL, lw=1.6, label="Lateral (drip line)"),
        Line2D([], [], marker="o", ls="none", ms=2.6, mfc=C_EMITTER,
               mec="none", label="Emitter"),
        Line2D([], [], marker="o", ls="none", ms=6, mfc=C_VALVE, mec=C_VALVE,
               label="Valve"),
        Line2D([], [], marker="s", ls="none", ms=4, mfc="white", mec=C_OBS,
               mew=0.8, label="Observation point"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=5, frameon=False,
               bbox_to_anchor=(0.5, 0.005), fontsize=8.5, handlelength=1.8,
               columnspacing=2.0)
    fig.subplots_adjust(left=0.02, right=0.98, top=0.93, bottom=0.13, wspace=0.06)

    for ext, kw in (("png", dict(dpi=300)), ("pdf", {})):
        path = os.path.join(FIG, f"fig_layout_case1_case2.{ext}")
        fig.savefig(path, bbox_inches="tight", **kw)
        print("saved:", path)
    plt.close(fig)


if __name__ == "__main__":
    main()
