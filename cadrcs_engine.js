'use strict';
/* ============================================================================
 * CAD-RCS analytical engine — monostatic Physical Optics (PO) facet sum
 * + first-order Ufimtsev PTD edge diffraction.  Single source of truth:
 *   - verify_math.js require()s this file for the physics anchors;
 *   - waveguide_simulator.html inlines the identical block (between the
 *     __CADRCS_ENGINE_START__ / __CADRCS_ENGINE_END__ markers) as window.CADRCS,
 *     and verify_math.js asserts the two copies are byte-identical (whitespace-
 *     normalized) so they can never silently drift.
 *
 * Validated (workflow + adjudication + independent re-runs + openEMS full-wave):
 *   PO plate boresight = 4piA^2/lambda^2 exact (fine & coarse mesh, 2 freqs);
 *   full off-boresight pattern exact; cylinder 2piah^2/lambda to 0.03 dB;
 *   sphere -> PO limit (0.34 dB above GO pi a^2, converged = real PO physics);
 *   PTD: broadside untouched (ripple 0.004 dB), grazing PO collapses (<-50 dBsm)
 *   while PO+PTD holds the L^2/pi edge floor, frequency- & mesh-independent;
 *   openEMS full-wave (120 mm plate): broadside 0.15 dB, wide-angle floor ~3.5 dB
 *   (first-order PTD, conservative at small electrical size), vs PO alone up to 69 dB off.
 * DO NOT edit one copy without the other.
 * ==========================================================================*/

// __CADRCS_ENGINE_START__
const sub    = (a, b) => [a[0]-b[0], a[1]-b[1], a[2]-b[2]];
const add3   = (a, b) => [a[0]+b[0], a[1]+b[1], a[2]+b[2]];
const scaleV = (a, s) => [a[0]*s, a[1]*s, a[2]*s];
const dot    = (a, b) => a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
const cross  = (a, b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
const norm   = (a) => Math.hypot(a[0], a[1], a[2]);
const unit   = (a) => { const n = norm(a); return n < 1e-300 ? [0,0,0] : scaleV(a, 1/n); };
const radOf  = (d) => d * Math.PI / 180;

// exact triangle phase integral (vertex divided-difference; finite at all coincidences)
function fddExp(a, b) {
  const m = 0.5*(a+b), d = 0.5*(a-b);
  const s = Math.abs(d) < 1e-13 ? 1 : Math.sin(d)/d;
  return { re: -Math.sin(m)*s, im: Math.cos(m)*s };
}
function triPhaseIntegral(area, g1, g2, g3) {
  const lo = Math.min(g1, g2, g3);
  const hi = Math.max(g1, g2, g3);
  const mid = g1 + g2 + g3 - lo - hi;
  const spread = hi - lo;
  if (spread < 1e-7) {
    const gm = (g1 + g2 + g3) / 3;
    return { re: area*Math.cos(gm), im: area*Math.sin(gm) };
  }
  const flm = fddExp(lo, mid);
  const fmh = fddExp(mid, hi);
  const re = (fmh.re - flm.re) / spread;
  const im = (fmh.im - flm.im) / spread;
  return { re: -2*area*re, im: -2*area*im };
}

// prepMesh: per-facet outward unit normal, area, centroid. tris = [{i,j,k,segId?,gamma?}]
function prepMesh(verts, tris) {
  const facets = [];
  for (const t of tris) {
    const v1 = verts[t.i], v2 = verts[t.j], v3 = verts[t.k];
    const nc = cross(sub(v2, v1), sub(v3, v1));
    const twoA = norm(nc);
    if (twoA < 1e-18) continue;
    facets.push({
      v1, v2, v3,
      area: 0.5 * twoA,
      n:    scaleV(nc, 1/twoA),
      c:    scaleV(add3(add3(v1, v2), v3), 1/3),
      segId: (t.segId != null ? t.segId : 0),
      gamma: t.gamma || null,
    });
  }
  return facets;
}

// monostatic PO. khat = incident propagation unit vector; lambda in SAME length units as verts.
// opts.gammaFn(facet,idx)->{re,im} per-facet reflection coeff (coating); opts.perSeg -> coherent segRCS.
function rcsMonostatic(facets, khat, lambda, opts = {}) {
  const k = 2 * Math.PI / lambda;
  const w = scaleV(khat, 2 * k);
  const uhat = scaleV(khat, -1);
  const gammaFn = opts.gammaFn || null;
  const perSeg = opts.perSeg ? {} : null;

  let Ire = 0, Iim = 0;
  for (let f = 0; f < facets.length; f++) {
    const fac = facets[f];
    const ndu = dot(fac.n, uhat);
    if (ndu <= 0) continue;

    const g1 = dot(w, fac.v1), g2 = dot(w, fac.v2), g3 = dot(w, fac.v3);
    const fi = triPhaseIntegral(fac.area, g1, g2, g3);
    let cre = ndu * fi.re, cim = ndu * fi.im;

    const g = gammaFn ? gammaFn(fac, f) : fac.gamma;
    if (g) {
      const nre = cre * g.re - cim * g.im;
      const nim = cre * g.im + cim * g.re;
      cre = nre; cim = nim;
    }

    Ire += cre; Iim += cim;

    if (perSeg) {
      const s = fac.segId;
      const acc = perSeg[s] || (perSeg[s] = { re: 0, im: 0 });
      acc.re += cre; acc.im += cim;
    }
  }

  const pref = 4 * Math.PI / (lambda * lambda);
  const sigma = pref * (Ire*Ire + Iim*Iim);
  const out = { sigma, dbsm: 10 * Math.log10(sigma), I: { re: Ire, im: Iim } };
  if (perSeg) {
    out.segRCS = {};
    for (const s in perSeg) {
      const p = perSeg[s];
      out.segRCS[s] = pref * (p.re*p.re + p.im*p.im);
    }
  }
  return out;
}

// ---- canonical mesh builders (validation) ----
function buildPlate(W, H, nx, ny) {
  const verts = [], tris = [];
  const idx = (i, j) => i * (ny + 1) + j;
  for (let i = 0; i <= nx; i++)
    for (let j = 0; j <= ny; j++)
      verts.push([0, -W/2 + (W*i)/nx, -H/2 + (H*j)/ny]);
  for (let i = 0; i < nx; i++)
    for (let j = 0; j < ny; j++) {
      const a = idx(i,j), b = idx(i+1,j), c = idx(i+1,j+1), d = idx(i,j+1);
      tris.push({ i:a, j:c, k:d });
      tris.push({ i:a, j:b, k:c });
    }
  return { verts, tris };
}
// Welded UV sphere: ONE vertex per pole and no duplicated longitude seam (j wraps with
// %nLon). A seam of duplicated vertices would look like a boundary rim, and pole
// quads would be degenerate slivers — both would be mistaken for real diffracting edges.
function buildSphere(a, nLat, nLon) {
  const verts = [], tris = [];
  const north = verts.length; verts.push([0, 0, a]);
  const ringStart = [];
  for (let i = 1; i < nLat; i++) {
    ringStart.push(verts.length);
    const th = Math.PI * i / nLat, st = Math.sin(th), ct = Math.cos(th);
    for (let j = 0; j < nLon; j++) {
      const ph = 2 * Math.PI * j / nLon;
      verts.push([a*st*Math.cos(ph), a*st*Math.sin(ph), a*ct]);
    }
  }
  const south = verts.length; verts.push([0, 0, -a]);
  const r0 = ringStart[0];
  for (let j = 0; j < nLon; j++) {                      // north cap
    const jn = (j + 1) % nLon;
    tris.push({ i:north, j:r0 + j, k:r0 + jn });
  }
  for (let r = 0; r + 1 < ringStart.length; r++) {      // bands
    const up = ringStart[r], dn = ringStart[r + 1];
    for (let j = 0; j < nLon; j++) {
      const jn = (j + 1) % nLon;
      tris.push({ i:up + j, j:dn + j,  k:dn + jn });
      tris.push({ i:up + j, j:dn + jn, k:up + jn });
    }
  }
  const rl = ringStart[ringStart.length - 1];
  for (let j = 0; j < nLon; j++) {                      // south cap
    const jn = (j + 1) % nLon;
    tris.push({ i:south, j:rl + jn, k:rl + j });
  }
  return { verts, tris };
}
function buildCylinder(a, h, nCirc, nAx, caps = true) {
  const verts = [], tris = [];
  const idx = (i, j) => i * nCirc + j;
  for (let i = 0; i <= nAx; i++) {
    const z = -h/2 + (h*i)/nAx;
    for (let j = 0; j < nCirc; j++) {
      const ph = 2 * Math.PI * j / nCirc;
      verts.push([a*Math.cos(ph), a*Math.sin(ph), z]);
    }
  }
  for (let i = 0; i < nAx; i++)
    for (let j = 0; j < nCirc; j++) {
      const jn = (j + 1) % nCirc;
      const a0 = idx(i,j), b0 = idx(i,jn), c0 = idx(i+1,jn), d0 = idx(i+1,j);
      tris.push({ i:a0, j:b0, k:c0 });
      tris.push({ i:a0, j:c0, k:d0 });
    }
  if (caps) {
    const cb = verts.length; verts.push([0, 0, -h/2]);
    for (let j = 0; j < nCirc; j++) {
      const jn = (j + 1) % nCirc;
      tris.push({ i:cb, j:idx(0,jn), k:idx(0,j) });
    }
    const ct = verts.length; verts.push([0, 0, h/2]);
    for (let j = 0; j < nCirc; j++) {
      const jn = (j + 1) % nCirc;
      tris.push({ i:ct, j:idx(nAx,j), k:idx(nAx,jn) });
    }
  }
  return { verts, tris };
}

// ---- PTD: real-edge extraction (boundary rim OR dihedral crease) ----
// dihedralTolDeg: how sharp a crease must be to count as a REAL diffracting edge.
// Must stay well above the facet-to-facet angle produced by tessellating a CURVED
// surface, or every tessellation seam is mistaken for a sharp edge and PTD adds huge
// spurious diffraction (a tessellated sphere read +29 dB too high at 1 deg). Real CAD
// edges are typically >= 30 deg; a reasonably meshed curved surface is only a few deg.
// Boundary edges (one adjacent face, e.g. a plate rim) are always real regardless.
function buildEdges(verts, tris, opts = {}) {
  const tolDeg = opts.dihedralTolDeg != null ? opts.dihedralTolDeg : 20.0;
  const cosTol = Math.cos(radOf(tolDeg));
  // A sliver facet's normal is numerically meaningless, so a crease against it is not
  // evidence of a real edge. q = 4*sqrt(3)*A/(a^2+b^2+c^2): 1 = equilateral, ->0 = degenerate.
  const qMin = opts.minFacetQuality != null ? opts.minFacetQuality : 0.10;
  const faceN = [], faceV = [], faceQ = [];
  for (const t of tris) {
    const v1 = verts[t.i], v2 = verts[t.j], v3 = verts[t.k];
    const nc = cross(sub(v2, v1), sub(v3, v1));
    const twoA = norm(nc);
    if (twoA < 1e-18) { faceN.push(null); faceV.push(null); faceQ.push(0); continue; }
    faceN.push(scaleV(nc, 1/twoA));
    faceV.push([t.i, t.j, t.k]);
    const e1 = sub(v2, v1), e2 = sub(v3, v2), e3 = sub(v1, v3);
    const ss = dot(e1, e1) + dot(e2, e2) + dot(e3, e3);
    faceQ.push(ss > 0 ? (2 * Math.sqrt(3) * twoA) / ss : 0);
  }
  const map = new Map();
  const key = (a, b) => (a < b ? a + '_' + b : b + '_' + a);
  for (let f = 0; f < tris.length; f++) {
    if (!faceV[f]) continue;
    const [a, b, c] = faceV[f];
    const trip = [[a, b, c], [b, c, a], [c, a, b]];
    for (const [u, v, w] of trip) {
      const kk = key(u, v);
      let e = map.get(kk);
      if (!e) { e = { u, v, faces: [] }; map.set(kk, e); }
      e.faces.push({ f, opp: w });
    }
  }
  const edges = [];
  for (const e of map.values()) {
    let real = false;
    if (e.faces.length === 1) real = true;
    else {
      const f0 = e.faces[0].f, f1 = e.faces[1].f;
      const n0 = faceN[f0], n1 = faceN[f1];
      if (n0 && n1 && faceQ[f0] > qMin && faceQ[f1] > qMin && dot(n0, n1) < cosTol) real = true;
    }
    if (!real) continue;
    edges.push({
      A: verts[e.u], B: verts[e.v],
      faces: e.faces.map(ff => ({ n: faceN[ff.f], opp: verts[ff.opp] })),
    });
  }
  return edges;
}

// coherent complex Ufimtsev fringe line integral over all real edges (added to PO complex I).
// opts.Epol = incident E unit vector (perp khat); omit -> soft (E-parallel) default.
function rcsFringe(edges, khat, lambda, opts = {}) {
  const k = 2 * Math.PI / lambda;
  const uhat = scaleV(khat, -1);
  const Epol = opts.Epol ? unit(opts.Epol) : null;
  const useObliq = opts.oblique !== false;
  const sinBetaMin = opts.sinBetaMin != null ? opts.sinBetaMin : 0.05;

  let Ire = 0, Iim = 0;
  for (const e of edges) {
    const A = e.A, B = e.B;
    const ev = sub(B, A);
    const L = norm(ev);
    if (L < 1e-15) continue;
    const ehat = scaleV(ev, 1/L);
    const rc = scaleV(add3(A, B), 0.5);

    let lit = null, best = 0;
    for (const fc of e.faces) {
      const d = dot(fc.n, uhat);
      if (d > best) { best = d; lit = fc; }
    }
    if (!lit) continue;
    const nf = lit.n;

    let sIn = sub(lit.opp, rc);
    sIn = sub(sIn, scaleV(ehat, dot(sIn, ehat)));
    if (norm(sIn) < 1e-15) continue;
    const sface = unit(sIn);

    let up = sub(uhat, scaleV(ehat, dot(uhat, ehat)));
    if (norm(up) < 1e-12) continue;
    up = unit(up);

    const dotN = dot(up, nf);
    const dotS = dot(up, sface);
    if (dotN <= 0) continue;

    const phi = Math.atan2(dotN, dotS);

    const tq = Math.tan(Math.PI/4 - phi/2);
    const cSoft = 0.5 * (1 - tq);
    const cHard = 0.5 * (1 + tq);

    let w = 1;
    if (Epol) { const ee = dot(Epol, ehat); w = ee * ee; }
    const cEdge = cSoft * w + cHard * (1 - w);
    const Df = 2 * cEdge;

    const kde = dot(khat, ehat);
    const sinb = Math.sqrt(Math.max(0, 1 - kde*kde));
    if (sinb < sinBetaMin) continue;
    const obf = useObliq ? 1/sinb : 1;

    const arg = k * kde * L;
    const sinc = Math.abs(arg) < 1e-12 ? 1 : Math.sin(arg) / arg;

    const ph = 2 * k * dot(khat, rc);

    const mag = (Df * L * sinc * obf) / (2 * k);
    Ire += mag * Math.sin(ph);
    Iim += -mag * Math.cos(ph);
  }
  return { re: Ire, im: Iim };
}

// PO + PTD total in one call. facets=prepMesh, edges=buildEdges. Returns dBsm both ways.
function rcsPOplusPTD(facets, edges, khat, lambda, opts = {}) {
  const po = rcsMonostatic(facets, khat, lambda, opts);
  const fr = edges ? rcsFringe(edges, khat, lambda, opts) : { re: 0, im: 0 };
  const Ire = po.I.re + fr.re, Iim = po.I.im + fr.im;
  const pref = 4 * Math.PI / (lambda * lambda);
  const sigPO  = po.sigma;
  const sigTot = pref * (Ire*Ire + Iim*Iim);
  const sigFr  = pref * (fr.re*fr.re + fr.im*fr.im);
  const dB = (s) => (s > 0 ? 10*Math.log10(s) : -Infinity);
  return {
    poDbsm: dB(sigPO), totalDbsm: dB(sigTot), fringeDbsm: dB(sigFr),
    poSigma: sigPO, totalSigma: sigTot, fringeSigma: sigFr,
    segRCS: po.segRCS || null,
    I_po: po.I, I_fringe: fr, I_total: { re: Ire, im: Iim },
  };
}
// __CADRCS_ENGINE_END__

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    prepMesh, rcsMonostatic, triPhaseIntegral,
    buildPlate, buildSphere, buildCylinder,
    buildEdges, rcsFringe, rcsPOplusPTD,
  };
}
