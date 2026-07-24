#!/usr/bin/env python3
"""
Export the openEMS 3-D E-field VOLUME dump (Ev_*.vtr from /tmp/horn_sim) into a
compact JSON point cloud for the interactive browser field viewer on the Horn tab.

It reads the frequency-domain |E| the solver actually computed, keeps only the
points that carry real field (thresholded), downsamples to a browser-friendly
count, and writes horn_results/field3d.json with positions in mm + normalized
|E| (0..1) + the horn geometry so the viewer can draw the walls aligned to the
field.

FAIL-SOFT: any problem (no volume dump, no pyvista, empty field) just prints and
returns without writing — the run still succeeds, the viewer simply stays hidden.
The stale file is removed first so a failed export never serves old data.

Run:  <python-with-pyvista> export_field3d.py
Out:  horn_results/field3d.json
"""
import glob, os, json
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_SCR = os.environ.get("OPENEMS_SCRATCH") or (r"C:\openems_scratch" if os.name == "nt" else "/tmp")
SIM  = os.path.join(_SCR, "horn_sim")
OUT  = os.path.join(HERE, "horn_results")
DEST = os.path.join(OUT, "field3d.json")
MAXPTS = 34000      # cap for smooth browser rendering (denser = more CST-like)
FLOOR  = 0.035      # keep points brighter than 3.5% of peak |E| (omit empty space)


def main():
    os.makedirs(OUT, exist_ok=True)
    # remove any previous export so a failure here can't serve stale data
    try:
        if os.path.exists(DEST):
            os.remove(DEST)
    except Exception:
        pass

    try:
        import pyvista as pv
    except Exception as e:
        print("export_field3d: pyvista not available:", e)
        return

    files = sorted(glob.glob(os.path.join(SIM, "Ev*.vtr")))
    if not files:
        print("export_field3d: no Ev*.vtr volume dump in", SIM)
        return
    try:
        mesh = pv.read(files[-1])
    except Exception as e:
        print("export_field3d: could not read", files[-1], e)
        return

    # |E| from the complex freq-domain field (real & imaginary vector arrays)
    vecs = []
    for assoc in (mesh.point_data, mesh.cell_data):
        for n in list(assoc.keys()):
            a = assoc[n]
            if getattr(a, "ndim", 0) == 2 and a.shape[1] == 3:
                vecs.append((n, assoc, a))
    if not vecs:
        print("export_field3d: no 3-component field array in the dump")
        return
    if len(vecs) >= 2:
        mag = np.sqrt(np.linalg.norm(vecs[0][2], axis=1) ** 2 +
                      np.linalg.norm(vecs[1][2], axis=1) ** 2)
        assoc = vecs[0][1]
    else:
        mag = np.linalg.norm(vecs[0][2], axis=1)
        assoc = vecs[0][1]
    assoc["|E|"] = mag
    if assoc is mesh.cell_data:
        mesh = mesh.cell_data_to_point_data()

    E = np.asarray(mesh.point_data["|E|"], dtype=float)
    pts = np.asarray(mesh.points, dtype=float) * 1000.0     # openEMS metres -> mm
    if E.size == 0 or not np.isfinite(np.nanmax(E)):
        print("export_field3d: empty / non-finite field")
        return
    Emax = float(np.nanmax(E))
    if Emax <= 0:
        print("export_field3d: peak |E| is zero")
        return
    inten = E / Emax

    keep = np.where(inten > FLOOR)[0]
    if keep.size == 0:                       # fallback: brightest points
        keep = np.argsort(inten)[-2000:]
    if keep.size > MAXPTS:                    # keep the brightest MAXPTS
        order = keep[np.argsort(inten[keep])][::-1]
        keep = order[:MAXPTS]

    x = np.round(pts[keep, 0], 1).tolist()
    y = np.round(pts[keep, 1], 1).tolist()
    z = np.round(pts[keep, 2], 1).tolist()
    e = np.round(inten[keep], 3).tolist()

    # --- structured mid-y cut-plane (H-plane) for the smooth CST-style field view ---
    plane = None
    try:
        dims = getattr(mesh, "dimensions", None)
        if dims is not None and len(dims) == 3:
            nx, ny, nz = int(dims[0]), int(dims[1]), int(dims[2])
            if nx >= 2 and nz >= 2 and (nx * ny * nz == E.size):
                xc = np.asarray(mesh.x, dtype=float) * 1000.0     # mm
                zc = np.asarray(mesh.z, dtype=float) * 1000.0
                yc = np.asarray(mesh.y, dtype=float)
                E3 = E.reshape((nx, ny, nz), order="F")           # VTK ordering: x fastest
                j0 = int(np.argmin(np.abs(yc)))                   # slice nearest y = 0
                P = E3[:, j0, :] / Emax                           # (nx, nz), 0..1
                xi = np.unique(np.linspace(0, nx - 1, min(nx, 160)).round().astype(int))
                zi = np.unique(np.linspace(0, nz - 1, min(nz, 160)).round().astype(int))
                Psub = P[np.ix_(xi, zi)]
                plane = {"nx": int(len(xi)), "nz": int(len(zi)),
                         "y": round(float(yc[j0] * 1000.0), 2),
                         "x": np.round(xc[xi], 1).tolist(),
                         "z": np.round(zc[zi], 1).tolist(),
                         "e": np.round(Psub.T.ravel(), 3).tolist()}   # index = k*nx + i
    except Exception as ex:
        print("export_field3d: plane slice skipped:", ex)
        plane = None

    geo = {}
    try:
        vals = [float(v) for v in open(os.path.join(OUT, "horn_geo.txt")).read().split()]
        a, b, Ax, By, feed, flare, f0 = vals[:7]
        geo = {"a": a, "b": b, "Ax": Ax, "By": By, "feed": feed, "flare": flare, "f0": f0}
    except Exception:
        geo = {}

    out = {"unit": "mm", "geo": geo, "plane": plane, "n": len(e), "x": x, "y": y, "z": z, "e": e}
    with open(DEST, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print("export_field3d: wrote", DEST, "with", len(e), "points (peak |E| =", Emax, ")")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("export_field3d: unexpected error:", e)
