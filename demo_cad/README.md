# demo_cad — multi-part STEP models for the CAD-RCS tab

Ready-to-upload test geometry for **RCS ▾ → CAD-RCS (STEP/STL)**. Every file is a
**multi-body** STEP: each solid arrives as its own **coatable part**, so you can put a
different RAM coating on a rocket's nose than on its fins.

Upload one, press **Compute RCS**, then assign coatings per part (or use
**Apply to all**). All numbers are analytical (Physical Optics + Ufimtsev PTD) and instant.

| File | Parts | Size (mm) | Electrical size @10 GHz | What it's good for |
|---|---|---|---|---|
| `calib_sphere_100mm.step` | 1 | 100 ⌀ | 3.3 λ | **Sanity check** — a sphere's RCS is the same from every angle and equals ≈ **−21 dBsm**. If the chart is flat at −21, the engine is behaving. |
| `cone_tube.step` | 2 (tube, cone) | 100 × 100 × 420 | 14 λ | The simplest multi-part case: coat the cone, leave the tube bare, watch the difference. |
| `water_bottle.step` | 4 (body, shoulder, neck, cap) | 70 × 70 × 272 | 9 λ | An everyday curved object — mostly curved surfaces, so no single huge flash. |
| `rocket.step` | 7 (nose, body, nozzle, fin_1–4) | 320 × 320 × 980 | 33 λ | The classic missile/rocket signature: big broadside flash from the body tube, fin edges elsewhere. |
| `satellite.step` | 5 (bus, panel_L, panel_R, dish, boom) | 2800 × 600 × 810 | 93 λ | Large **flat** solar panels = the biggest specular returns of any model here (~+28 dBsm). Shows why flat panels dominate. |
| `drone_quad.step` | 10 (body, arm_1–4, rotor_1–4, camera) | 569 × 569 × 85 | 19 λ | Per-part attribution: the flat body is ~96 % of the echo at its peak angle; coating the rotors buys almost nothing there. |

Reference values from the engine at 10 GHz, V-pol, full 360° azimuth sweep (bare metal):

| Model | Peak RCS | Peak at | Mean RCS | Real diffracting edges |
|---|---|---|---|---|
| calib_sphere_100mm | −21.4 dBsm | (flat) | −21.4 dBsm | 0 (a smooth sphere has none) |
| cone_tube | −0.3 dBsm | 230° | −0.5 dBsm | 353 |
| water_bottle | −6.8 dBsm | 225° | −7.2 dBsm | 544 |
| rocket | +12.2 dBsm | 95° | +8.8 dBsm | 930 |
| satellite | +27.6 dBsm | 0° | +15.1 dBsm | 1154 |
| drone_quad | +1.9 dBsm | 270° | −8.9 dBsm | 2463 |

Note how much bigger the **satellite** is than the **drone** — flat panels square-on to the
radar are enormous reflectors, which is exactly what the 3-D facet view shows in red.

## Notes

- These are **representative shapes, not engineering models** — good for exercising and
  understanding the tool, not for a real signature study of a specific vehicle.
- All models are **electrically large** (9–93 wavelengths), so full-wave FDTD cannot fit
  them; that is precisely why the analytical PO+PTD engine exists. Only
  `calib_sphere_100mm` (3.3 λ) is small enough for the openEMS cross-check button.
- Parts touch or slightly overlap where they join (fins into the body, arms into the
  drone frame). The engine has no ray self-occlusion, so a facet hidden inside another
  solid still contributes; the effect is small here but it is a real limitation.
- Regenerate or edit them with `python demo_cad/make_demo_cad.py` (needs `pip install gmsh`).
  Add your own model by writing a `parts_fn` that returns `(label, solid_tag)` pairs —
  keep the solids **separate** (never boolean-fused) so they stay individually coatable.

## Defence-oriented models (added for the shape-improvement search)

| File | Parts | Size (mm) | What it is for |
|---|---|---|---|
| `stealth_ucav.step` | 6 | 862 × 766 × 192 | A flying-wing UCAV: chined blended body, 38°-swept wing panels, canted vertical tails, shielded dorsal inlet lip. This is the shape low-observable design actually produces, so the shape-improvement search has to work *with* it — the levers that move the needle here are planform sweep and tail cant, not body taper. |
| `missile_seeker.step` | 11 | 307 × 307 × 2280 | Air-to-air missile: ogive radome, cylindrical body, four cruciform mid-body strakes, four tail fins at 45°. Cruciform fins are the textbook broadside/45° specular problem, so the fin-cant lever has a large and physically real effect. |
| `corner_test_dihedral.step` | 2 | 300 cube | **A deliberate worst case and an honesty exhibit.** Two plates meeting at 90° retroreflect, so the real measured RCS is enormous over a wide sector. This tool's PO + first-order PTD engine carries no multiple-bounce term and will therefore **under-report this shape badly**. It ships as a demo precisely so that limitation is something you can see rather than only read about. |
