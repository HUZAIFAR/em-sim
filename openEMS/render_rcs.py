#!/usr/bin/env python3
"""
Render RCS visuals from an openEMS plane-wave scattering solve.

  field mode:  read Et_*.vtr (z=0 cut-plane, TOTAL field = incident+scattered) ->
               a scattered-field ANIMATION gif (signed Ez wavefronts) + a steady |E| still.
  lobe  mode:  read rcs_lobe_<tag>.csv (theta,phi,dbsm grid) -> a rotating 3-D scattering-lobe gif.

Usage:
  render_rcs.py field <sim_dir>  <out_base> "<title>"
  render_rcs.py lobe  <lobe_csv> <out_base> "<title>"

Writes into the project fullwave_figures/. Fail-soft: prints an error and exits non-zero.
Run with the Anaconda python (has matplotlib + pyvista + imageio).
"""
import os, sys, glob, csv
import numpy as np

# --- Windows software-OpenGL shim (must run BEFORE pyvista/vtk import; lobe mode renders) ---
# Headless/disconnected Windows sessions have no usable system OpenGL pixel format, so
# VTK off-screen rendering crashes. Preload Mesa's software opengl32.dll (llvmpipe) so
# rendering works in any session. No-op on macOS/Linux / if Mesa absent. (See render_field.py.)
if os.name == "nt":
    try:
        import ctypes
        _mesa_dir = os.environ.get("OPENEMS_MESA_GL", r"C:\opt\mesa")
        _mesa_gl = os.path.join(_mesa_dir, "opengl32.dll")
        if os.path.isfile(_mesa_gl):
            os.add_dll_directory(_mesa_dir)
            ctypes.WinDLL(_mesa_gl)
            os.environ.setdefault("GALLIUM_DRIVER", "llvmpipe")
    except Exception:
        pass

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fullwave_figures")
HERE = os.path.dirname(os.path.abspath(__file__))
os.makedirs(OUT, exist_ok=True)

MODE  = sys.argv[1] if len(sys.argv) > 1 else "field"
_SCR  = os.environ.get("OPENEMS_SCRATCH") or (r"C:\openems_scratch" if os.name == "nt" else "/tmp")
ARG   = sys.argv[2] if len(sys.argv) > 2 else os.path.join(_SCR, "rcs_sim_bare")
BASE  = sys.argv[3] if len(sys.argv) > 3 else "rcs_field"
TITLE = sys.argv[4] if len(sys.argv) > 4 else "openEMS RCS"

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import imageio.v2 as imageio


def _read_geo():
    """shape, size1, size2 (mm), inc(deg), x-extent(mm) written by rcs_run.m."""
    try:
        parts = open(os.path.join(HERE, "rcs_geo.txt")).read().split()
        return parts[0], float(parts[1]), float(parts[2]), float(parts[3])
    except Exception:
        return "sphere", 15.0, 15.0, 0.0


def _draw_target(ax, shape, s1, s2):
    if shape in ("sphere", "cylinder"):
        # on the z=0 cut both are a circle of radius s1
        ax.add_patch(plt.Circle((0, 0), s1, fill=False, ec="#e7f0eb", lw=1.6, alpha=0.9))
    elif shape == "dihedral":
        # arms along -x and -y, thickness tp (matches rcs_run.m geometry)
        tp = max(2.0, 0.06 * s1)
        ax.add_patch(plt.Rectangle((-s1, -tp), s1, tp, fill=True, fc="#c9a36a", ec="#e7f0eb", lw=1.2, alpha=0.85))
        ax.add_patch(plt.Rectangle((-tp, -s1), tp, s1, fill=True, fc="#c9a36a", ec="#e7f0eb", lw=1.2, alpha=0.85))
    elif shape == "import":
        # imported CAD mesh: draw its bounding-box silhouette (half-extent s1) as a dashed outline
        ax.add_patch(plt.Rectangle((-s1, -s1), 2 * s1, 2 * s1, fill=False, ec="#e7f0eb", lw=1.3, ls="--", alpha=0.75))
    else:  # plate: normal +x (in the y-z plane) -> on the z=0 plane it is a thin bar along y
        tp = max(2.0, 0.06 * max(s1, s2) / 2)
        ax.add_patch(plt.Rectangle((-tp / 2, -s1 / 2), tp, s1, fill=True, fc="#c9a36a", ec="#e7f0eb", lw=1.2, alpha=0.85))


def _has3vec(assoc):
    for n in assoc.keys():
        a = assoc[n]
        if getattr(a, "ndim", 0) == 2 and a.shape[1] == 3:
            return True
    return False


def _plane(grid):
    """Return (x, y, Ez[ny,nx], mag[ny,nx]) from a z=0 RectilinearGrid .vtr.
    openEMS may store the E-vector as either point OR cell data; normalise to point data
    so the point-count always matches grid.dimensions before reshaping."""
    if not _has3vec(grid.point_data) and _has3vec(grid.cell_data):
        try: grid = grid.cell_data_to_point_data()
        except Exception: pass
    nx, ny, nz = grid.dimensions
    arr = None
    for n in grid.point_data.keys():
        a = grid.point_data[n]
        if getattr(a, "ndim", 0) == 2 and a.shape[1] == 3:
            arr = a; break
    if arr is None or arr.shape[0] != nx * ny * nz:
        return None
    x = np.asarray(grid.x) * 1000.0; y = np.asarray(grid.y) * 1000.0   # openEMS .vtr coords are in metres -> mm
    ez = arr[:, 2].reshape((nx, ny, max(nz, 1)), order="F")[:, :, 0].T
    mg = np.linalg.norm(arr, axis=1).reshape((nx, ny, max(nz, 1)), order="F")[:, :, 0].T
    return x, y, ez, mg


def render_field(sim_dir, base, title):
    import pyvista as pv
    files = sorted(glob.glob(os.path.join(sim_dir, "Et_*.vtr")))
    if not files:
        sys.exit(f"No Et_*.vtr frames in {sim_dir}")
    shape, s1, s2, inc = _read_geo()

    # pass 1: peak |Ez| per sampled frame -> symmetric colour scale + active window
    samp = list(range(0, len(files), max(1, len(files) // 120)))
    peaks, gmax = {}, 0.0
    envelope = None; xg = yg = None
    for i in samp:
        pl = _plane(pv.read(files[i]))
        if pl is None: continue
        xg, yg, ez, mg = pl
        pk = float(np.abs(ez).max())
        peaks[i] = pk; gmax = max(gmax, pk)
        envelope = mg if envelope is None else np.maximum(envelope, mg)
    if gmax <= 0:
        sys.exit("No field in dumps.")
    active = [i for i in samp if peaks.get(i, 0) > 0.06 * gmax] or samp
    lo, hi = active[0], active[-1]
    sel = sorted(set(np.linspace(lo, hi, 60).astype(int)))
    A = 0.85 * gmax

    def _fig(x, y, C, cmap, vmin, vmax, subtitle):
        fig, ax = plt.subplots(figsize=(6.6, 5.2), dpi=100)
        fig.patch.set_facecolor("#0d1117"); ax.set_facecolor("#0d1117")
        ax.pcolormesh(x, y, C, cmap=cmap, vmin=vmin, vmax=vmax, shading="auto")
        _draw_target(ax, shape, s1, s2)
        ax.set_aspect("equal"); ax.set_xlabel("x (mm)"); ax.set_ylabel("y (mm)")
        for sp in ax.spines.values(): sp.set_color("#5d645f")
        ax.tick_params(colors="#9cc2b5"); ax.xaxis.label.set_color("#9cc2b5"); ax.yaxis.label.set_color("#9cc2b5")
        ax.set_title(title + "  -  " + subtitle, color="#e7f0eb", fontsize=10)
        # incidence arrow: wave travels along k = (cos inc, sin inc), drawn near the upwind corner
        ki, kj = np.cos(np.radians(inc)), np.sin(np.radians(inc))
        span = x.max() - x.min()
        ax0 = x.min() + 0.10 * span - 0.08 * span * ki
        ay0 = y.max() * 0.82 - 0.08 * span * kj
        ax.annotate("", xy=(ax0 + 0.16 * span * ki, ay0 + 0.16 * span * kj), xytext=(ax0, ay0),
                    arrowprops=dict(arrowstyle="-|>", color="#3ddc97", lw=2))
        ax.text(x.min() + 0.02 * span, y.max() * 0.92, "incident", color="#3ddc97", fontsize=8)
        fig.tight_layout()
        fig.canvas.draw()
        img = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
        plt.close(fig)
        return img

    frames = []
    for i in sel:
        pl = _plane(pv.read(files[i]))
        if pl is None: continue
        x, y, ez, mg = pl
        frames.append(_fig(x, y, ez, "RdBu_r", -A, A, "total field E_z (incident + scattered), wavefronts"))
    imageio.mimsave(os.path.join(OUT, base + ".gif"), frames, duration=0.08, loop=0)

    # steady still: time-max |E| envelope (shows the shadow behind + backscatter lobe)
    ec = max(float(envelope.max()) * 0.9, 1e-12)
    still = _fig(xg, yg, envelope, "turbo", 0.0, ec, "peak |E| envelope (shadow + backscatter)")
    imageio.imwrite(os.path.join(OUT, base + "_still.png"), still)
    print("field ->", base + ".gif,", base + "_still.png (", len(frames), "frames )")


def render_lobe(lobe_csv, base, title):
    import pyvista as pv
    rows = list(csv.reader(open(lobe_csv)))[1:]
    if not rows:
        sys.exit("empty lobe csv")
    th = sorted(set(float(r[0]) for r in rows))
    ph = sorted(set(float(r[1]) for r in rows))
    nt, npw = len(th), len(ph)
    ti = {v: i for i, v in enumerate(th)}; pi = {v: i for i, v in enumerate(ph)}
    G = np.full((nt, npw), -120.0)
    for r in rows:
        G[ti[float(r[0])], pi[float(r[1])]] = float(r[2])
    dmin, dmax = float(G.min()), float(G.max())
    rn = (G - dmin) / max(dmax - dmin, 1e-9)          # 0..1
    rr = 0.18 + 0.82 * rn                              # keep a small core so nulls are visible
    TH = np.radians(np.array(th))[:, None]
    PH = np.radians(np.array(ph))[None, :]
    X = rr * np.sin(TH) * np.cos(PH)
    Y = rr * np.sin(TH) * np.sin(PH)
    Z = rr * np.cos(TH) * np.ones_like(PH)
    grid = pv.StructuredGrid(X, Y, Z)
    grid["RCS (dBsm)"] = G.ravel(order="F") if grid.n_points == G.size else G.T.ravel()
    pv.OFF_SCREEN = True
    frames = []
    az = list(range(0, 360, 15))
    for a in az:
        p = pv.Plotter(off_screen=True, window_size=(640, 560))
        p.set_background("#0d1117")
        p.add_mesh(grid, scalars="RCS (dBsm)", cmap="turbo", smooth_shading=True,
                   scalar_bar_args={"title": "RCS (dBsm)", "color": "white"})
        # incidence direction marker (+x)
        p.add_mesh(pv.Arrow(start=(-1.7, 0, 0), direction=(1, 0, 0), scale=0.6), color="#3ddc97")
        r = 3.4
        p.camera_position = [(r*np.cos(np.radians(a)), r*np.sin(np.radians(a)), 1.5), (0, 0, 0), (0, 0, 1)]
        p.add_text(title + " - 3-D scattering lobe", font_size=10, color="white")
        fp = os.path.join(OUT, "_lobe_tmp.png")
        p.screenshot(fp); p.close()
        frames.append(imageio.imread(fp))
    imageio.mimsave(os.path.join(OUT, base + "_lobe.gif"), frames, duration=0.1, loop=0)
    imageio.imwrite(os.path.join(OUT, base + "_lobe.png"), frames[len(frames) // 8])
    for fp in glob.glob(os.path.join(OUT, "_lobe_tmp.png")):
        os.remove(fp)
    print("lobe ->", base + "_lobe.gif,", base + "_lobe.png (", len(frames), "views )")


if MODE == "field":
    render_field(ARG, BASE, TITLE)
elif MODE == "lobe":
    render_lobe(ARG, BASE, TITLE)
else:
    sys.exit("unknown mode: " + MODE)
