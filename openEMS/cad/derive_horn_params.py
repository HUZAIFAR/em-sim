#!/usr/bin/env python3
"""
Derive parametric horn dimensions from a converted STL (best-effort, for
horn / flared-waveguide shapes). Prints JSON: {Ax,By,feed,flare,length}.
The feed waveguide (a,b) is taken from the band (passed in), since a horn is
fed by a standard rectangular guide.

Usage:
    python derive_horn_params.py horn.stl --a 22.86 --b 10.16
"""
import sys, json, argparse
import numpy as np

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stl")
    ap.add_argument("--a", type=float, default=22.86)   # feed broad (mm)
    ap.add_argument("--b", type=float, default=10.16)   # feed narrow (mm)
    ap.add_argument("--wall", type=float, default=2.0)  # assumed wall thickness (mm)
    a = ap.parse_args()

    import pyvista as pv
    m = pv.read(a.stl)
    b = m.bounds
    spans = {"x": b[1]-b[0], "y": b[3]-b[2], "z": b[5]-b[4]}
    axis = max(spans, key=spans.get)
    trans = [k for k in "xyz" if k != axis]
    ai = "xyz".index(axis); lo, hi = m.bounds[2*ai], m.bounds[2*ai+1]
    L = hi - lo

    def origin(pos):
        o=[0,0,0]; o[ai]=pos; return o
    s0max=s1max=0.0
    for i in range(30):
        pos = lo + (i+0.5)/30*(hi-lo)
        try: sl = m.slice(normal=axis, origin=origin(pos))
        except Exception: sl=None
        if sl is None or sl.n_points==0: continue
        sb=sl.bounds
        s0=sb[2*"xyz".index(trans[0])+1]-sb[2*"xyz".index(trans[0])]
        s1=sb[2*"xyz".index(trans[1])+1]-sb[2*"xyz".index(trans[1])]
        s0max=max(s0max,s0); s1max=max(s1max,s1)

    broad_outer, narrow_outer = max(s0max,s1max), min(s0max,s1max)
    Ax = max(a.a, broad_outer  - 2*a.wall)     # inner aperture, broad (H-plane)
    By = max(a.b, narrow_outer - 2*a.wall)     # inner aperture, narrow (E-plane)
    feed = 20.0
    flare = max(0.4*L, L - 15.0)               # flare length (drop ~flange)
    print(json.dumps({"Ax":round(Ax,2),"By":round(By,2),
                      "feed":round(feed,2),"flare":round(flare,2),"length":round(L,2)}))

if __name__ == "__main__":
    main()
