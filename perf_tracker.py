"""
perf_tracker.py — Full performance telemetry engine for Chronos Time-Lock.

Capabilities
────────────
• Tracks: iteration count, elapsed time, completion %, CPU %, remaining %.
• Autonomous daemon thread samples CPU every `sample_interval` seconds.
• Solver callback records iteration-aligned data points — zero blocking.
• build_graphs() renders 5 chart types to dark-themed PNGs:
    1. Completion % vs Time
    2. CPU Usage % vs Time
    3. Iterations vs Time
    4. Remaining % vs Time
    5. AES decrypt vs Time-Lock decrypt (comparison bar)
• run_delay_benchmark() — background benchmark across multiple delay targets,
  produces a "target vs actual CPU time" scatter/line plot.

Thread-safety
─────────────
All public methods safe from any thread.  Internal state guarded by
threading.Lock — concurrent solver + poller + sampler never race.
"""

from __future__ import annotations

import os
import time
import threading
from typing import Callable, Optional

# ── Optional dependencies ─────────────────────────────────────────────────────
try:
    import psutil as _psutil
    _PSUTIL_OK = True
except ImportError:
    _psutil = None          # type: ignore
    _PSUTIL_OK = False

try:
    import matplotlib
    matplotlib.use('Agg')   # headless / server-safe backend
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    _MPL_OK = True
except ImportError:
    plt = None              # type: ignore
    _MPL_OK = False


# ─────────────────────────────────────────────────────────────────────────────
# Palette — mirrors the app's GitHub-dark theme
# ─────────────────────────────────────────────────────────────────────────────
_BG      = "#0d1117"
_PANEL   = "#161b22"
_BORDER  = "#30363d"
_TEXT    = "#c9d1d9"
_SUB     = "#8b949e"
_BLUE    = "#58a6ff"
_ORANGE  = "#f0883e"
_PURPLE  = "#8957e5"
_GREEN   = "#3fb950"
_RED     = "#f85149"
_YELLOW  = "#d29922"


# ─────────────────────────────────────────────────────────────────────────────
# PerfTracker
# ─────────────────────────────────────────────────────────────────────────────

class PerfTracker:
    """
    One instance per decryption job.

    Parameters
    ----------
    file_id         : UUID string — used in titles and PNG file names.
    total_iters     : expected squarings (puzzle['t']). Used for axis scaling.
    sample_interval : seconds between autonomous CPU daemon ticks.
    """

    def __init__(self, file_id: str,
                 total_iters: int = 0,
                 sample_interval: float = 0.5):
        self.file_id        = file_id
        self.total_iters    = total_iters
        self.sample_interval = sample_interval

        # Samples: {"t": float, "iter": int, "pct": float, "cpu": float}
        self._samples: list[dict] = []
        self._lock      = threading.Lock()
        self._start_ts: float | None = None
        self._stop_ev   = threading.Event()
        self._sampler: threading.Thread | None = None

        # AES baseline for comparison chart
        self.aes_time_ms: float = 0.0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Call just before the solver loop begins."""
        self._start_ts = time.perf_counter()
        if self.sample_interval > 0 and _PSUTIL_OK:
            self._stop_ev.clear()
            self._sampler = threading.Thread(
                target=self._cpu_loop, daemon=True,
                name=f"cpu-sampler-{self.file_id[:8]}")
            self._sampler.start()

    def stop(self) -> None:
        """Call just after the solver loop finishes."""
        self._stop_ev.set()
        if self._sampler:
            self._sampler.join(timeout=2.0)

    # ── Sample ingestion ──────────────────────────────────────────────────────

    def record_sample(self, iteration: int, percentage: float,
                      cpu_override: float | None = None) -> None:
        """
        Record one telemetry data point.  Designed to run inside the
        solver's on_progress callback — adds < 1 µs overhead.
        """
        if self._start_ts is None:
            return
        elapsed = time.perf_counter() - self._start_ts
        cpu     = cpu_override if cpu_override is not None else _cpu_pct()
        with self._lock:
            self._samples.append({
                "t":    elapsed,
                "iter": iteration,
                "pct":  float(percentage),
                "cpu":  cpu,
            })

    def record_aes_baseline(self, duration_ms: float) -> None:
        """Store plain AES-EAX decrypt time for the comparison bar chart."""
        self.aes_time_ms = duration_ms

    # ── Graph rendering ───────────────────────────────────────────────────────

    def build_graphs(self,
                     save_dir: str | None = None,
                     show: bool = False,
                     include_remaining: bool = True,
                     include_comparison: bool = True) -> dict[str, str]:
        """
        Render all performance graphs from collected samples.

        Parameters
        ----------
        save_dir           : directory to write PNGs (None = don't save).
        show               : call plt.show() — for local dev with a display.
        include_remaining  : render the Remaining % chart.
        include_comparison : render the AES vs Time-Lock bar chart.

        Returns
        -------
        dict { graph_key -> absolute_path } — only includes saved files.
        """
        if not _MPL_OK:
            raise RuntimeError(
                "matplotlib is not installed. Run: pip install matplotlib")

        with self._lock:
            samples = list(self._samples)

        if len(samples) < 2:
            return {}

        ts    = [s["t"]    for s in samples]
        pcts  = [s["pct"]  for s in samples]
        iters = [s["iter"] for s in samples]
        cpus  = [s["cpu"]  for s in samples]
        label = self.file_id[:8]
        saved: dict[str, str] = {}

        def _smooth(data, w=5):
            if len(data) < w: return data
            return [sum(data[max(0, i-w+1):i+1])/min(i+1, w) for i in range(len(data))]

        # 1 — Completion % vs Time
        smooth_pcts = _smooth(pcts, 3)
        markers = []
        for target in [25.0, 50.0, 75.0]:
            closest_i = min(range(len(smooth_pcts)), key=lambda i: abs(smooth_pcts[i]-target))
            if abs(smooth_pcts[closest_i] - target) < 15.0:
                markers.append((ts[closest_i], smooth_pcts[closest_i], f"{int(target)}%"))

        saved["completion"] = _save(
            *_line_fig(ts, smooth_pcts,
                       xlabel="Elapsed Time (s)",
                       ylabel="Completion (%)",
                       title=f"Solver Progress  [{label}]",
                       color=_BLUE, ylim=(0, 105), markers=markers),
            save_dir=save_dir, fname=f"{self.file_id}_completion.png", show=show)

        # 2 — CPU Usage % vs Time
        smooth_cpus = _smooth(cpus, 5)
        saved["cpu"] = _save(
            *_line_fig(ts, smooth_cpus,
                       xlabel="Elapsed Time (s)",
                       ylabel="CPU Usage (%)",
                       title=f"CPU Utilisation (Moving Avg)  [{label}]",
                       color=_ORANGE, ylim=(0, 105), peaks=True),
            save_dir=save_dir, fname=f"{self.file_id}_cpu.png", show=show)

        # 3 — Iterations vs Time
        saved["iterations"] = _save(
            *_line_fig(ts, iters,
                       xlabel="Elapsed Time (s)",
                       ylabel="Squarings Completed",
                       title=f"Iterations vs Time  [{label}]",
                       color=_GREEN, ylim=None,
                       yformat_int=True, log_scale=True),
            save_dir=save_dir, fname=f"{self.file_id}_iterations.png", show=show)

        # 4 — Remaining Time Prediction
        if include_remaining:
            rem_times = []
            for t, p in zip(ts, pcts):
                if p < 1.0 or t < 0.1:
                    rem_times.append(0.0)
                else:
                    total_est = t / (p / 100.0)
                    rem_times.append(max(0.0, total_est - t))
            rem_times = _smooth(rem_times, 4)

            saved["remaining"] = _save(
                *_line_fig(ts, rem_times,
                           xlabel="Elapsed Time (s)",
                           ylabel="Remaining Time (s)",
                           title=f"Predicted Remaining Time  [{label}]",
                           color=_PURPLE, ylim=None, yformat_seconds=True),
                save_dir=save_dir, fname=f"{self.file_id}_remaining.png", show=show)

        # 5 — AES vs Time-Lock comparison bar
        if include_comparison and self.aes_time_ms > 0 and ts:
            tlock_ms = ts[-1] * 1000
            saved["comparison"] = _save(
                *_comparison_bar(self.aes_time_ms, tlock_ms,
                                 title=f"AES Decrypt vs Time-Lock  [{label}]"),
                save_dir=save_dir, fname=f"{self.file_id}_comparison.png", show=show)

        return {k: v for k, v in saved.items() if v}

    # ── Accessors ─────────────────────────────────────────────────────────────

    def get_samples(self) -> list[dict]:
        """Thread-safe snapshot of all recorded samples."""
        with self._lock:
            return list(self._samples)

    def elapsed(self) -> float:
        if self._start_ts is None:
            return 0.0
        return time.perf_counter() - self._start_ts

    # ── CPU daemon ────────────────────────────────────────────────────────────

    def _cpu_loop(self) -> None:
        while not self._stop_ev.wait(self.sample_interval):
            if self._start_ts is None:
                continue
            t   = time.perf_counter() - self._start_ts
            cpu = _cpu_pct()
            with self._lock:
                pct = self._samples[-1]["pct"]  if self._samples else 0.0
                itr = self._samples[-1]["iter"] if self._samples else 0
                self._samples.append(
                    {"t": t, "iter": itr, "pct": pct, "cpu": cpu})


# ─────────────────────────────────────────────────────────────────────────────
# Multi-delay benchmark
# ─────────────────────────────────────────────────────────────────────────────

def run_delay_benchmark(
        delays: list[int],
        save_dir: str | None = None,
        show: bool = False,
        done_callback: Callable[[dict[str, str]], None] | None = None,
) -> threading.Thread:
    """
    Spin up a background thread that encrypts + solves a time-lock puzzle at
    each delay value, then renders a "target vs actual" comparison plot.

    Parameters
    ----------
    delays        : e.g. [1, 5, 10, 30]
    save_dir      : PNG output directory (None = don't save).
    show          : plt.show() for local dev.
    done_callback : called with {graph_key -> path} on completion.

    Returns the Thread so you can .join() if needed.
    """

    def _worker():
        # Late import avoids circular dependency when used standalone
        try:
            from crypto import generate_key, generate_puzzle, solve_puzzle_tracked  # type: ignore
        except ImportError:
            if done_callback:
                done_callback({})
            return

        targets: list[float] = []
        actuals: list[float] = []

        for d in delays:
            key    = generate_key()
            puzzle = generate_puzzle(key, d)
            t0     = time.perf_counter()
            solve_puzzle_tracked(
                puzzle["N"], puzzle["a"], puzzle["t"], puzzle["C_K"],
                db_update_func=None,
                update_interval=max(1, puzzle["t"] // 10))
            actuals.append(time.perf_counter() - t0)
            targets.append(float(d))

        paths: dict[str, str] = {}
        if _MPL_OK:
            paths["benchmark"] = _save(
                *_benchmark_chart(targets, actuals),
                save_dir=save_dir,
                fname="benchmark_delay_vs_actual.png",
                show=show)

        if done_callback:
            done_callback(paths)

    th = threading.Thread(target=_worker, daemon=True, name="delay-benchmark")
    th.start()
    return th


# ─────────────────────────────────────────────────────────────────────────────
# Registry — app.py looks up trackers by file_id
# ─────────────────────────────────────────────────────────────────────────────

_REG: dict[str, PerfTracker] = {}
_REG_LOCK = threading.Lock()


def create_tracker(file_id: str,
                   total_iters: int = 0,
                   sample_interval: float = 0.5) -> PerfTracker:
    t = PerfTracker(file_id, total_iters=total_iters,
                    sample_interval=sample_interval)
    with _REG_LOCK:
        _REG[file_id] = t
    return t


def get_tracker(file_id: str) -> PerfTracker | None:
    with _REG_LOCK:
        return _REG.get(file_id)


def remove_tracker(file_id: str) -> None:
    with _REG_LOCK:
        _REG.pop(file_id, None)


def list_trackers() -> list[str]:
    with _REG_LOCK:
        return list(_REG.keys())


# ─────────────────────────────────────────────────────────────────────────────
# Private rendering helpers
# ─────────────────────────────────────────────────────────────────────────────

def _cpu_pct() -> float:
    if not _PSUTIL_OK:
        return 0.0
    try:
        return _psutil.Process().cpu_percent(interval=None)
    except Exception:
        return 0.0


def _apply_theme(ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_facecolor(_PANEL)
    ax.set_title(title,  color=_TEXT,  fontsize=10, pad=10,
                 fontfamily="monospace", fontweight="bold")
    ax.set_xlabel(xlabel, color=_SUB,  fontsize=8.5)
    ax.set_ylabel(ylabel, color=_SUB,  fontsize=8.5)
    ax.tick_params(colors=_SUB, labelsize=8)
    for sp in ax.spines.values():
        sp.set_color(_BORDER)
    ax.grid(axis='y', color='#1c2128', linestyle='--',
            linewidth=0.6, zorder=1)


def _line_fig(xs, ys, xlabel, ylabel, title, color,
              ylim=None, yformat_int=False, yformat_seconds=False,
              log_scale=False, markers=None, peaks=False):
    fig, ax = plt.subplots(figsize=(8.5, 3.8))
    fig.patch.set_facecolor(_BG)
    _apply_theme(ax, title, xlabel, ylabel)

    ax.plot(xs, ys, color=color, linewidth=1.9, zorder=3)
    ax.fill_between(xs, ys, alpha=0.11, color=color, zorder=2)

    if ylim:
        ax.set_ylim(*ylim)

    if log_scale:
        ax.set_yscale('symlog')
        ax.yaxis.set_major_formatter(mticker.LogFormatterSciNotation())
    elif yformat_int:
        ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    elif yformat_seconds:
        ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda v, _: f"{v:.1f}s"))
    else:
        ax.yaxis.set_major_formatter(
            mticker.FormatStrFormatter('%.0f%%'))

    if markers:
        for (mx, my, lbl) in markers:
            ax.plot(mx, my, marker='o', color=_TEXT, markersize=5, zorder=5)
            ax.annotate(lbl, xy=(mx, my), xytext=(-10, 10), textcoords="offset points", color=_TEXT, fontsize=8)

    if peaks and ys:
        px = xs[ys.index(max(ys))]
        py = max(ys)
        ax.plot(px, py, marker='^', color=_RED, markersize=7, zorder=5)
        ax.annotate(f"Peak {py:.1f}%", xy=(px, py), xytext=(-20, 10), textcoords="offset points", color=_RED, fontsize=8)

    # Annotate final value
    if xs and ys:
        if yformat_seconds:
            lbl = f"{ys[-1]:.1f}s"
        elif yformat_int:
            lbl = f"{ys[-1]:,}"
        else:
            lbl = f"{ys[-1]:.1f}%"
        ax.annotate(lbl, xy=(xs[-1], ys[-1]),
                    xytext=(-42, 10), textcoords="offset points",
                    color=color, fontsize=8, fontfamily="monospace",
                    arrowprops=dict(arrowstyle="->", color=color, lw=0.9))

    fig.tight_layout(pad=1.4)
    return fig, ax


def _comparison_bar(aes_ms: float, tlock_ms: float, title: str):
    fig, ax = plt.subplots(figsize=(6, 3.6))
    fig.patch.set_facecolor(_BG)
    _apply_theme(ax, title, "Decryption Method", "Time")

    labels = ["AES-EAX\n(no time-lock)", "Time-Lock\nPuzzle"]
    vals   = [aes_ms, tlock_ms]
    colors = [_GREEN, _PURPLE]

    bars = ax.bar(labels, vals, color=colors, width=0.42,
                  edgecolor=_BORDER, linewidth=0.8, zorder=3)

    # Value labels above bars
    for bar, val in zip(bars, vals):
        lbl = f"{val:,.1f} ms" if val < 2000 else f"{val/1000:,.2f} s"
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max(vals) * 0.025,
                lbl, ha='center', va='bottom',
                color=_TEXT, fontsize=9, fontfamily="monospace")

    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(
            lambda v, _: f"{v/1000:.2f}s" if v >= 1000 else f"{v:.0f}ms"))
    fig.tight_layout(pad=1.4)
    return fig, ax


def _benchmark_chart(targets: list[float], actuals: list[float]):
    fig, ax = plt.subplots(figsize=(8.5, 3.8))
    fig.patch.set_facecolor(_BG)
    _apply_theme(ax,
                 "Multi-Delay Benchmark  ·  Target vs Actual CPU Time",
                 "Target Delay (s)", "Actual Elapsed (s)")

    # Ideal 1:1 reference
    mx = max(targets) * 1.15
    ax.plot([0, mx], [0, mx], color=_BORDER, linestyle='--',
            linewidth=1.1, zorder=2, label="Ideal (1:1)")

    ax.plot(targets, actuals, color=_BLUE, linewidth=2.0,
            marker='o', markersize=5.5, zorder=4, label="Measured")

    for t, a in zip(targets, actuals):
        ax.annotate(f"{a:.2f}s", xy=(t, a),
                    xytext=(5, 7), textcoords="offset points",
                    color=_SUB, fontsize=7.5, fontfamily="monospace")

    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.1f'))
    ax.legend(facecolor=_PANEL, edgecolor=_BORDER,
              labelcolor=_TEXT, fontsize=8.5, framealpha=0.9)
    fig.tight_layout(pad=1.4)
    return fig, ax


def _save(fig, ax, save_dir: str | None, fname: str, show: bool) -> str:
    path = ""
    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
        path = os.path.join(save_dir, fname)
        fig.savefig(path, dpi=130, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
    if show:
        plt.show()
    plt.close(fig)
    return path