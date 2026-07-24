#!/usr/bin/env python3
"""
Stage 1b - view a converted STL with PyVista (same renderer the simulator
already uses for openEMS field maps).

Usage:
    python view_stl.py  model.stl            # interactive 3-D window (rotate/zoom)
    python view_stl.py  model.stl --shots    # also save PNGs from 4 angles
    python view_stl.py  model.stl --shots --no-window   # PNGs only, no window

Outputs (with --shots): model_iso.png, model_side.png, model_front.png,
model_axis.png next to the STL.
"""
import sys, os, argparse

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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stl")
    ap.add_argument("--shots", action="store_true", help="save PNG snapshots")
    ap.add_argument("--no-window", action="store_true", help="do not open interactive window")
    args = ap.parse_args()

    stl = os.path.abspath(args.stl)
    if not os.path.isfile(stl):
        sys.exit(f"ERROR: file not found: {stl}")

    try:
        import pyvista as pv
    except ImportError:
        sys.exit("ERROR: pyvista not installed.  Run:  pip install pyvista")

    mesh = pv.read(stl)
    b = mesh.bounds  # xmin,xmax,ymin,ymax,zmin,zmax
    print(f"loaded: {mesh.n_cells} triangles, {mesh.n_points} points")
    print(f"bounds: X {b[0]:.3f}..{b[1]:.3f}  Y {b[2]:.3f}..{b[3]:.3f}  Z {b[4]:.3f}..{b[5]:.3f}")

    base = os.path.splitext(stl)[0]

    def make_plotter(off):
        p = pv.Plotter(off_screen=off, window_size=[1100, 850])
        # translucent shell so you can see INTO the horn (this is the "show the inside" part)
        p.add_mesh(mesh, color="#9db4c0", opacity=0.45, show_edges=True,
                   edge_color="#4a5a66", line_width=0.4, smooth_shading=True)
        p.add_mesh(mesh.extract_feature_edges(), color="#0B6E54", line_width=1.5)
        p.set_background("white")
        p.add_axes()
        return p

    if args.shots:
        views = {
            "iso":   "iso",
            "side":  "yz",
            "front": "xy",
            "axis":  "xz",
        }
        for name, cam in views.items():
            p = make_plotter(off=True)
            p.camera_position = cam
            p.reset_camera()
            out = f"{base}_{name}.png"
            p.screenshot(out)
            p.close()
            print(f"saved {out}")

    if not args.no_window:
        p = make_plotter(off=False)
        print("opening interactive window - drag to rotate, scroll to zoom, q to quit")
        p.show()

if __name__ == "__main__":
    main()
