#!/usr/bin/env python3
"""
Render openEMS E-field dumps into a 3-D coloured field view of the wave
propagating through a horizontal MXene-coated-wood waveguide.

Reads Et_*.vtr frames from /tmp/wg_sim, writes into the project fullwave_figures/:
    field_animation.gif, field_animation.mp4, field_still.png

Run with the python that has pyvista (Anaconda):
    /opt/anaconda3/bin/python "<path>/openEMS/render_field.py"
"""
import glob, os, sys, re
import numpy as np

# --- Windows software-OpenGL shim (must run BEFORE pyvista/vtk import) -------------
# In a headless / disconnected Windows session the system OpenGL has no usable pixel
# format, so VTK off-screen rendering CRASHES (not just renders black). Preload Mesa's
# software opengl32.dll (llvmpipe) so rendering works in ANY session state. No-op on
# macOS/Linux and no-op if Mesa isn't present. Dir via OPENEMS_MESA_GL (default C:\opt\mesa).
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

_SCR = os.environ.get("OPENEMS_SCRATCH") or (r"C:\openems_scratch" if os.name == "nt" else "/tmp")
SIM = os.path.join(_SCR, "wg_sim")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fullwave_figures")
BASE  = sys.argv[1] if len(sys.argv) > 1 else "field_animation"
TITLE = sys.argv[2] if len(sys.argv) > 2 else "openEMS E-field"
MODE  = sys.argv[3] if len(sys.argv) > 3 else "full"   # "full" = gif+still, "loss" = power-loss still only

# which obstacle shape is in the guide (so we can DRAW it): read it from wg_params.m
def _read_shape():
    try:
        txt = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "wg_params.m")).read()
        m = re.search(r"p_shape\s*=\s*'([^']*)'", txt)
        return m.group(1) if m else "waveguide"
    except Exception:
        return "waveguide"
SHAPE = sys.argv[4] if len(sys.argv) > 4 else _read_shape()

try:
    import pyvista as pv
    import imageio.v2 as imageio
except Exception as e:
    sys.exit(f"Missing package: {e}\nInstall:  /opt/anaconda3/bin/pip install pyvista imageio imageio-ffmpeg numpy")

pv.OFF_SCREEN = True
try: pv.global_theme.font.color = "white"      # light text on the dark field background
except Exception: pass
os.makedirs(OUT, exist_ok=True)

# --- field render mode ------------------------------------------------------------
# GPU volume ray-casting (add_volume) renders BLACK on a headless / disconnected
# Windows session, where OpenGL falls back to the GDI-generic (1.1) software driver
# (add_mesh polygons still draw, add_volume does not). So on Windows we default to a
# robust polygon "surface" render (centre cut-planes coloured by |E|), which draws on
# any OpenGL. macOS/Linux keep the volume render UNCHANGED. Override either way with
# OPENEMS_FIELD_RENDER=volume|surface.
_RMODE = os.environ.get("OPENEMS_FIELD_RENDER", "").strip().lower()
USE_SURFACE = (_RMODE == "surface") or (_RMODE != "volume" and os.name == "nt")

files = sorted(glob.glob(os.path.join(SIM, "Et_*.vtr")))
if not files:
    sys.exit(f"No Et_*.vtr frames in {SIM}. Run wg_pipeline_test.m first.")
print(f"{len(files)} field frames found")

def vec(mesh):
    for assoc in (mesh.point_data, mesh.cell_data):
        for n in assoc.keys():
            a = assoc[n]
            if getattr(a, "ndim", 0) == 2 and a.shape[1] == 3:
                return n, assoc
    return None, None

# pass 1: per-frame peak (sampled) -> colour scale + active time window + still frame
idx = list(range(0, len(files), max(1, len(files)//120)))
peaks = {}
gmax = 0.0
for i in idx:
    m = pv.read(files[i]); n, a = vec(m)
    if n is None: continue
    pk = float(np.linalg.norm(a[n], axis=1).max())
    peaks[i] = pk; gmax = max(gmax, pk)
if gmax <= 0: sys.exit("No field found in dumps.")
clim = (0.0, 0.85*gmax)

# active window = frames whose peak is > 6% of global peak
active = [i for i in idx if peaks.get(i, 0) > 0.06*gmax] or idx
still_i = max(active, key=lambda i: peaks[i])
# ~80 evenly spaced frames across the active window
lo, hi = active[0], active[-1]
sel = sorted(set(np.linspace(lo, hi, 80).astype(int)) | {still_i})

bounds = pv.read(files[still_i]).bounds   # xmin,xmax,ymin,ymax,zmin,zmax (whole dumped region)
cx=(bounds[0]+bounds[1])/2; cy=(bounds[2]+bounds[3])/2; cz=(bounds[4]+bounds[5])/2
Lz = bounds[5]-bounds[4]

# the dump now covers guide + surrounding vacuum; map the GUIDE outline into these
# coordinates so we can draw the guide walls and see field that leaks OUT past them.
GUIDE = None
try:
    _n = [float(v) for v in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "render_geo.txt")).read().split()]
    dxmin,dxmax,dymin,dymax,dzmin,dzmax, gx0,gx1,gy0,gy1,gz0,gz1 = _n[:12]
    def _mp(v, vmin, vmax, b0, b1):
        return b0 + (v-vmin)/(vmax-vmin)*(b1-b0) if vmax > vmin else b0
    GUIDE = (_mp(gx0,dxmin,dxmax,bounds[0],bounds[1]), _mp(gx1,dxmin,dxmax,bounds[0],bounds[1]),
             _mp(gy0,dymin,dymax,bounds[2],bounds[3]), _mp(gy1,dymin,dymax,bounds[2],bounds[3]),
             _mp(gz0,dzmin,dzmax,bounds[4],bounds[5]), _mp(gz1,dzmin,dzmax,bounds[4],bounds[5]))
except Exception:
    GUIDE = None

def plot_mesh(mesh, clim_local, title):
    p = pv.Plotter(off_screen=True, window_size=(1320, 640))
    # dark background so ZERO/low intensity (e.g. field escaping a leaky basswood wall)
    # is visible as dark space + faint colour, instead of vanishing into white.
    p.set_background("#0d1117")
    xs=bounds[1]-bounds[0]; ys=bounds[3]-bounds[2]; zs=bounds[5]-bounds[4]
    try:
        if SHAPE in ("sphere", "cylinder", "block"):
            # the object IS this shape (a hollow coated shell) -> draw it TRANSLUCENT so the
            # wave inside is visible, matching "waves inside the object".
            if SHAPE == "sphere":
                shell = pv.Sphere(radius=0.5*min(xs, ys, zs), center=(cx, cy, cz), theta_resolution=48, phi_resolution=48)
            elif SHAPE == "cylinder":
                shell = pv.Cylinder(center=(cx, cy, cz), direction=(0, 0, 1), radius=0.5*min(xs, ys), height=zs, resolution=48)
            else:
                shell = pv.Box(bounds=bounds)
            if not USE_SURFACE:   # translucent fill needs real OpenGL; skip in surface mode
                p.add_mesh(shell, color="#c9a36a", opacity=0.10, smooth_shading=True)
            try:  # clean silhouette only (feature edges), not the full triangulation
                p.add_mesh(shell.extract_feature_edges(), color="#0b6e54", line_width=2)
            except Exception:
                pass
        else:
            gb = GUIDE if GUIDE else bounds   # draw the GUIDE walls (field outside them = leakage)
            box = pv.Box(bounds=gb)
            if not USE_SURFACE:   # translucent fill needs real OpenGL; skip in surface mode
                p.add_mesh(box, color="#c9a36a", opacity=0.12)
            p.add_mesh(box.extract_all_edges(), color="#3ddc97", line_width=4)
            if SHAPE == "reflector":
                p.add_mesh(pv.Box(bounds=(gb[0], gb[1], gb[2], gb[3], gb[5]-0.03*(gb[5]-gb[4]), gb[5])), color="#15b88a", opacity=0.9)
    except Exception:
        if not USE_SURFACE:
            p.add_mesh(pv.Box(bounds=bounds), color="#c9a36a", opacity=0.10)
    sbar = {"title":"|E| (V/m)","vertical":True,"title_font_size":18,"label_font_size":14}
    if USE_SURFACE:
        # Robust polygon render: two centre cut-planes coloured by |E|. Uses only
        # add_mesh (opaque), which draws on any OpenGL incl. headless GDI-generic,
        # where GPU add_volume ray-casting renders black.
        vol = mesh if "|E|" in mesh.point_data else mesh.cell_data_to_point_data()
        shown = False
        for _nm in ("y", "x"):
            try:
                sl = vol.slice(normal=_nm, origin=(cx, cy, cz))
            except Exception:
                sl = None
            if sl is not None and sl.n_points:
                if not shown:
                    p.add_mesh(sl, scalars="|E|", cmap="turbo", clim=clim_local, scalar_bar_args=sbar)
                    shown = True
                else:
                    p.add_mesh(sl, scalars="|E|", cmap="turbo", clim=clim_local, show_scalar_bar=False)
        if not shown:
            p.add_mesh(mesh.slice(normal="y"), scalars="|E|", cmap="turbo", clim=clim_local, scalar_bar_args=sbar)
    else:
        try:
            vol = mesh if "|E|" in mesh.point_data else mesh.cell_data_to_point_data()
            p.add_volume(vol, scalars="|E|", cmap="turbo", clim=clim_local,
                         opacity=[0.0, 0.09, 0.20, 0.38, 0.62, 0.92], scalar_bar_args=sbar)
        except Exception:
            p.add_mesh(mesh.slice(normal="y"), scalars="|E|", cmap="jet", clim=clim_local, scalar_bar_args=sbar)
    # view the guide LYING HORIZONTALLY: look from the +X/+Y front so the long
    # axis (z = length) runs left-to-right across the screen, height (y) is up.
    p.camera_position = [(cx + 0.85*Lz, cy + 0.5*Lz, cz),
                         (cx, cy, cz),
                         (0, 1, 0)]
    p.camera.zoom(1.35)
    try: p.enable_anti_aliasing()
    except Exception: pass
    p.add_text(title, font_size=11, color="white")
    fp = os.path.join(OUT, "_tmp_frame.png")
    p.screenshot(fp); p.close()
    return imageio.imread(fp)

# --- loss-map mode: power-loss density ~ |E|^2 (time-max), single still, no animation ---
if MODE == "loss":
    envq = None; refq = None
    for i in sel:
        m = pv.read(files[i]); n, a = vec(m)
        if n is None: continue
        mag = np.linalg.norm(a[n], axis=1)
        if refq is None: refq = m
        envq = mag.copy() if envq is None else np.maximum(envq, mag)
    if envq is None: sys.exit("No field found for loss map.")
    pw = envq ** 2                     # dissipated power density is proportional to |E|^2
    refq["|E|"] = pw                   # reuse the "|E|" scalar name so plot_mesh works
    lc = (0.0, max(float(pw.max()) * 0.9, 1e-12))
    imageio.imwrite(os.path.join(OUT, BASE + "_loss.png"),
                    plot_mesh(refq, lc, TITLE + "  -  power-loss density ~ |E|^2 (bright = highest loss)"))
    print("loss map ->", BASE + "_loss.png")
    sys.exit(0)

# build the animation (travelling pulse) and accumulate the time-max envelope
frames = []
env = None
ref_mesh = None
for i in sel:
    m = pv.read(files[i]); n, a = vec(m)
    mag = np.linalg.norm(a[n], axis=1); m["|E|"] = mag
    if ref_mesh is None: ref_mesh = m
    env = mag.copy() if env is None else np.maximum(env, mag)
    frames.append(plot_mesh(m, clim, TITLE + "  (travelling wave)"))

imageio.mimsave(os.path.join(OUT, BASE+".gif"), frames, duration=0.07, loop=0)
try:
    imageio.mimsave(os.path.join(OUT, BASE+".mp4"), frames, fps=15, macro_block_size=1)
except Exception as e:
    print("mp4 skipped:", e)

# STILL = time-max ENVELOPE: peak field reached at each point -> shows how the field
# holds up ALONG the guide. Uniform/bright = carried with low loss; fading toward the
# far end = energy lost in the wall.
ref_mesh["|E|"] = env
env_clim = (0.0, max(float(env.max())*0.92, 1e-12))
imageio.imwrite(os.path.join(OUT, BASE+"_still.png"),
                plot_mesh(ref_mesh, env_clim, TITLE + "  -  peak field (bright = carried, fades = lost)"))
for fp in glob.glob(os.path.join(OUT, "_tmp_frame.png")) + glob.glob(os.path.join(OUT, "_f_*.png")):
    os.remove(fp)
print("Done ->", BASE, "in", OUT)
