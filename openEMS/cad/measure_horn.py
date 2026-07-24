#!/usr/bin/env python3
"""
Stage 2 - measure a horn/waveguide STL's flare profile.

Slices the mesh along the long (axial) direction and, at each station,
reports the OUTER cross-section half-widths in the two transverse axes.
This reveals: the feed (throat) opening, where the flare begins, the
aperture opening, and the axial length - everything needed to rebuild a
clean parametric horn interior in openEMS.

Usage:
    python measure_horn.py  horn.stl  [--n 25]

Assumes the long axis is whichever bounding-box dimension is largest.
Prints a table (axial position -> transverse spans) and a summary.
"""
import sys, argparse
import numpy as np

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stl")
    ap.add_argument("--n", type=int, default=25, help="number of slice stations")
    args = ap.parse_args()

    import pyvista as pv
    mesh = pv.read(args.stl)
    b = mesh.bounds  # xmin,xmax,ymin,ymax,zmin,zmax
    spans = {"x": b[1]-b[0], "y": b[3]-b[2], "z": b[5]-b[4]}
    axis = max(spans, key=spans.get)                 # long axis = propagation axis
    trans = [k for k in "xyz" if k != axis]
    ai = "xyz".index(axis)
    lo, hi = mesh.bounds[2*ai], mesh.bounds[2*ai+1]
    print(f"long (propagation) axis: {axis.upper()}   length = {hi-lo:.2f} mm")
    print(f"transverse axes: {trans[0].upper()} , {trans[1].upper()}")
    print(f"{'pos_mm':>8} | {trans[0].upper()+'_span':>9} | {trans[1].upper()+'_span':>9}")
    print("-"*34)

    rows = []
    for i in range(args.n):
        frac = (i + 0.5) / args.n
        pos = lo + frac * (hi - lo)
        try:
            sl = mesh.slice(normal=axis, origin=_origin(axis, pos))
        except Exception:
            sl = None
        if sl is None or sl.n_points == 0:
            rows.append((pos, 0.0, 0.0)); continue
        sb = sl.bounds
        s0 = sb[2*"xyz".index(trans[0])+1] - sb[2*"xyz".index(trans[0])]
        s1 = sb[2*"xyz".index(trans[1])+1] - sb[2*"xyz".index(trans[1])]
        rows.append((pos, s0, s1))
        print(f"{pos:8.2f} | {s0:9.2f} | {s1:9.2f}")

    # summary: throat (min transverse span region) and aperture (max)
    arr = np.array(rows)
    ap_row = arr[np.argmax(arr[:,1]*arr[:,2])]
    th_row = arr[np.argmin(arr[arr[:,1]>0][:,1]*arr[arr[:,1]>0][:,2])] if (arr[:,1]>0).any() else arr[0]
    print("-"*34)
    print(f"APERTURE  ~ {ap_row[1]:.2f} x {ap_row[2]:.2f} mm  (outer, at pos {ap_row[0]:.1f})")
    print(f"THROAT    ~ {th_row[1]:.2f} x {th_row[2]:.2f} mm  (outer, at pos {th_row[0]:.1f})")
    print("note: WR-90 feed inner is 22.86 x 10.16 mm; walls subtract ~2x thickness.")

def _origin(axis, pos):
    o = [0.0, 0.0, 0.0]
    o["xyz".index(axis)] = pos
    return o

if __name__ == "__main__":
    main()
