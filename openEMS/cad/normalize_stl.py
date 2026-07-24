#!/usr/bin/env python3
"""
Normalize an STL for the RCS import path: recenter it at the origin and convert to
millimetres, so rcs_run.m can drop it straight into a domain centred on (0,0,0) with
p_stl_scale = 1. Prints a one-line JSON with the normalized half-extent + size (mm).

Usage:  normalize_stl.py  in.stl  out.stl
Run with the Anaconda python (has pyvista/numpy).

Unit heuristic: STL files are unitless. RF targets here are mm..decimetre scale, so if the
raw bounding-box span is tiny (< 5) the file is almost certainly in metres and is scaled
x1000 to mm; otherwise the numbers are taken as mm. The assumed size is reported back so
the user can sanity-check it in the UI (honesty rule).
"""
import sys, json
import numpy as np


def main():
    if len(sys.argv) < 3:
        sys.exit("usage: normalize_stl.py in.stl out.stl")
    src, dst = sys.argv[1], sys.argv[2]
    import pyvista as pv
    m = pv.read(src)
    b = m.bounds  # (xmin,xmax,ymin,ymax,zmin,zmax)
    span = max(b[1] - b[0], b[3] - b[2], b[5] - b[4])
    if span <= 0:
        sys.exit("degenerate mesh (zero span)")
    scale = 1000.0 if span < 5.0 else 1.0          # metres -> mm, else already mm
    center = np.array([(b[0] + b[1]) / 2.0, (b[2] + b[3]) / 2.0, (b[4] + b[5]) / 2.0])
    m.points = (np.asarray(m.points) - center) * scale
    m.save(dst)
    nb = m.bounds
    half = max(abs(nb[0]), abs(nb[1]), abs(nb[2]), abs(nb[3]), abs(nb[4]), abs(nb[5]))
    print(json.dumps({
        "ok": True, "half_extent_mm": round(float(half), 3),
        "size_mm": {"x": round(float(nb[1] - nb[0]), 2),
                    "y": round(float(nb[3] - nb[2]), 2),
                    "z": round(float(nb[5] - nb[4]), 2)},
        "unit_guess": "metres" if scale != 1.0 else "mm",
        "n_faces": int(m.n_cells)
    }))


if __name__ == "__main__":
    main()
