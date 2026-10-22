"""Static report charts (matplotlib). Palette: validated categorical order,
light mode; series are always legend- and direct-labelled."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0", "#fcfcfb"

# fixed colour per entity, never by rank
ENTITY_COLOR = {
    "median": SERIES[0], "trimmed_mean": SERIES[1], "weighted": SERIES[2], "quorum_median": SERIES[3], "reputation": SERIES[4],
    "mad": SERIES[0], "hampel": SERIES[1], "rolling": SERIES[2], "cusum": SERIES[3], "vol_mad": SERIES[4],
}


def style(ax, title=None, xlabel=None, ylabel=None):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, loc="left", fontsize=11, color=INK, fontweight="bold")
    if xlabel:
        ax.set_xlabel(xlabel, color=INK2, fontsize=9)
    if ylabel:
        ax.set_ylabel(ylabel, color=INK2, fontsize=9)


def figure(w=7.5, h=4.2, ncols=1, nrows=1):
    fig, axes = plt.subplots(nrows, ncols, figsize=(w, h), squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    return fig, axes


def save(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)
