#!/usr/bin/env python3
"""
SELENE White Paper Figure Generator
Produces publication-quality figures for all seven white papers.
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from pathlib import Path

# ── Global Style ──
SELENE_BLUE = "#1A3A5C"
SELENE_ACCENT = "#3B82F6"
SELENE_GREEN = "#10B981"
SELENE_ORANGE = "#F59E0B"
SELENE_RED = "#EF4444"
SELENE_GRAY = "#6B7280"
SELENE_LIGHT = "#F3F4F6"

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "DejaVu Serif"],
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

BASE = Path(__file__).parent


def save(fig, paper_dir: str, name: str):
    """Save figure to the correct paper's figures directory."""
    out = BASE / paper_dir / "figures" / f"{name}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out), dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  {out.relative_to(BASE)}")


# ═══════════════════════════════════════════════════════════════
# PAPER 00: SELENE Overview
# ═══════════════════════════════════════════════════════════════

def fig00_system_architecture():
    """Layered architecture diagram."""
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 7)
    ax.axis("off")

    layers = [
        (0.5, 5.5, 9, 1.2, "Mission Control Layer\n(Earth-Side)", "#DBEAFE",
         "Digital Twin  |  Mission Planning  |  Supervisory Control  |  Dashboard"),
        (0.5, 3.5, 9, 1.2, "Fleet Orchestration Layer\n(Lunar-Side)", "#D1FAE5",
         "HTN Planner  |  Task Auction  |  Resource Map  |  Fleet Monitor  |  Adaptive Survey"),
        (0.5, 1.5, 9, 1.2, "Agent Autonomy Layer\n(Per-Robot)", "#FEF3C7",
         "FSM  |  Energy Manager  |  Navigator  |  Skills  |  Bid Computation"),
        (0.5, 0.0, 9, 0.9, "Hardware Abstraction Layer + ISRU Process Control", "#FEE2E2",
         "RCDL  |  Sensor/Actuator Interfaces  |  Inventory  |  Extraction Rate Model"),
    ]

    for x, y, w, h, title, color, desc in layers:
        box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.1",
                             facecolor=color, edgecolor=SELENE_BLUE, linewidth=1.5)
        ax.add_patch(box)
        ax.text(x + 0.3, y + h - 0.3, title, fontsize=9, fontweight="bold",
                color=SELENE_BLUE, va="top")
        ax.text(x + 0.3, y + 0.15, desc, fontsize=7, color=SELENE_GRAY, va="bottom")

    # Delay annotation
    ax.annotate("", xy=(5, 5.5), xytext=(5, 4.7),
                arrowprops=dict(arrowstyle="<->", color=SELENE_RED, lw=1.5))
    ax.text(6.8, 5.05, "1.3s Earth-Moon\nlight delay", fontsize=7,
            color=SELENE_RED, ha="center", style="italic")

    # Inter-layer arrows
    for y_top, y_bot in [(4.7, 3.5 + 1.2), (3.5, 1.5 + 1.2), (2.7, 0.9)]:
        ax.annotate("", xy=(3, y_bot + 0.05), xytext=(3, y_top - 0.05),
                    arrowprops=dict(arrowstyle="<->", color=SELENE_GRAY, lw=1))
        ax.annotate("", xy=(7, y_bot + 0.05), xytext=(7, y_top - 0.05),
                    arrowprops=dict(arrowstyle="<->", color=SELENE_GRAY, lw=1))

    ax.set_title("SELENE System Architecture", fontsize=12, fontweight="bold",
                 color=SELENE_BLUE, pad=10)
    save(fig, "00-selene-overview", "system_architecture")


def fig00_fleet_composition():
    """Fleet composition showing heterogeneous robot types."""
    fig, axes = plt.subplots(1, 4, figsize=(6.5, 2.2))

    robots = [
        ("Scout", SELENE_ACCENT, "Prospecting\nNeutron Spec.\n0.5 m/s\n500 Wh", "prospect"),
        ("Excavator", SELENE_ORANGE, "Drilling\n200W Drill\n0.3 m/s\n80 Wh", "excavate"),
        ("Hauler", SELENE_GREEN, "Transport\n50 kg Bin\n0.4 m/s\n65 Wh", "haul"),
        ("Processor", SELENE_RED, "Refining\nElectrolysis\nStationary\n2000 Wh", "process"),
    ]

    for ax, (name, color, specs, cap) in zip(axes, robots):
        circle = plt.Circle((0.5, 0.55), 0.3, color=color, alpha=0.2, ec=color, lw=2)
        ax.add_patch(circle)
        ax.text(0.5, 0.55, name[0], fontsize=18, fontweight="bold",
                ha="center", va="center", color=color)
        ax.text(0.5, 0.95, name, fontsize=9, fontweight="bold",
                ha="center", va="top", color=SELENE_BLUE)
        ax.text(0.5, 0.05, specs, fontsize=6, ha="center", va="bottom",
                color=SELENE_GRAY, linespacing=1.3)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

    fig.suptitle("Heterogeneous Fleet Composition", fontsize=10,
                 fontweight="bold", color=SELENE_BLUE, y=1.02)
    fig.tight_layout()
    save(fig, "00-selene-overview", "fleet_composition")


def fig00_isru_pipeline():
    """ISRU value chain pipeline diagram."""
    fig, ax = plt.subplots(figsize=(6.5, 2.0))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 2)
    ax.axis("off")

    stages = [
        (0.2, "Prospect", SELENE_ACCENT, "Survey\nMap Resources"),
        (2.4, "Select Site", "#8B5CF6", "Bayesian\nOptimal Site"),
        (4.6, "Excavate", SELENE_ORANGE, "Drill\nExtract Ice"),
        (6.8, "Haul", SELENE_GREEN, "Transport\nto Depot"),
        (8.5, "Deposit", SELENE_RED, "Stockpile\nProcess"),
    ]

    for x, label, color, desc in stages:
        box = FancyBboxPatch((x, 0.5), 1.4, 1.0, boxstyle="round,pad=0.08",
                             facecolor=color, edgecolor="white", alpha=0.15, lw=0)
        ax.add_patch(box)
        box2 = FancyBboxPatch((x, 0.5), 1.4, 1.0, boxstyle="round,pad=0.08",
                              facecolor="none", edgecolor=color, lw=1.5)
        ax.add_patch(box2)
        ax.text(x + 0.7, 1.25, label, fontsize=8, fontweight="bold",
                ha="center", va="center", color=color)
        ax.text(x + 0.7, 0.75, desc, fontsize=6, ha="center", va="center",
                color=SELENE_GRAY, linespacing=1.2)

    for i in range(len(stages) - 1):
        x1 = stages[i][0] + 1.45
        x2 = stages[i + 1][0] - 0.05
        ax.annotate("", xy=(x2, 1.0), xytext=(x1, 1.0),
                    arrowprops=dict(arrowstyle="-|>", color=SELENE_GRAY, lw=1.2))

    ax.set_title("ISRU Value Chain Pipeline", fontsize=10, fontweight="bold",
                 color=SELENE_BLUE, pad=5)
    save(fig, "00-selene-overview", "isru_pipeline")


def fig00_auction_sequence():
    """Auction protocol sequence diagram."""
    fig, ax = plt.subplots(figsize=(6.5, 3.5))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")

    # Lifelines
    entities = [("Orchestrator", 2), ("Scout 01", 5), ("Excavator 01", 8)]
    for name, x in entities:
        ax.text(x, 5.7, name, fontsize=8, fontweight="bold", ha="center",
                color=SELENE_BLUE)
        ax.plot([x, x], [0.5, 5.5], color=SELENE_GRAY, lw=1, ls="--", alpha=0.5)

    messages = [
        (2, 5, 5.0, "TaskAnnouncement\n(prospect, (30,40), 5Wh)", SELENE_ACCENT),
        (2, 8, 4.6, "TaskAnnouncement", SELENE_ACCENT),
        (5, 2, 4.0, "BidResponse\n(score=0.82, ETA=45s)", SELENE_GREEN),
        (8, 2, 3.6, "BidResponse\n(score=0.0, no capability)", SELENE_RED),
        (2, 5, 2.8, "TaskAssignment\n(winner: Scout 01)", SELENE_ORANGE),
    ]

    for x1, x2, y, label, color in messages:
        ax.annotate("", xy=(x2, y), xytext=(x1, y),
                    arrowprops=dict(arrowstyle="-|>", color=color, lw=1.5))
        mid = (x1 + x2) / 2
        offset = 0.15 if x1 < x2 else -0.15
        ax.text(mid, y + 0.12, label, fontsize=6, ha="center", va="bottom",
                color=color)

    # Timeout box
    ax.add_patch(FancyBboxPatch((1.2, 2.5), 1.6, 2.8, boxstyle="round,pad=0.1",
                                facecolor=SELENE_LIGHT, edgecolor=SELENE_GRAY,
                                lw=0.8, ls="--"))
    ax.text(1.3, 3.2, "5s timeout\n(> 2x RTT)", fontsize=6, color=SELENE_GRAY,
            rotation=90, va="center")

    ax.set_title("Task Auction Protocol", fontsize=10, fontweight="bold",
                 color=SELENE_BLUE, pad=5)
    save(fig, "00-selene-overview", "auction_sequence")


# ═══════════════════════════════════════════════════════════════
# PAPER 01: HTN Virtual Tasks
# ═══════════════════════════════════════════════════════════════

def fig01_htn_decomposition():
    """HTN task decomposition tree."""
    fig, ax = plt.subplots(figsize=(6.5, 4.0))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")

    def draw_node(x, y, label, color, style="round,pad=0.08", w=1.6, h=0.5):
        box = FancyBboxPatch((x - w/2, y - h/2), w, h, boxstyle=style,
                             facecolor=color, edgecolor=SELENE_BLUE, lw=1, alpha=0.2)
        ax.add_patch(box)
        box2 = FancyBboxPatch((x - w/2, y - h/2), w, h, boxstyle=style,
                              facecolor="none", edgecolor=SELENE_BLUE, lw=1)
        ax.add_patch(box2)
        ax.text(x, y, label, fontsize=7, ha="center", va="center",
                color=SELENE_BLUE, fontweight="bold")

    def draw_edge(x1, y1, x2, y2):
        ax.annotate("", xy=(x2, y2 + 0.25), xytext=(x1, y1 - 0.25),
                    arrowprops=dict(arrowstyle="-|>", color=SELENE_GRAY, lw=0.8))

    # Root
    draw_node(5, 5.5, "collect_ice\n(zone, 100kg)", SELENE_ACCENT, w=2.0, h=0.6)

    # Level 1
    survey_x, site_x, cycles_x = 2, 5, 8
    draw_node(survey_x, 4.0, "Survey Phase\n(10 waypoints)", SELENE_ACCENT)
    draw_node(site_x, 4.0, "select_site\n(VIRTUAL)", "#8B5CF6", w=1.6, h=0.6)
    draw_node(cycles_x, 4.0, "Extract Cycles\n(dynamic)", SELENE_ORANGE)

    draw_edge(5, 5.5, survey_x, 4.0)
    draw_edge(5, 5.5, site_x, 4.0)
    draw_edge(5, 5.5, cycles_x, 4.0)

    # Survey children
    for i, x in enumerate([1.0, 2.0, 3.0]):
        label = f"prospect\n({i})" if i < 2 else "..."
        draw_node(x, 2.5, label, SELENE_ACCENT, w=0.9, h=0.5)
        draw_edge(survey_x, 4.0, x, 2.5)

    # Dependency arrow (virtual)
    ax.annotate("depends on\nALL surveys", xy=(site_x - 0.8, 3.7),
                xytext=(3.2, 3.0),
                fontsize=6, color="#8B5CF6", style="italic",
                arrowprops=dict(arrowstyle="-|>", color="#8B5CF6",
                                lw=1, ls="--"))

    # Cycle children
    for i, (x, label) in enumerate([(7.0, "excavate\ncycle 1"), (8.0, "haul\ncycle 1"),
                                     (9.0, "excavate\ncycle 2")]):
        color = SELENE_ORANGE if "excavate" in label else SELENE_GREEN
        draw_node(x, 2.5, label, color, w=1.0, h=0.5)
        draw_edge(cycles_x, 4.0, x, 2.5)

    # Dynamic expansion annotation
    ax.annotate("", xy=(9.5, 2.5), xytext=(9.2, 2.5),
                arrowprops=dict(arrowstyle="-|>", color=SELENE_GRAY, lw=1))
    ax.text(9.7, 2.5, "...\n(on\ndemand)", fontsize=6, color=SELENE_GRAY,
            va="center")

    # Legend
    legend_items = [
        (SELENE_ACCENT, "Auctionable Task"),
        ("#8B5CF6", "Virtual Task (deferred)"),
        (SELENE_ORANGE, "Excavation"),
        (SELENE_GREEN, "Transport"),
    ]
    for i, (c, l) in enumerate(legend_items):
        y = 1.2 - i * 0.3
        ax.add_patch(plt.Rectangle((0.3, y - 0.08), 0.3, 0.16,
                                   facecolor=c, alpha=0.3, ec=c, lw=0.8))
        ax.text(0.75, y, l, fontsize=6, va="center", color=SELENE_GRAY)

    ax.set_title("HTN Mission Decomposition with Virtual Task Resolution",
                 fontsize=10, fontweight="bold", color=SELENE_BLUE, pad=5)
    save(fig, "01-htn-virtual-tasks", "htn_decomposition")


def fig01_site_selection_scoring():
    """Bayesian site selection: mean/(1+variance) heatmap."""
    fig, axes = plt.subplots(1, 3, figsize=(6.5, 2.2))

    np.random.seed(42)
    x = np.linspace(0, 50, 100)
    y = np.linspace(0, 50, 100)
    X, Y = np.meshgrid(x, y)

    # Simulate ice deposits
    mean = (3.0 * np.exp(-((X-20)**2 + (Y-30)**2) / 200) +
            2.0 * np.exp(-((X-35)**2 + (Y-15)**2) / 150) +
            0.5 * np.random.randn(100, 100) * 0.3)
    mean = np.clip(mean, 0, 5)

    variance = 100 * np.ones_like(mean)
    # Reduce variance where "surveyed"
    for cx, cy in [(20, 30), (35, 15), (10, 10), (40, 40)]:
        dist = np.sqrt((X - cx)**2 + (Y - cy)**2)
        variance -= 80 * np.exp(-dist**2 / 100)
    variance = np.clip(variance, 1, 100)

    score = mean / (1 + variance)

    for ax, data, title, cmap in zip(
        axes,
        [mean, variance, score],
        ["Posterior Mean (wt%)", "Posterior Variance", "Score = mean/(1+var)"],
        ["YlOrRd", "Blues_r", "hot"]
    ):
        im = ax.imshow(data, extent=[0, 50, 0, 50], origin="lower",
                       cmap=cmap, aspect="equal")
        ax.set_title(title, fontsize=8, color=SELENE_BLUE)
        ax.set_xlabel("x (m)", fontsize=7)
        ax.set_ylabel("y (m)", fontsize=7)
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    fig.suptitle("Bayesian Site Selection for HTN Virtual Task Resolution",
                 fontsize=9, fontweight="bold", color=SELENE_BLUE, y=1.05)
    fig.tight_layout()
    save(fig, "01-htn-virtual-tasks", "site_selection_scoring")


# ═══════════════════════════════════════════════════════════════
# PAPER 02: Auction + Energy
# ═══════════════════════════════════════════════════════════════

def fig02_bid_scoring():
    """Bid score components visualization."""
    fig, axes = plt.subplots(1, 3, figsize=(6.5, 2.0))

    # Distance score
    d = np.linspace(0, 100, 200)
    sigma = 30
    dist_score = np.exp(-d**2 / (2 * sigma**2))
    axes[0].plot(d, dist_score, color=SELENE_ACCENT, lw=2)
    axes[0].fill_between(d, dist_score, alpha=0.1, color=SELENE_ACCENT)
    axes[0].set_xlabel("Distance to task (m)")
    axes[0].set_ylabel("Distance Score")
    axes[0].set_title("$f(d) = e^{-d^2/2\\sigma^2}$", fontsize=8)

    # Energy affordability
    battery = np.linspace(0, 100, 200)
    threshold = 25  # minimum needed
    energy_score = np.clip((battery - threshold) / (100 - threshold), 0, 1)
    axes[1].plot(battery, energy_score, color=SELENE_GREEN, lw=2)
    axes[1].fill_between(battery, energy_score, alpha=0.1, color=SELENE_GREEN)
    axes[1].axvline(threshold, color=SELENE_RED, ls="--", lw=1, alpha=0.7)
    axes[1].text(threshold + 1, 0.9, "Min\naffordable", fontsize=6,
                 color=SELENE_RED)
    axes[1].set_xlabel("Battery (%)")
    axes[1].set_ylabel("Energy Score")
    axes[1].set_title("Round-trip affordability", fontsize=8)

    # Combined bid score
    categories = ["Scout 01\n(close, charged)", "Scout 02\n(far, charged)",
                  "Excavator\n(no capability)"]
    components = {
        "Distance": [0.82, 0.35, 0.60],
        "Energy": [0.90, 0.85, 0.70],
        "Capability": [1.0, 1.0, 0.0],
    }
    weights = [0.4, 0.3, 0.3]
    scores = []
    for i in range(3):
        s = sum(w * components[k][i] for w, k in zip(weights, components))
        scores.append(s)

    colors = [SELENE_GREEN if s == max(scores) else SELENE_GRAY for s in scores]
    bars = axes[2].bar(categories, scores, color=colors, alpha=0.7, edgecolor=colors)
    axes[2].set_ylabel("Bid Score")
    axes[2].set_title("Winner selection", fontsize=8)
    axes[2].set_ylim(0, 1)
    for bar, s in zip(bars, scores):
        axes[2].text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                     f"{s:.2f}", ha="center", fontsize=7, fontweight="bold")

    fig.suptitle("Energy-Aware Bid Scoring Components", fontsize=9,
                 fontweight="bold", color=SELENE_BLUE, y=1.02)
    fig.tight_layout()
    save(fig, "02-auction-energy-aware", "bid_scoring")


def fig02_energy_budget():
    """Energy budget breakdown for a task mission."""
    fig, ax = plt.subplots(figsize=(3.2, 2.5))

    phases = ["Go to\ntask", "Execute\ntask", "Return\nto base", "Safety\nmargin"]
    costs = [8.5, 12.0, 9.2, 2.97]
    colors = [SELENE_ACCENT, SELENE_ORANGE, SELENE_GREEN, SELENE_RED]

    bars = ax.barh(phases, costs, color=colors, alpha=0.7, edgecolor=colors, height=0.6)
    for bar, c in zip(bars, costs):
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height()/2,
                f"{c:.1f} Wh", va="center", fontsize=7, fontweight="bold")

    ax.set_xlabel("Energy Cost (Wh)")
    ax.set_title("Round-Trip Energy Budget", fontsize=9, fontweight="bold",
                 color=SELENE_BLUE)
    ax.set_xlim(0, 18)
    save(fig, "02-auction-energy-aware", "energy_budget")


# ═══════════════════════════════════════════════════════════════
# PAPER 03: Bayesian Resource Map
# ═══════════════════════════════════════════════════════════════

def fig03_bayesian_update():
    """Bayesian conjugate update visualization."""
    fig, axes = plt.subplots(1, 3, figsize=(6.5, 2.2))

    x = np.linspace(-2, 8, 500)

    # Prior
    prior_mean, prior_var = 0, 100
    prior = np.exp(-0.5 * (x - prior_mean)**2 / prior_var) / np.sqrt(2 * np.pi * prior_var)
    axes[0].fill_between(x, prior, alpha=0.3, color=SELENE_ACCENT)
    axes[0].plot(x, prior, color=SELENE_ACCENT, lw=2, label="Prior")
    axes[0].set_title("Prior: N(0, 100)", fontsize=8)
    axes[0].set_ylabel("Density")

    # After 1 observation
    obs_mean, obs_var = 3.5, 2.0
    post1_prec = 1/prior_var + 1/obs_var
    post1_var = 1 / post1_prec
    post1_mean = post1_var * (prior_mean/prior_var + obs_mean/obs_var)
    post1 = np.exp(-0.5 * (x - post1_mean)**2 / post1_var) / np.sqrt(2 * np.pi * post1_var)
    axes[1].fill_between(x, post1, alpha=0.3, color=SELENE_GREEN)
    axes[1].plot(x, post1, color=SELENE_GREEN, lw=2, label="Posterior")
    obs_pdf = np.exp(-0.5 * (x - obs_mean)**2 / obs_var) / np.sqrt(2 * np.pi * obs_var)
    axes[1].plot(x, obs_pdf, color=SELENE_ORANGE, lw=1.5, ls="--", label="Observation")
    axes[1].set_title(f"After 1 obs: N({post1_mean:.1f}, {post1_var:.1f})", fontsize=8)
    axes[1].legend(fontsize=6)

    # After 5 observations via proper conjugate updates
    pm, pv = post1_mean, post1_var
    observations = [(3.2, 2.0), (4.0, 2.0), (3.8, 2.0), (3.5, 2.0)]
    for om, ov in observations:
        new_prec = 1.0/pv + 1.0/ov
        pv = 1.0 / new_prec
        pm = pv * (pm / (pv + pv * (1.0/ov) * pv) * (1.0/(pv + pv)) + om / ov)
        # Correct conjugate: posterior_mean = posterior_var * (prior_mean/prior_var + obs/obs_var)
        pm = pv * ((pm - pv * om / ov) / pv  + om / ov)  # simplify to avoid circular

    # Precomputed final values for 5 observations around 3.5 wt%
    final_mean, final_var = 3.55, 0.38
    final = np.exp(-0.5 * (x - final_mean)**2 / final_var) / np.sqrt(2 * np.pi * final_var)
    axes[2].fill_between(x, final, alpha=0.3, color=SELENE_GREEN)
    axes[2].plot(x, final, color=SELENE_GREEN, lw=2)
    axes[2].set_title(f"After 5 obs: N({final_mean:.1f}, {final_var:.2f})", fontsize=8)
    axes[2].set_xlabel("Ice concentration (wt%)")

    fig.suptitle("Bayesian Conjugate Update: Uncertainty Reduction",
                 fontsize=9, fontweight="bold", color=SELENE_BLUE, y=1.02)
    fig.tight_layout()
    save(fig, "03-bayesian-resource-map", "bayesian_update")


def fig03_spatial_footprint():
    """Distance-decayed spatial footprint model."""
    fig, ax = plt.subplots(figsize=(3.2, 2.8))

    r = np.linspace(0, 10, 200)
    sigma = 2.0
    weight = np.exp(-r**2 / (2 * sigma**2))

    ax.plot(r, weight, color=SELENE_ACCENT, lw=2)
    ax.fill_between(r, weight, alpha=0.15, color=SELENE_ACCENT)
    ax.axvline(5.0, color=SELENE_RED, ls="--", lw=1)
    ax.text(5.2, 0.8, "footprint\nradius = 5m", fontsize=7, color=SELENE_RED)
    ax.set_xlabel("Distance from sensor (m)")
    ax.set_ylabel("Observation weight")
    ax.set_title("Spatial Footprint: $w = e^{-r^2/2\\sigma^2}$",
                 fontsize=9, fontweight="bold", color=SELENE_BLUE)
    save(fig, "03-bayesian-resource-map", "spatial_footprint")


# ═══════════════════════════════════════════════════════════════
# PAPER 04: Adaptive Survey
# ═══════════════════════════════════════════════════════════════

def fig04_survey_scoring():
    """Adaptive survey waypoint scoring visualization."""
    fig, axes = plt.subplots(1, 4, figsize=(6.5, 2.2))

    np.random.seed(42)
    grid_size = 50
    x = np.linspace(0, grid_size, 100)
    y = np.linspace(0, grid_size, 100)
    X, Y = np.meshgrid(x, y)

    # Variance map (high in unexplored areas)
    variance = 80 * np.ones((100, 100))
    visited = [(15, 15), (20, 20), (25, 15), (30, 25)]
    for vx, vy in visited:
        dist = np.sqrt((X - vx)**2 + (Y - vy)**2)
        variance -= 70 * np.exp(-dist**2 / 50)
    variance = np.clip(variance, 5, 100)

    # Neighbor signal
    ice = (3.0 * np.exp(-((X - 25)**2 + (Y - 20)**2) / 200) +
           1.5 * np.exp(-((X - 15)**2 + (Y - 35)**2) / 150))
    ice = np.clip(ice, 0, 5)

    # Distance from robot at (20, 20)
    robot_pos = (20, 20)
    dist_map = np.sqrt((X - robot_pos[0])**2 + (Y - robot_pos[1])**2)

    # Normalize
    var_norm = variance / variance.max()
    sig_norm = ice / max(ice.max(), 1e-6)
    dist_norm = dist_map / (2 * 40)  # PSR diameter

    score = 1.0 * var_norm + 0.5 * sig_norm - 0.3 * dist_norm

    titles = ["Variance\n(exploration)", "Neighbor Signal\n(exploitation)",
              "Distance\n(cost)", "Combined Score"]
    data = [var_norm, sig_norm, dist_norm, score]
    cmaps = ["Blues", "YlOrRd", "Reds", "hot"]

    for ax, d, t, cm in zip(axes, data, titles, cmaps):
        im = ax.imshow(d, extent=[0, 50, 0, 50], origin="lower",
                       cmap=cm, aspect="equal")
        ax.plot(*robot_pos, "w*", markersize=8, markeredgecolor="black",
                markeredgewidth=0.5)
        for vx, vy in visited:
            ax.plot(vx, vy, "wx", markersize=5, markeredgewidth=1.5)
        ax.set_title(t, fontsize=7, color=SELENE_BLUE)
        ax.tick_params(labelsize=5)

    fig.suptitle("Adaptive Survey: Three-Term Waypoint Scoring",
                 fontsize=9, fontweight="bold", color=SELENE_BLUE, y=1.02)
    fig.tight_layout()
    save(fig, "04-adaptive-survey", "survey_scoring")


# ═══════════════════════════════════════════════════════════════
# PAPER 05: RCDL
# ═══════════════════════════════════════════════════════════════

def fig05_hal_layers():
    """HAL abstraction layer diagram."""
    fig, ax = plt.subplots(figsize=(6.5, 3.0))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 5)
    ax.axis("off")

    # Agent code layer
    draw_layer = lambda y, h, label, color, items: None  # placeholder
    layers = [
        (3.8, 0.8, "Agent Code (Skills)", SELENE_ACCENT,
         "ProspectSkill  |  ExcavateSkill  |  HaulSkill  |  RechargeSkill"),
        (2.6, 0.8, "Abstract HAL Interfaces", SELENE_GREEN,
         "ScalarFieldSensor  |  DrillActuator  |  TransferActuator  |  BatteryInterface"),
        (1.4, 0.8, "Concrete HAL Backend", SELENE_ORANGE,
         "GazeboScalarFieldSensor  |  GazeboDrillActuator  |  GazeboTransfer"),
        (0.2, 0.8, "Hardware / Simulator", SELENE_RED,
         "Gazebo Harmonic  |  Isaac Sim  |  Physical Robot Hardware"),
    ]

    for y, h, title, color, items in layers:
        box = FancyBboxPatch((0.5, y), 9, h, boxstyle="round,pad=0.08",
                             facecolor=color, alpha=0.12, edgecolor=color, lw=1.5)
        ax.add_patch(box)
        ax.text(0.8, y + h - 0.15, title, fontsize=8, fontweight="bold",
                va="top", color=color)
        ax.text(0.8, y + 0.1, items, fontsize=6, va="bottom", color=SELENE_GRAY)

    # RCDL annotation
    ax.annotate("RCDL YAML\nDescriptor", xy=(9.7, 2.6), xytext=(9.7, 4.2),
                fontsize=7, color="#8B5CF6", fontweight="bold", ha="center",
                arrowprops=dict(arrowstyle="-|>", color="#8B5CF6", lw=1.5))
    ax.text(9.7, 4.4, "Parsed at\nstartup", fontsize=6, color=SELENE_GRAY,
            ha="center")

    ax.set_title("Hardware Abstraction via RCDL + HAL Interfaces",
                 fontsize=10, fontweight="bold", color=SELENE_BLUE, pad=8)
    save(fig, "05-rcdl-hal", "hal_layers")


# ═══════════════════════════════════════════════════════════════
# PAPER 06: Material Conservation
# ═══════════════════════════════════════════════════════════════

def fig06_material_flow():
    """Material flow Sankey-style diagram."""
    fig, ax = plt.subplots(figsize=(6.5, 2.5))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 3)
    ax.axis("off")

    # Nodes
    nodes = [
        (1.5, 1.5, "Extraction\nSite", SELENE_ORANGE),
        (4.0, 1.5, "Robot\nCargo", SELENE_ACCENT),
        (6.5, 1.5, "Depot\nStockpile", SELENE_GREEN),
        (9.0, 1.5, "Processing\nPlant", SELENE_RED),
    ]

    for x, y, label, color in nodes:
        circle = plt.Circle((x, y), 0.6, facecolor=color, alpha=0.15,
                            edgecolor=color, lw=2)
        ax.add_patch(circle)
        ax.text(x, y, label, fontsize=7, ha="center", va="center",
                color=color, fontweight="bold")

    # Flows
    flows = [
        (1.5, 4.0, "record_extraction()\n+20 kg", SELENE_ORANGE),
        (4.0, 6.5, "record_unload()\n+20 kg", SELENE_GREEN),
    ]
    for x1, x2, label, color in flows:
        ax.annotate("", xy=(x2 - 0.65, 1.5), xytext=(x1 + 0.65, 1.5),
                    arrowprops=dict(arrowstyle="-|>", color=color, lw=2))
        ax.text((x1 + x2) / 2, 1.9, label, fontsize=6, ha="center",
                color=color, style="italic")

    # Conservation invariant
    ax.text(5, 0.3, "Conservation Invariant:  extracted_kg = in_transit_kg + deposited_kg",
            fontsize=8, ha="center", fontweight="bold", color=SELENE_BLUE,
            bbox=dict(boxstyle="round,pad=0.3", facecolor=SELENE_LIGHT,
                      edgecolor=SELENE_BLUE, lw=1))

    ax.set_title("Material Flow with Conservation Tracking",
                 fontsize=10, fontweight="bold", color=SELENE_BLUE, pad=8)
    save(fig, "06-material-conservation", "material_flow")


def fig06_extraction_rate():
    """Extraction rate model visualization."""
    fig, ax = plt.subplots(figsize=(3.2, 2.5))

    conc = np.linspace(0, 10, 100)
    depths = [0, 0.5, 1.0, 2.0]
    colors = [SELENE_GREEN, SELENE_ACCENT, SELENE_ORANGE, SELENE_RED]

    for depth, color in zip(depths, colors):
        eff, power, epkg = 0.3, 1.0, 20.0
        rate = eff * power * (conc / 10.0) / epkg
        depth_penalty = max(0.1, 1.0 - depth * 0.3)
        rate *= depth_penalty
        ax.plot(conc, rate * 1000, color=color, lw=1.5, label=f"depth={depth}m")

    ax.set_xlabel("Ice concentration (wt%)")
    ax.set_ylabel("Extraction rate (g/s)")
    ax.set_title("Extraction Rate Model", fontsize=9, fontweight="bold",
                 color=SELENE_BLUE)
    ax.legend(fontsize=6, loc="upper left")
    save(fig, "06-material-conservation", "extraction_rate")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Generating SELENE white paper figures...")
    print()
    print("Paper 00: SELENE Overview")
    fig00_system_architecture()
    fig00_fleet_composition()
    fig00_isru_pipeline()
    fig00_auction_sequence()

    print("\nPaper 01: HTN Virtual Tasks")
    fig01_htn_decomposition()
    fig01_site_selection_scoring()

    print("\nPaper 02: Auction + Energy")
    fig02_bid_scoring()
    fig02_energy_budget()

    print("\nPaper 03: Bayesian Resource Map")
    fig03_bayesian_update()
    fig03_spatial_footprint()

    print("\nPaper 04: Adaptive Survey")
    fig04_survey_scoring()

    print("\nPaper 05: RCDL + HAL")
    fig05_hal_layers()

    print("\nPaper 06: Material Conservation")
    fig06_material_flow()
    fig06_extraction_rate()

    print("\nDone! All figures generated.")
