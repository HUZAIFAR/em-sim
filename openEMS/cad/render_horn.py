#!/usr/bin/env python3
"""
Stage 3 render - the "show me the inside" view.

Reads the frequency-domain E-field dump written by horn_run.m
(/tmp/horn_sim/Ef*.vtr, the y=0 H-plane cut) and paints |E| in colour so
you can see the TE10 wave travelling up the feed, expanding through the
horn, and radiating out of the aperture. Overlays the horn wall outline
(from horn_results/horn_geo.txt) so the metal boundary is visible.

Run:
    /opt/anaconda3/bin/python render_horn.py
Output:
    horn_results/horn_field.png
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

HERE = os.path.dirname(os.path.abspath(__file__))
_SCR = os.environ.get("OPENEMS_SCRATCH") or (r"C:\openems_scratch" if os.name == "nt" else "/tmp")
SIM  = os.path.join(_SCR, "horn_sim")
OUT  = os.path.join(HERE, "horn_results")
os.makedirs(OUT, exist_ok=True)

try:
    import pyvista as pv
except Exception as e:
    sys.exit(f"need pyvista: {e}\n  /opt/anaconda3/bin/pip install pyvista")
pv.OFF_SCREEN = True

files = sorted(glob.glob(os.path.join(SIM, "Ef*.vtr")))
if not files:
    sys.exit(f"No Ef*.vtr in {SIM}. Run:  octave --no-gui horn_run.m")
mesh = pv.read(files[-1])

# --- build |E| from whatever field arrays exist (complex freq-domain = Re+Im) ---
def collect_vectors(m):
    out = []
    for assoc in (m.point_data, m.cell_data):
        for n in list(assoc.keys()):
            a = assoc[n]
            if getattr(a, "ndim", 0) == 2 and a.shape[1] == 3:
                out.append((n, assoc, a))
    return out
vecs = collect_vectors(mesh)
if not vecs:
    sys.exit("no 3-component field array found in the dump")
if len(vecs) >= 2:                       # real & imaginary parts
    mag = np.sqrt(np.linalg.norm(vecs[0][2], axis=1)**2 +
                  np.linalg.norm(vecs[1][2], axis=1)**2)
    assoc = vecs[0][1]
else:
    mag = np.linalg.norm(vecs[0][2], axis=1)
    assoc = vecs[0][1]
assoc["|E|"] = mag
if assoc is mesh.cell_data:
    mesh = mesh.cell_data_to_point_data()

# --- two scalar views: peak-normalized LINEAR and normalized dB ---------------
# The |E| amplitude genuinely falls as the wave expands through the flare
# (spreading ~1/sqrt(area)) and radiates from the aperture (~1/r); that decay is
# REAL. Raw V/m are tiny (~1e-11), so we normalize to the peak and also provide a
# dB view (0 to -40 dB) — the standard antenna presentation — so the guided mode
# and the radiated lobes stay readable all the way out.
E = np.asarray(mesh.point_data["|E|"], dtype=float)
Emax = float(np.nanmax(E)) if np.nanmax(E) > 0 else 1.0
mesh.point_data["|E|_lin"] = E / Emax                                # 0..1
mesh.point_data["|E|_dB"]  = 20.0*np.log10(np.maximum(E/Emax, 1e-3)) # floored at -60 dB
b = mesh.bounds

# --- horn wall outline in sim coords (metres); propagation = z, H-plane cut = x-z ---
def wall_lines():
    try:
        a,bb,Ax,By,feed,flare,f0 = [float(v) for v in open(os.path.join(OUT,"horn_geo.txt")).read().split()]
    except Exception:
        return []
    s = 1e-3
    # right wall: feed (x=a/2, z:-feed..0) then flare to x=Ax/2 at z=flare
    R = np.array([[ a/2*s,0,-feed*s],[ a/2*s,0,0],[ Ax/2*s,0,flare*s]])
    L = np.array([[-a/2*s,0,-feed*s],[-a/2*s,0,0],[-Ax/2*s,0,flare*s]])
    return [R, L]

# framing from the horn geometry (meters)
try:
    _a,_b,_Ax,_By,_feed,_flare,_f0=[float(v) for v in open(os.path.join(OUT,"horn_geo.txt")).read().split()]
except Exception:
    _Ax=80.0
s=1e-3
cz=(b[4]+b[5])/2                            # centre horizontally on the actual field region
half_x=(_Ax/2 + 32)*s                       # vertical half-height (aperture + margin, incl. beam spread)

def render(scalar, cmap, clim, title, outfile):
    p = pv.Plotter(off_screen=True, window_size=(1280, 560))
    p.set_background("white")
    p.add_mesh(mesh, scalars=scalar, cmap=cmap, clim=clim,
               scalar_bar_args={"title":title,"vertical":True,"title_font_size":14,
                                "label_font_size":11,"position_x":0.915,"position_y":0.25,"height":0.5,"width":0.035})
    for seg in wall_lines():
        p.add_mesh(pv.lines_from_points(seg), color="black", line_width=3)
    # face-on x-z plane: propagation (z) horizontal, x vertical, centred, parallel projection
    p.enable_parallel_projection()
    p.camera_position=[(0.0, 1.0, cz),(0.0, 0.0, cz),(1,0,0)]
    try: p.camera.parallel_scale = half_x
    except Exception: p.reset_camera()
    try: p.enable_anti_aliasing()
    except Exception: pass
    out = os.path.join(OUT, outfile)
    p.screenshot(out); p.close()
    print("wrote", out)

render("|E|_lin", "jet", (0.0, 1.0),   "|E| / max",  "horn_field_lin.png")
render("|E|_dB",  "jet", (-40.0, 0.0), "|E| (dB)",   "horn_field_db.png")
# back-compat: keep horn_field.png (linear view) for anything referencing it
import shutil
try: shutil.copyfile(os.path.join(OUT,"horn_field_lin.png"), os.path.join(OUT,"horn_field.png"))
except Exception: pass

# --- optional TIME-DOMAIN animation (Field view = time) -----------------------
# openEMS is a time-domain (FDTD) solver; when the tab requests the time-domain
# view, horn_run.m also writes Et_*.vtr frames on the H-plane cut. Build a GIF of
# the pulse entering the feed, expanding through the flare, and radiating out.
FIELD_MODE = sys.argv[1] if len(sys.argv) > 1 else "freq"
if FIELD_MODE == "time":
    et = sorted(glob.glob(os.path.join(SIM, "Et_*.vtr")))
    try: import imageio.v2 as imageio
    except Exception: imageio = None
    if et and imageio is not None:
        idx = list(range(0, len(et), max(1, len(et)//80)))
        gmax = 0.0
        for i in idx:
            mm = pv.read(et[i]); vs = collect_vectors(mm)
            if vs: gmax = max(gmax, float(np.linalg.norm(vs[0][2], axis=1).max()))
        if gmax > 0:
            clim = (0.0, 0.85*gmax); frames = []
            for i in idx:
                mm = pv.read(et[i]); vs = collect_vectors(mm)
                if not vs: continue
                mag = np.linalg.norm(vs[0][2], axis=1); vs[0][1]["|E|"] = mag
                mmp = mm.cell_data_to_point_data() if vs[0][1] is mm.cell_data else mm
                pl = pv.Plotter(off_screen=True, window_size=(1280, 560)); pl.set_background("white")
                try:
                    vol = mmp if "|E|" in mmp.point_data else mmp.cell_data_to_point_data()
                    pl.add_mesh(vol, scalars="|E|", cmap="jet", clim=clim,
                                scalar_bar_args={"title":"|E| (V/m)","vertical":True,"title_font_size":14,"label_font_size":11})
                except Exception:
                    pass
                for seg in wall_lines():
                    pl.add_mesh(pv.lines_from_points(seg), color="black", line_width=3)
                pl.enable_parallel_projection()
                pl.camera_position = [(0.0, 1.0, cz), (0.0, 0.0, cz), (1, 0, 0)]
                try: pl.camera.parallel_scale = half_x
                except Exception: pl.reset_camera()
                fp = os.path.join(OUT, "_hf_frame.png"); pl.screenshot(fp); pl.close()
                frames.append(imageio.imread(fp))
            if frames:
                imageio.mimsave(os.path.join(OUT, "horn_field.gif"), frames, duration=0.07, loop=0)
                try: os.remove(os.path.join(OUT, "_hf_frame.png"))
                except Exception: pass
                print("wrote horn_field.gif")
    else:
        print("time-domain view requested but no Et_*.vtr frames / imageio found")
