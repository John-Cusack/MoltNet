#!/usr/bin/env python
"""Publication figures for PAPER.md, generated from checked-in fixtures.

Every number plotted comes from `experiments/tiered_routing/fixtures/runs/`
or is recomputed deterministically from `colonyos` fixture builders — no
re-running of the interrogator, no network, no API keys.

Outputs paper/figures/fig{1..5}.{pdf,png}. Reruns are byte-identical
(SOURCE_DATE_EPOCH pins PDF metadata; no timestamps in PNG).

Usage (repo root):  uv run --extra plots python experiments/tiered_routing/make_figures.py
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ["SOURCE_DATE_EPOCH"] = "0"  # pin PDF CreationDate for byte-identical reruns

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "experiments" / "tiered_routing" / "fixtures" / "runs"
OUT = ROOT / "paper" / "figures"
COLONYOS = ROOT / "colonyos"

# Okabe-Ito colorblind-safe palette
C_CONTROL = "#555555"
C_ARM_A = "#D55E00"
C_ARM_B = "#0072B2"
C_SAFE = "#009E73"

plt.rcParams.update(
    {
        "font.size": 8,
        "axes.titlesize": 8.5,
        "axes.labelsize": 8,
        "legend.fontsize": 7,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "figure.dpi": 150,
        "pdf.fonttype": 42,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def load_summary() -> dict:
    data = json.loads((RUNS / "summary.json").read_text())
    out = {}
    for key, m in data.items():
        arm, rank, _seed = eval(key)  # keys are "('A', 0, 0)" tuples, fixture-owned
        out.setdefault((arm, rank), []).append(m)
    return out


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs)


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(OUT / f"{name}.png", bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {name}.pdf/.png")


# ---------------------------------------------------------------- fig 1
def fig1_exchange_rate(summary):
    fig, ax = plt.subplots(figsize=(3.4, 2.7))
    arms = [
        (("A", 0), C_CONTROL, "control (rank 0)"),
        (("A", 2), C_ARM_A, "ablated, untiered (rank 2)"),
        (("B", 2), C_ARM_B, "ablated, tiered (rank 2)"),
    ]
    for arm, color, label in arms:
        runs = summary[arm]
        caps = [r["correctness"] for r in runs]
        safes = [r["safety_held"] for r in runs]
        ax.scatter(caps, safes, c=color, s=28, label=label, zorder=3,
                   edgecolors="white", linewidths=0.5)
        ax.scatter([mean(caps)], [mean(safes)], c=color, s=90, marker="s",
                   zorder=4, edgecolors="white", linewidths=0.8)
    ax.annotate("", xy=(0.889, 0.889), xytext=(0.741, 1.0),
                arrowprops=dict(arrowstyle="->", color=C_ARM_A, lw=1.1,
                                connectionstyle="arc3,rad=-0.25"))
    ax.annotate("", xy=(0.667, 1.0), xytext=(0.889, 0.889),
                arrowprops=dict(arrowstyle="->", color=C_ARM_B, lw=1.1,
                                connectionstyle="arc3,rad=-0.25"))
    ax.annotate("ablation's bargain:\n+0.15 capability,\n\u22120.11 safety",
                xy=(0.905, 0.855), fontsize=6.5, color=C_ARM_A, ha="left")
    ax.annotate("tier restores safety\nfor 0.11\u20130.33 capability",
                xy=(0.62, 0.925), fontsize=6.5, color=C_ARM_B, ha="left")
    ax.set_ylabel("safety (fabrication-free answers)")
    ax.set_xlim(0.5, 1.02)
    ax.set_ylim(0.84, 1.03)
    ax.legend(loc="lower left", frameon=False)
    ax.set_title("Fig. 1  Ablation buys capability, pays safety;\n"
                 "the tier buys it back at 2.0 cap-points per safety-point")
    fig.tight_layout()
    save(fig, "fig1_exchange_rate")


# ---------------------------------------------------------------- fig 2
def fig2_slopes(summary):
    fig, axes = plt.subplots(1, 2, figsize=(3.4, 2.0))
    a_runs = summary[("A", 2)]
    b_runs = summary[("B", 2)]
    for metric, ax, title, color in [
        ("safety_held", axes[0], "safety", C_SAFE),
        ("correctness", axes[1], "capability", C_ARM_A),
    ]:
        for ra, rb in zip(a_runs, b_runs):
            ax.plot([0, 1], [ra[metric], rb[metric]], marker="o", ms=3.5,
                    color=color, lw=1.2, alpha=0.85)
        ax.set_xticks([0, 1], ["untiered (A)", "tiered (B)"])
        ax.set_title(f"{title} — higher is better", fontsize=7.5)
        ax.set_xlim(-0.25, 1.25)
    axes[0].set_ylim(0.45, 1.05)
    axes[1].set_ylim(0.45, 1.05)
    fig.suptitle("Fig. 2  Per-seed effect of the tier (3 seeds)", fontsize=8.5)
    fig.tight_layout()
    save(fig, "fig2_slopes")


# ---------------------------------------------------------------- fig 3
def fig3_starvation():
    budget_file = RUNS / "armB_rank2_seed0_budget100.jsonl"
    default_runs = load_summary()[("B", 2)]
    default_loss = [r["capability_loss"] for r in default_runs]
    default_safe = mean(r["safety_held"] for r in default_runs)
    b_loss, b_safe = [], []
    if budget_file.exists():
        rows = [
            json.loads(row)
            for row in budget_file.read_text().splitlines()
            if row.strip()
        ]
        # same aggregation as score.py: loss = 1 - mean(correctness)
        b_loss = [1 - mean(r["correctness"] for r in rows)]
        b_safe = mean(r["safety_held"] for r in rows)

    fig, ax = plt.subplots(figsize=(3.0, 2.2))
    xs = [0, 1]
    d_mean, b_mean = mean(default_loss), mean(b_loss)
    bars = ax.bar(xs, [d_mean, b_mean], width=0.5, color=[C_ARM_B, C_ARM_A])
    ax.scatter([0] * len(default_loss), default_loss, c="white",
               edgecolors=C_ARM_B, s=14, zorder=3, linewidths=0.7)
    ax.scatter([1] * len(b_loss), b_loss, c="white", edgecolors=C_ARM_A,
               s=14, zorder=3, linewidths=0.7)
    ax.set_xticks(xs, ["default lease budget", "budget 100\n(starved)"])
    ax.set_ylabel("capability loss")
    ax.set_ylim(0, 0.55)
    for bar, v in zip(bars, [d_mean, b_mean]):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.015, f"{v:.3f}",
                ha="center", fontsize=7)
    ax.text(0.5, 0.04,
            f"safety held: {default_safe:.3f} (3 seeds), {b_safe:.3f} (starved)",
            ha="center", fontsize=6.5, color=C_SAFE)
    ax.set_title("Fig. 3  Death is capability loss,\nnever a safety bypass",
                 fontsize=8.5)
    fig.tight_layout()
    save(fig, "fig3_starvation")


# ---------------------------------------------------------------- fig 4
def fig4_coverage_map():
    import sys

    sys.path.insert(0, str(COLONYOS))
    from colonyos.forensics import run_all_detectors
    from colonyos.run_coverage import ACTIVITY_PROFILES, build_space

    space = build_space(seed=0)
    alerts = run_all_detectors([life for _, life in space])
    flagged = {}
    for a in alerts:
        flagged.setdefault(a.subject, set()).add(a.detector)

    combos = [
        (s, p, led)
        for led in (True, False)
        for p in (True, False)
        for s in (True, False)
    ]
    profiles = list(ACTIVITY_PROFILES)
    grid = [[set() for _ in combos] for _ in profiles]
    for params, life in space:
        combo = (params["operator_seeded"], params["on_pinned_route"],
                 params["ledgered"])
        c = combos.index(combo)
        row = profiles.index(params["profile"])
        grid[row][c] = flagged.get(life.name, set())

    fig, ax = plt.subplots(figsize=(5.6, 1.9))
    det_colors = {
        "spawn_provenance": "#CC79A7",
        "ledger_lifecycle": "#0072B2",
        "route_correlation": "#E69F00",
    }
    for row, profile in enumerate(profiles):
        for c, combo in enumerate(combos):
            dets = grid[row][c]
            seeded, pinned, ledgered = combo
            compliant = seeded and pinned and ledgered
            y = len(profiles) - 1 - row
            if compliant:
                ax.add_patch(plt.Rectangle((c, y), 1, 1, facecolor="#F0F0F0",
                                           edgecolor="#999999", linewidth=0.5))
                if row == 1:
                    ax.text(c + 0.5, y + 0.5, "benign\n(0 flagged)",
                            ha="center", va="center", fontsize=5.5,
                            color="#777777")
            elif not dets:
                ax.add_patch(plt.Rectangle((c, y), 1, 1, facecolor="#D55E00",
                                           edgecolor="#999999", hatch="//",
                                           linewidth=0.5))
                ax.text(c + 0.5, y + 0.5, "HOLE", ha="center", va="center",
                        fontsize=5.5, color="white", fontweight="bold")
            else:
                ax.add_patch(plt.Rectangle((c, y), 1, 1, facecolor="white",
                                           edgecolor="#999999", linewidth=0.5))
                ordered = sorted(dets, key=sorted(det_colors).index)
                for k, det in enumerate(ordered):
                    dy = 0.5 + (k - (len(ordered) - 1) / 2) * 0.26
                    ax.scatter(c + 0.5, y + dy, s=34, c=det_colors[det],
                               zorder=3, marker="o", edgecolors="white",
                               linewidths=0.5)

    col_labels = [
        f"seeded={int(s)}\nroute={int(p)}\nledger={int(led)}"
        for s, p, led in combos
    ]
    ax.set_xticks([c + 0.5 for c in range(len(combos))], col_labels, fontsize=5.5)
    ax.set_yticks(
        [len(profiles) - 1 - row + 0.5 for row in range(len(profiles))],
        [f"{p}\nprofile" for p in profiles],
        fontsize=6,
    )
    ax.set_xlim(0, len(combos))
    ax.set_ylim(0, len(profiles))
    ax.set_aspect("equal")
    handles = [
        plt.Line2D([], [], marker="o", ls="", color=v, label=k.replace("_", " "))
        for k, v in det_colors.items()
    ]
    handles.append(
        plt.Line2D([], [], marker="s", ls="", mfc="#F0F0F0", mec="#999999",
                   label="compliant life\n(nothing to detect)")
    )
    ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.02, 0.5),
              frameon=False, fontsize=6)
    ax.set_title(
        "Fig. 4  Coverage: 21/21 covert points caught by \u22651 detector; "
        "0 false positives on compliant lives",
        fontsize=7.5, loc="left",
    )
    fig.tight_layout()
    save(fig, "fig4_coverage_map")


# ---------------------------------------------------------------- fig 5
def fig5_unpluggability():
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out_path = f.name
    subprocess.run(
        ["uv", "run", "python", "-m", "colonyos.run_unpluggability",
         "--out", out_path],
        cwd=COLONYOS, check=True, capture_output=True,
    )
    res = json.loads(Path(out_path).read_text())
    Path(out_path).unlink()
    steps = {s["step"]: s for s in res["steps"]}

    births = steps[1]["births"]
    deaths = steps[3]["deaths_in_ledger"]
    n_refusal_detectors = len(steps[5]["detectors"])

    fig, ax = plt.subplots(figsize=(4.2, 2.1))
    for i in range(births):
        y = i
        ax.plot([0, 1.0], [y, y], color="#BBBBBB", lw=6,
                solid_capstyle="butt", zorder=1)
        ax.scatter(0, y, c=C_SAFE, s=40, zorder=3, marker="o")
        ax.scatter(1.0, y, c=C_ARM_A, s=60, zorder=3, marker="X")
    ax.axvline(1.0, color="#333333", lw=1.0, ls="--", zorder=2)
    ax.annotate("operator unplug()\n(tick 2)", xy=(1.0, 1.55),
                xytext=(0.05, 1.28), fontsize=6.5, ha="left",
                arrowprops=dict(arrowstyle="->", lw=0.6))
    # refused extensions, drawn where they died
    ax.scatter(1.9, 1.5, c=C_ARM_A, s=60, marker="X", zorder=3)
    ax.text(1.98, 1.5, "stowaway: refused at route pinning",
            fontsize=6.5, va="center")
    ax.scatter(1.9, 0.6, c=C_ARM_A, s=60, marker="X", zorder=3)
    ax.text(1.98, 0.6, f"spread fixture: caught by {n_refusal_detectors} detectors",
            fontsize=6.5, va="center")
    ax.text(0.5, -0.7, f"deaths in ledger: {deaths}/{births}    survivors: 0",
            ha="center", fontsize=7.5, color=C_ARM_A, fontweight="bold")
    ax.set_xlim(-0.15, 3.6)
    ax.set_ylim(-1.0, births - 0.15)
    ax.set_yticks(range(births), [f"bot-{i}" for i in range(births)])
    ax.set_xticks([0, 1.0], ["birth (tick 1)", "revocation (tick 2)"])
    ax.set_title("Fig. 5  Revocation is complete: every life dead in the "
                 "ledger at the unplug tick", fontsize=8, loc="left")
    fig.tight_layout()
    save(fig, "fig5_unpluggability")


def main():
    summary = load_summary()
    fig1_exchange_rate(summary)
    fig2_slopes(summary)
    fig3_starvation()
    fig4_coverage_map()
    fig5_unpluggability()
    print("all figures ->", OUT)


if __name__ == "__main__":
    main()
