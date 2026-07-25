#!/usr/bin/env python3
"""
STEP -> segmented triangle-mesh JSON for the analytical CAD-RCS tab.

Tessellates a .step/.stp with gmsh's OpenCASCADE kernel and emits a compact JSON
the browser loads for the Physical-Optics facet RCS engine. Each STEP **solid**
becomes a named **segment** (so an assembly of fuselage/wing/fin parts comes in
pre-split, and the UI can assign a coating per part). A single fused solid yields
one segment (the UI offers manual grouping in that case).

This does NO electromagnetics — it only reads + tessellates geometry. It is the
STEP counterpart of the browser-side STL parser (STL is parsed client-side).

Output JSON (units = MILLIMETRES, recentred at the bounding-box centre):
  {
    "ok": true,
    "units": "mm",
    "unit_guess": "mm" | "m->mm",
    "n_solids": <int>, "n_verts": <int>, "n_tri": <int>,
    "bbox_mm": [dx, dy, dz],
    "half_extent_mm": <max half-span, for the openEMS electrical-size guard>,
    "verts": [[x,y,z], ...],                         # mm, shared across segments
    "segments": [ {"id": <int>, "name": <str>, "ntri": <int>,
                   "tris": [[i,j,k], ...]} ]         # indices into verts
  }
Fail-soft: on any error prints {"ok": false, "error": "..."} and exits non-zero,
so the bridge can surface the real reason to the page.

Usage:
    python step_facets.py input.step [output.json] [--res R] [--mm-per-unit K] [--max-tri N]
"""
import sys, os, json, argparse


def _fail(msg):
    print(json.dumps({"ok": False, "error": str(msg)}))
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step")
    ap.add_argument("out", nargs="?", default=None)
    ap.add_argument("--res", type=float, default=1 / 200.0,
                    help="target triangle size as a fraction of the bbox diagonal (smaller = finer)")
    ap.add_argument("--mm-per-unit", type=float, default=None,
                    help="override: how many mm one file-unit equals (skips the auto unit guess)")
    ap.add_argument("--max-tri", type=int, default=200000,
                    help="safety cap; if the mesh would exceed this the triangle target is coarsened")
    args = ap.parse_args()

    step = os.path.abspath(args.step)
    if not os.path.isfile(step):
        _fail(f"file not found: {step}")
    out = os.path.abspath(args.out) if args.out else os.path.splitext(step)[0] + "_facets.json"

    try:
        import gmsh
    except Exception as e:
        _fail(f"gmsh not installed ({e}); pip install gmsh")

    try:
        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.occ.importShapes(step)
        gmsh.model.occ.synchronize()

        vols = gmsh.model.getEntities(3)
        if not vols:
            # some STEP files carry only free surfaces (no solid) -> treat every surface as one segment
            vols = []
        surfs_all = gmsh.model.getEntities(2)
        if not surfs_all:
            _fail("no surfaces found in STEP (empty or unreadable geometry)")

        # --- unit handling: STEP files may be in mm, m or inch. Guess from size unless told. ---
        bb = gmsh.model.getBoundingBox(-1, -1)
        dx, dy, dz = bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]
        diag = (dx * dx + dy * dy + dz * dz) ** 0.5
        if args.mm_per_unit is not None:
            k = float(args.mm_per_unit); unit_guess = f"x{k}"
        elif diag < 2.0:            # a "1.4"-ish diagonal is almost certainly metres for a real part
            k = 1000.0; unit_guess = "m->mm"
        else:                        # already mm-scale
            k = 1.0; unit_guess = "mm"

        # --- mesh (coarsen the target if it would blow past --max-tri) ---
        target = diag * args.res
        for _attempt in range(6):
            gmsh.model.mesh.clear()
            gmsh.option.setNumber("Mesh.MeshSizeMin", target * 0.5)
            gmsh.option.setNumber("Mesh.MeshSizeMax", target)
            gmsh.option.setNumber("Mesh.Algorithm", 6)   # Frontal-Delaunay
            gmsh.model.mesh.generate(2)
            _, etags, _ = gmsh.model.mesh.getElements(2)
            ntri_est = sum(len(t) for t in etags)
            if ntri_est <= args.max_tri:
                break
            target *= 1.4                                  # too many -> coarsen and retry

        # --- global node table (dedup shared vertices), mm + recentred ---
        ntags, ncoords, _ = gmsh.model.mesh.getNodes()
        ncoords = list(ncoords)
        cx = (bb[0] + bb[3]) / 2.0; cy = (bb[1] + bb[4]) / 2.0; cz = (bb[2] + bb[5]) / 2.0
        tag2idx = {}
        verts = []
        for j, t in enumerate(ntags):
            x = (ncoords[3 * j] - cx) * k
            y = (ncoords[3 * j + 1] - cy) * k
            z = (ncoords[3 * j + 2] - cz) * k
            tag2idx[int(t)] = len(verts)
            verts.append([round(x, 5), round(y, 5), round(z, 5)])

        # --- collect triangles per solid; a surface shared by two solids is assigned once ---
        def tris_of_surface(stag):
            tris = []
            etypes, etags2, enodes = gmsh.model.mesh.getElements(2, stag)
            for et, nod in zip(etypes, enodes):
                if et == 2:                                # 3-node triangle
                    nod = list(nod)
                    for m in range(0, len(nod), 3):
                        try:
                            tris.append([tag2idx[int(nod[m])], tag2idx[int(nod[m + 1])], tag2idx[int(nod[m + 2])]])
                        except KeyError:
                            pass
            return tris

        # Many STEP writers label every solid with a generic translator string
        # ("Open CASCADE STEP translator 7.8 1.3") instead of the real component name.
        # Those are useless in the UI, so treat them as unnamed and fall back to part_N.
        import re as _re
        _GENERIC = _re.compile(r"open\s*cascade|step\s*translator|^compound$|^solid\d*$|^shape\d*$", _re.I)

        segments = []
        used_surface = set()
        seg_id = 0
        if vols:
            for dim, vtag in vols:
                name = gmsh.model.getEntityName(dim, vtag) or ""
                name = name.split("/")[-1].strip() if name else ""
                if (not name) or _GENERIC.search(name):
                    name = f"part_{seg_id + 1}"
                bnd = gmsh.model.getBoundary([(dim, vtag)], oriented=False, recursive=False)
                seg_tris = []
                for bdim, btag in bnd:
                    st = abs(int(btag))
                    if (2, st) in [(d, t) for d, t in [(bdim, st)]] and st in used_surface:
                        continue
                    if st in used_surface:
                        continue
                    used_surface.add(st)
                    seg_tris.extend(tris_of_surface(st))
                if seg_tris:
                    # per-part size (mm) so the UI can identify each part even when the STEP
                    # carries no real component names (body vs arm vs rotor by their dimensions)
                    try:
                        vb = gmsh.model.getBoundingBox(dim, vtag)
                        size_mm = [round((vb[3] - vb[0]) * k, 1), round((vb[4] - vb[1]) * k, 1),
                                   round((vb[5] - vb[2]) * k, 1)]
                    except Exception:
                        size_mm = None
                    segments.append({"id": seg_id, "name": name, "ntri": len(seg_tris),
                                     "size_mm": size_mm, "tris": seg_tris})
                    seg_id += 1
        # any surfaces not owned by a solid (free faces) -> one extra segment
        leftover = []
        for sdim, stag in surfs_all:
            if stag not in used_surface:
                leftover.extend(tris_of_surface(stag))
                used_surface.add(stag)
        if leftover:
            segments.append({"id": seg_id, "name": "surfaces", "ntri": len(leftover), "tris": leftover})

        if not segments:
            _fail("tessellation produced no triangles")

        n_tri = sum(s["ntri"] for s in segments)
        halfx = max(abs(v[0]) for v in verts); halfy = max(abs(v[1]) for v in verts); halfz = max(abs(v[2]) for v in verts)
        result = {
            "ok": True, "units": "mm", "unit_guess": unit_guess,
            "n_solids": len(vols), "n_verts": len(verts), "n_tri": n_tri,
            "bbox_mm": [round(dx * k, 4), round(dy * k, 4), round(dz * k, 4)],
            "half_extent_mm": round(max(halfx, halfy, halfz), 4),
            "verts": verts, "segments": segments,
        }
        with open(out, "w") as f:
            json.dump(result, f)
        # human-readable line to stderr; JSON summary (no verts) to stdout for the bridge
        summary = {k2: result[k2] for k2 in ("ok", "units", "unit_guess", "n_solids", "n_verts", "n_tri", "bbox_mm", "half_extent_mm")}
        summary["segments"] = [{"id": s["id"], "name": s["name"], "ntri": s["ntri"]} for s in segments]
        summary["out"] = out
        print(json.dumps(summary))
    except SystemExit:
        raise
    except Exception as e:
        _fail(e)
    finally:
        try:
            gmsh.finalize()
        except Exception:
            pass


if __name__ == "__main__":
    main()
