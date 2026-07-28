#!/usr/bin/env python3
"""
Generate the demo multi-body STEP models shipped in demo_cad/ for the CAD-RCS tab.

Each model is written as SEPARATE SOLIDS (never fused), because the CAD-RCS tab turns
one STEP solid into one coatable "part". That is what lets you put a different RAM
coating on a rocket's nose vs its fins, or a drone's body vs its rotors.

Run:  python demo_cad/make_demo_cad.py        (needs `pip install gmsh`)
Out:  demo_cad/*.step
"""
import os, re, math, gmsh

HERE = os.path.dirname(os.path.abspath(__file__))
S = 1.0 / math.sqrt(2.0)


def name_step_products(path, model_name, labels):
    """OpenCASCADE's STEP writer ignores gmsh entity names and labels every solid
    'Open CASCADE STEP translator <ver> 1.N' (N = solid order). Rewrite those PRODUCT
    names to the real part names so any STEP reader (and the CAD-RCS tab) shows
    'nose', 'fin_1', 'rotor_3' instead of a generic translator string."""
    with open(path, "r") as f:
        txt = f.read()
    # NB the trailing integer is a per-write counter (1 for the first file written in a
    # session, 2 for the next, ...), so it must be matched generically, not hardcoded.
    m = re.search(r"Open CASCADE STEP translator [\d.]+ \d+", txt)
    if not m:
        return False
    base = m.group(0)
    # descending so '1.10' is replaced before '1.1'
    for i in sorted(range(1, len(labels) + 1), reverse=True):
        txt = txt.replace(f"{base}.{i}", labels[i - 1])
    txt = txt.replace(base, model_name)          # the root assembly product
    with open(path, "w") as f:
        f.write(txt)
    return True


def build(name, parts_fn):
    """parts_fn(occ) -> list of (label, solid_tag). Writes <name>.step."""
    gmsh.model.add(name)
    occ = gmsh.model.occ
    parts = parts_fn(occ)
    occ.synchronize()
    for label, tag in parts:
        try:
            gmsh.model.setEntityName(3, tag, label)
        except Exception:
            pass
    bb = gmsh.model.getBoundingBox(-1, -1)
    out = os.path.join(HERE, name + ".step")
    gmsh.write(out)
    name_step_products(out, name, [l for l, _ in parts])
    print(f"{name+'.step':<26s} {len(parts):2d} parts   "
          f"{bb[3]-bb[0]:7.1f} x {bb[4]-bb[1]:7.1f} x {bb[5]-bb[2]:7.1f} mm   "
          f"[{', '.join(l for l, _ in parts[:6])}{' …' if len(parts) > 6 else ''}]")
    gmsh.clear()


# ---------------------------------------------------------------- models
def cone_tube(occ):
    """The simplest multi-part case: a tube with a cone on top."""
    return [
        ("tube", occ.addCylinder(0, 0, 0, 0, 0, 300, 50)),
        ("cone", occ.addCone(0, 0, 300, 0, 0, 120, 50, 0)),
    ]


def water_bottle(occ):
    """Body + shoulder taper + neck + cap — a everyday curved object."""
    return [
        ("body",     occ.addCylinder(0, 0, 0,   0, 0, 180, 35)),
        ("shoulder", occ.addCone(0, 0, 180,     0, 0, 45, 35, 13)),
        ("neck",     occ.addCylinder(0, 0, 225, 0, 0, 25, 13)),
        ("cap",      occ.addCylinder(0, 0, 248, 0, 0, 24, 15)),
    ]


def rocket(occ):
    """Nose cone + body tube + 4 fins + nozzle: the classic RCS shape."""
    parts = [
        ("nose",   occ.addCone(0, 0, 700, 0, 0, 200, 60, 0)),
        ("body",   occ.addCylinder(0, 0, 0, 0, 0, 700, 60)),
        ("nozzle", occ.addCone(0, 0, -80, 0, 0, 80, 45, 60)),
    ]
    for i in range(4):
        # fin: thin plate standing out from the base of the body
        t = occ.addBox(50, -4, 10, 110, 8, 160)
        occ.rotate([(3, t)], 0, 0, 0, 0, 0, 1, i * math.pi / 2)
        parts.append((f"fin_{i+1}", t))
    return parts


def satellite(occ):
    """Bus + 2 solar panels + dish + boom — flat panels make huge specular flashes."""
    return [
        ("bus",      occ.addBox(-200, -200, -250, 400, 400, 500)),
        ("panel_L",  occ.addBox(-1400, -300, -20, 1200, 600, 12)),
        ("panel_R",  occ.addBox(200, -300, -20, 1200, 600, 12)),
        ("dish",     occ.addCone(0, 0, 250, 0, 0, 90, 250, 60)),
        ("boom",     occ.addCylinder(0, 0, 340, 0, 0, 220, 12)),
    ]


def drone_quad(occ):
    """Quadcopter: body + 4 arms + 4 rotor discs + camera pod."""
    parts = [("body", occ.addBox(-80, -80, -25, 160, 160, 50))]
    for i, (sx, sy) in enumerate([(1, 1), (-1, 1), (-1, -1), (1, -1)]):
        x0, y0 = 110 * S * sx, 110 * S * sy
        dx, dy = (240 - 110) * S * sx, (240 - 110) * S * sy
        parts.append((f"arm_{i+1}", occ.addCylinder(x0, y0, 0, dx, dy, 0, 8)))
    for i, (sx, sy) in enumerate([(1, 1), (-1, 1), (-1, -1), (1, -1)]):
        x, y = 240 * S * sx, 240 * S * sy
        parts.append((f"rotor_{i+1}", occ.addCylinder(x, y, 26, 0, 0, 4, 115)))
    parts.append(("camera", occ.addBox(-25, -95, -55, 50, 40, 32)))
    return parts


def calib_sphere_100mm(occ):
    """A single 100 mm-diameter sphere: a KNOWN answer for sanity-checking the engine.
    Physical-optics backscatter of a sphere -> the optical limit pi*a^2
    = pi*(0.05 m)^2 = 7.854e-3 m^2 = -21.0 dBsm, independent of frequency.
    Import it, press Compute, and the chart should sit flat near -21 dBsm."""
    return [("sphere_r50mm", occ.addSphere(0, 0, 0, 50))]


def stealth_ucav(occ):
    """Flying-wing UCAV: a chined, highly swept blended body with canted tails and a shielded
    inlet lip. This is the classic low-observable planform, so the shape-improvement search has
    something to work WITH rather than against: the levers that matter here are planform sweep
    and tail cant, not body taper."""
    parts = []
    # blended centre body: a shallow wedge, wide at the back
    parts.append(("centrebody", occ.addBox(-90, -260, -35, 180, 520, 70)))
    # two highly swept wing panels, built as thin canted boxes and swept by a rotation
    for i, sx in enumerate((1, -1)):
        w = occ.addBox(0, -240, -14, 430, 300, 28)
        occ.rotate([(3, w)], 0, 0, 0, 0, 0, 1, math.radians(-38 * sx))
        if sx < 0:
            occ.mirror([(3, w)], 1, 0, 0, 0)
        parts.append((f"wing_{i+1}", w))
    # canted vertical tails (the single biggest specular lever on this shape)
    for i, sx in enumerate((1, -1)):
        t = occ.addBox(-14, 120, 0, 28, 190, 150)
        occ.rotate([(3, t)], 0, 0, 0, 0, 1, 0, math.radians(30 * sx))
        occ.translate([(3, t)], 150 * sx, 0, 20)
        parts.append((f"tail_{i+1}", t))
    # a shielded dorsal inlet lip: a serrated-looking blocky duct mouth
    parts.append(("inlet_lip", occ.addBox(-55, -140, 30, 110, 120, 26)))
    return parts


def missile_seeker(occ):
    """Air-to-air missile: ogive radome, body, four cruciform mid-body strakes and four tail fins.
    Cruciform fins are a textbook broadside/45-degree specular problem, so the fin-cant lever has
    a large, physically real effect here."""
    parts = [("radome", occ.addCone(0, 0, 0, 0, 0, 260, 0.5, 88)),
             ("body", occ.addCylinder(0, 0, 260, 0, 0, 1900, 88)),
             ("nozzle", occ.addCone(0, 0, 2160, 0, 0, 120, 88, 62))]
    for i in range(4):
        a = math.radians(90 * i)
        st = occ.addBox(-6, 0, 900, 12, 130, 260)
        occ.rotate([(3, st)], 0, 0, 0, 0, 0, 1, a)
        parts.append((f"strake_{i+1}", st))
    for i in range(4):
        a = math.radians(90 * i + 45)
        fn = occ.addBox(-7, 0, 1880, 14, 210, 300)
        occ.rotate([(3, fn)], 0, 0, 0, 0, 0, 1, a)
        parts.append((f"tailfin_{i+1}", fn))
    return parts


def corner_test_dihedral(occ):
    """Two plates meeting at 90 degrees - a deliberate WORST CASE, and an honesty exhibit.
    A dihedral retroreflects: real measured RCS is enormous over a wide sector. This tool's
    PO+PTD engine has no multiple-bounce term, so it will UNDER-report this shape badly. It ships
    as a demo precisely so that limitation is something you can see rather than just read."""
    return [("plate_vertical", occ.addBox(0, -150, 0, 6, 300, 300)),
            ("plate_horizontal", occ.addBox(0, -150, 0, 300, 300, 6))]


MODELS = [
    ("cone_tube", cone_tube),
    ("stealth_ucav", stealth_ucav),
    ("missile_seeker", missile_seeker),
    ("corner_test_dihedral", corner_test_dihedral),
    ("water_bottle", water_bottle),
    ("rocket", rocket),
    ("satellite", satellite),
    ("drone_quad", drone_quad),
    ("calib_sphere_100mm", calib_sphere_100mm),
]

if __name__ == "__main__":
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        for name, fn in MODELS:
            build(name, fn)
    finally:
        gmsh.finalize()
    print("\nAll models written to", HERE)
