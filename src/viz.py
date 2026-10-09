"""Small matplotlib helpers so every chart in the notebooks looks the same."""
import matplotlib.pyplot as plt

from config import FIGURES

BLUE = "#2a78d6"     # main series / price decreases
ORANGE = "#eb6834"   # second series / price increases
AQUA = "#1baf7a"
INK = "#0b0b0b"
MUTED = "#52514e"
GRID = "#e4e3df"

plt.rcParams.update({
    "figure.dpi": 110,
    "font.size": 10,
    "axes.edgecolor": MUTED,
    "axes.labelcolor": MUTED,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
})


def style(ax, title, xlabel=None, ylabel=None, note=None):
    ax.set_title(title, color=INK, pad=12)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    if note:
        ax.figure.text(0.01, -0.02, note, fontsize=8, color=MUTED, ha="left", va="top")
    return ax


def signed_colors(values):
    """Orange for increases, blue for decreases."""
    return [ORANGE if v >= 0 else BLUE for v in values]


def save(fig, name):
    FIGURES.mkdir(parents=True, exist_ok=True)
    path = FIGURES / f"{name}.png"
    fig.savefig(path, bbox_inches="tight", dpi=150)
    return path
