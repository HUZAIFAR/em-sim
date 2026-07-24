#!/usr/bin/env python3
"""
Stage 1a - STEP -> STL converter for the Waveguide Simulator CAD feature.

Uses gmsh's built-in OpenCASCADE kernel to:
  1. import a .step / .stp file,
  2. report the true bounding box (in the file's own units),
  3. surface-mesh the solid,
  4. write a triangulated .stl that openEMS/PyVista can read.

Usage:
    python step2stl.py  input.step  [output.stl]  [--mm-per-unit N]  [--res R]

Notes
-----
* This does NOT run any electromagnetics. It only proves the geometry can be
  read and tessellated. That is Stage 1 of the CAD pipeline.
* STEP files carry their own length unit. This horn file mixes METRE and INCH
  declarations, so we PRINT the raw bounding box and let you confirm the real
  physical size before we ever feed it to openEMS (openEMS wants metres).
* --res controls triangle size as a fraction of the bounding-box diagonal
  (default 1/120). Smaller = finer mesh = bigger STL.
"""
import sys, os, argparse

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step")
    ap.add_argument("stl", nargs="?", default=None)
    ap.add_argument("--res", type=float, default=1/120.0,
                    help="target triangle size as fraction of bbox diagonal")
    ap.add_argument("--mm-per-unit", type=float, default=None,
                    help="optional: how many mm one file-unit equals (just for the printed report)")
    args = ap.parse_args()

    step = os.path.abspath(args.step)
    if not os.path.isfile(step):
        sys.exit(f"ERROR: file not found: {step}")
    stl = args.stl or os.path.splitext(step)[0] + ".stl"
    stl = os.path.abspath(stl)

    try:
        import gmsh
    except ImportError:
        sys.exit("ERROR: gmsh not installed.  Run:  pip install gmsh")

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)   # quiet
        # --- import the STEP solid via OpenCASCADE ---
        ents = gmsh.model.occ.importShapes(step)
        gmsh.model.occ.synchronize()

        vols = gmsh.model.getEntities(3)
        surfs = gmsh.model.getEntities(2)
        print(f"imported: {len(vols)} solid(s), {len(surfs)} face(s)")

        # --- true bounding box in file units ---
        xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
        dx, dy, dz = xmax - xmin, ymax - ymin, zmax - zmin
        diag = (dx*dx + dy*dy + dz*dz) ** 0.5
        print("bounding box (file units):")
        print(f"    X {xmin:+.4f} .. {xmax:+.4f}   span {dx:.4f}")
        print(f"    Y {ymin:+.4f} .. {ymax:+.4f}   span {dy:.4f}")
        print(f"    Z {zmin:+.4f} .. {zmax:+.4f}   span {dz:.4f}")
        if args.mm_per_unit:
            k = args.mm_per_unit
            print(f"    -> in mm (x{k}):  {dx*k:.2f} x {dy*k:.2f} x {dz*k:.2f} mm")

        # --- mesh the surface ---
        target = diag * args.res
        gmsh.option.setNumber("Mesh.MeshSizeMin", target * 0.5)
        gmsh.option.setNumber("Mesh.MeshSizeMax", target)
        gmsh.option.setNumber("Mesh.Algorithm", 6)          # Frontal-Delaunay
        gmsh.model.mesh.generate(2)                          # surface mesh only

        gmsh.write(stl)
        # report triangle count
        _, tags, _ = gmsh.model.mesh.getElements(2)
        ntri = sum(len(t) for t in tags)
        print(f"wrote STL: {stl}")
        print(f"    triangles: {ntri}")
        print("OK")
    finally:
        gmsh.finalize()

if __name__ == "__main__":
    main()
