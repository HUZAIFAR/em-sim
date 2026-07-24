#!/usr/bin/env python3
"""
Render the openEMS FREQUENCY-DOMAIN E-field DFT dump (Ef_*.vtr from /tmp/wg_sim)
into a single steady-state |E| magnitude still, with the guide outline overlaid.

Used when the Full-wave tab's "Field view" is set to Frequency-domain. openEMS is
a time-domain (FDTD) solver; this reads its on-the-fly DFT dump at the band-centre
frequency, so the picture is the steady-state |E| at one frequency (not an animation).

Output:  fullwave_figures/<base>_still.png   (default base = field_guide)
Run with the python that has pyvista (Anaconda).
"""
import glob, os, sys
import numpy as np

# --- Windows software-OpenGL shim (must run BEFORE pyvista/vtk import) -------------
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

HERE  = os.path.dirname(os.path.abspath(__file__))
_SCR  = os.environ.get("OPENEMS_SCRATCH") or (r"C:\openems_scratch" if os.name == "nt" else "/tmp")
SIM   = os.path.join(_SCR, "wg_sim")
OUT   = os.path.join(os.path.dirname(HERE), "fullwave_figures")
BASE  = sys.argv[1] if len(sys.argv) > 1 else "field_guide"
TITLE = sys.argv[2] if len(sys.argv) > 2 else "steady |E| at f0 (frequency-domain)"

try:
    import pyvista as pv
    import imageio.v2 as imageio
except Exception as e:
    sys.exit(f"Missing package: {e}\nInstall: /opt/anaconda3/bin/pip install pyvista imageio numpy")

pv.OFF_SCREEN = True
try: pv.global_theme.font.color = "white"
except Exception: pass
os.makedirs(OUT, exist_ok=True)

# GPU volume ray-casting (add_volume) renders BLACK on a headless / disconnected
# Windows session (OpenGL falls back to GDI-generic 1.1). Default to a robust polygon
# render on Windows; macOS/Linux keep the volume render unchanged. Override with
# OPENEMS_FIELD_RENDER=volume|surface.  (Mirrors render_field.py.)
_RMODE = os.environ.get("OPENEMS_FIELD_RENDER", "").strip().lower()
USE_SURFACE = (_RMODE == "surface") or (_RMODE != "volume" and os.name == "nt")

files = sorted(glob.glob(os.path.join(SIM, "Ef_*.vtr")))
if not files:
    sys.exit(f"No Ef_*.vtr frequency-domain dump in {SIM}. (Run with field_mode='freq'.)")
mesh = pv.read(files[-1])

# |E| from the complex frequency-domain field (real & imaginary vector parts)
vecs = []
for assoc in (mesh.point_data, mesh.cell_data):
    for n in list(assoc.keys()):
        a = assoc[n]
        if getattr(a, "ndim", 0) == 2 and a.shape[1] == 3:
            vecs.append((n, assoc, a))
if not vecs:
    sys.exit("no 3-component field array found in the frequency-domain dump")
if len(vecs) >= 2:
    mag = np.sqrt(np.linalg.norm(vecs[0][2], axis=1)**2 + np.linalg.norm(vecs[1][2], axis=1)**2)
    assoc = vecs[0][1]
else:
    mag = np.linalg.norm(vecs[0][2], axis=1)
    assoc = vecs[0][1]
assoc["|E|"] = mag
if assoc is mesh.cell_data:
    mesh = mesh.cell_data_to_point_data()

b = mesh.bounds
cx = (b[0]+b[1])/2; cy = (b[2]+b[3])/2; cz = (b[4]+b[5])/2; Lz = b[5]-b[4]

# map the GUIDE outline into these coords so the wall is drawn (same as render_field.py)
GUIDE = None
try:
    _n = [float(v) for v in open(os.path.join(HERE, "render_geo.txt")).read().split()]
    dxmin,dxmax,dymin,dymax,dzmin,dzmax, gx0,gx1,gy0,gy1,gz0,gz1 = _n[:12]
    def _mp(v, vmin, vmax, b0, b1):
        return b0 + (v-vmin)/(vmax-vmin)*(b1-b0) if vmax > vmin else b0
    GUIDE = (_mp(gx0,dxmin,dxmax,b[0],b[1]), _mp(gx1,dxmin,dxmax,b[0],b[1]),
             _mp(gy0,dymin,dymax,b[2],b[3]), _mp(gy1,dymin,dymax,b[2],b[3]),
             _mp(gz0,dzmin,dzmax,b[4],b[5]), _mp(gz1,dzmin,dzmax,b[4],b[5]))
except Exception:
    GUIDE = None

E = np.asarray(mesh.point_data["|E|"], dtype=float)
clim = (0.0, max(float(np.nanmax(E)) * 0.9, 1e-12))

p = pv.Plotter(off_screen=True, window_size=(1320, 640))
p.set_background("#0d1117")
try:
    gb = GUIDE if GUIDE else b
    box = pv.Box(bounds=gb)
    if not USE_SURFACE:   # translucent fill needs real OpenGL; skip in surface mode
        p.add_mesh(box, color="#c9a36a", opacity=0.12)
    p.add_mesh(box.extract_all_edges(), color="#3ddc97", line_width=4)
except Exception:
    pass
sbar = {"title": "|E| (V/m)", "vertical": True, "title_font_size": 18, "label_font_size": 14}
if USE_SURFACE:
    # Robust polygon render (headless GDI-generic OpenGL can't do GPU volume ray-cast):
    # two centre cut-planes coloured by |E|, using only add_mesh.
    vol = mesh if "|E|" in mesh.point_data else mesh.cell_data_to_point_data()
    shown = False
    for _nm in ("y", "x"):
        try:
            sl = vol.slice(normal=_nm, origin=(cx, cy, cz))
        except Exception:
            sl = None
        if sl is not None and sl.n_points:
            if not shown:
                p.add_mesh(sl, scalars="|E|", cmap="turbo", clim=clim, scalar_bar_args=sbar)
                shown = True
            else:
                p.add_mesh(sl, scalars="|E|", cmap="turbo", clim=clim, show_scalar_bar=False)
    if not shown:
        p.add_mesh(mesh.slice(normal="y"), scalars="|E|", cmap="turbo", clim=clim, scalar_bar_args=sbar)
else:
    try:
        vol = mesh if "|E|" in mesh.point_data else mesh.cell_data_to_point_data()
        p.add_volume(vol, scalars="|E|", cmap="turbo", clim=clim,
                     opacity=[0.0, 0.09, 0.20, 0.38, 0.62, 0.92], scalar_bar_args=sbar)
    except Exception:
        p.add_mesh(mesh.slice(normal="y"), scalars="|E|", cmap="turbo", clim=clim, scalar_bar_args=sbar)
p.camera_position = [(cx + 0.85*Lz, cy + 0.5*Lz, cz), (cx, cy, cz), (0, 1, 0)]
p.camera.zoom(1.35)
try: p.enable_anti_aliasing()
except Exception: pass
p.add_text(TITLE, font_size=11, color="white")
outp = os.path.join(OUT, BASE + "_still.png")
p.screenshot(outp); p.close()
print("frequency-domain field ->", outp)
