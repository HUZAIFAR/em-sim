"""
Waveguide material simulator (core physics) — MXene-coated wood by default,
but works for any material.

Models a rectangular waveguide carrying its dominant TE10 mode and computes how
much signal is lost to the walls (attenuation, dB/m) across the X / Ku / K bands,
then compares a chosen wall material against solid copper and aluminum baselines,
including weight and TOTAL delivered-to-orbit cost per metre.

Physics chain (see the HTML "The physics" tab for full explanations):
  - Skin depth          d   = 1 / sqrt(pi * f * mu0 * sigma)
  - Surface resistance (thick wall):  Rs = 1 / (sigma * d)
  - Finite-thickness coating correction (film of thickness t on an insulator):
        Rs_eff = Rs / tanh(t / d)          (-> Rs when t >> d; blows up when t << d)
  - TE10 conductor attenuation (Pozar, Microwave Engineering):
        ac = Rs_eff / (b * eta0 * sqrt(1-(fc/f)^2)) * (1 + 2*(b/a)*(fc/f)^2)   [Np/m]
    cutoff  fc = c / (2a).   Convert Np/m -> dB/m by * 8.686.
  - Weight:  m = perimeter * wall_thickness * length * density
  - Cost:    C_total = C_material + m * launch_cost_per_kg

Verified: solid-copper WR-90 attenuation = 0.108 dB/m @10 GHz (published ~0.11).
"""

import numpy as np

# ---- physical constants ----
MU0 = 4 * np.pi * 1e-7      # H/m
EPS0 = 8.8541878128e-12     # F/m
C = 299_792_458.0           # m/s
ETA0 = np.sqrt(MU0 / EPS0)  # ~376.73 ohm, free-space wave impedance

# Cost of putting 1 kg into orbit ($/kg). This usually DOMINATES the bill: the
# material is bought once on the ground, but every kg must also be launched.
LAUNCH_COST_PER_KG = 7000.0

# ---- material library (researched values; edit freely for any material) ----
# sigma  : conductivity [S/m]   density: [kg/m^3]   price: [$/kg]
MATERIALS = {
    "copper":   dict(sigma=5.80e7, density=8960, price=10.0,  solid=True),
    "aluminum": dict(sigma=3.50e7, density=2700, price=3.4,   solid=True),
    # MXene coating on a wood wall. sigma ~1e6 S/m (1e4 S/cm) is a good film.
    # The wall's WEIGHT is dominated by the wood core; the coating is microns thin.
    "mxene_wood": dict(sigma=1.0e6, density=700,  price=2.0,  solid=False,
                       coat_price_per_kg=25000.0, coat_density=3700.0),
}

# Standard satellite bands (GHz) and the rectangular guide usually used in each.
# a, b are interior width/height in metres (standard WR sizes).
BANDS = {
    "X  (8-12 GHz)":  dict(f0=8.0,  f1=12.0, a=22.86e-3, b=10.16e-3),   # WR-90
    "Ku (12-18 GHz)": dict(f0=12.0, f1=18.0, a=15.80e-3, b=7.90e-3),    # WR-62
    "K  (18-27 GHz)": dict(f0=18.0, f1=27.0, a=10.67e-3, b=4.32e-3),    # WR-42
}


def skin_depth(f_hz, sigma):
    return 1.0 / np.sqrt(np.pi * f_hz * MU0 * sigma)


def surface_resistance(f_hz, sigma, coat_thickness_m=None):
    """Rs of a thick wall, or of a finite-thickness film on an insulator."""
    d = skin_depth(f_hz, sigma)
    rs_thick = 1.0 / (sigma * d)
    if coat_thickness_m is None:
        return rs_thick
    # finite film correction; tanh -> 1 for thick films, -> small for thin -> Rs up
    return rs_thick / np.tanh(coat_thickness_m / d)


def te10_attenuation_db_per_m(f_hz, a, b, sigma, coat_thickness_m=None):
    """TE10 conductor attenuation in dB/m. NaN below cutoff (no propagation)."""
    fc = C / (2 * a)
    ratio = fc / f_hz
    propagating = f_hz > fc
    rs = surface_resistance(f_hz, sigma, coat_thickness_m)
    with np.errstate(invalid="ignore", divide="ignore"):
        ac_np = (rs / (b * ETA0 * np.sqrt(1 - ratio**2))) * (1 + 2 * (b / a) * ratio**2)
    ac_db = ac_np * 8.685889638
    return np.where(propagating, ac_db, np.nan)


def section_mass_kg(band, material_key, length_m=1.0, wall_t_m=1.5e-3,
                    coats=1, coat_thickness_per_coat_m=1e-6):
    """Mass of one waveguide section (4 walls, thin-wall approx)."""
    g = BANDS[band]
    a, b = g["a"], g["b"]
    perimeter = 2 * (a + b)
    m = MATERIALS[material_key]
    if m["solid"]:
        vol = perimeter * wall_t_m * length_m          # metal wall volume
        return vol * m["density"]
    # coating-on-substrate: substrate core + thin coating
    sub_vol = perimeter * wall_t_m * length_m
    sub_mass = sub_vol * m["density"]
    coat_t = coats * coat_thickness_per_coat_m
    coat_vol = perimeter * coat_t * length_m
    coat_mass = coat_vol * m["coat_density"]
    return sub_mass + coat_mass


def section_cost_usd(band, material_key, length_m=1.0, wall_t_m=1.5e-3,
                     coats=1, coat_thickness_per_coat_m=1e-6):
    """Material cost only (no launch)."""
    g = BANDS[band]
    a, b = g["a"], g["b"]
    perimeter = 2 * (a + b)
    m = MATERIALS[material_key]
    if m["solid"]:
        mass = section_mass_kg(band, material_key, length_m, wall_t_m)
        return mass * m["price"]
    sub_vol = perimeter * wall_t_m * length_m
    sub_mass = sub_vol * m["density"]
    coat_t = coats * coat_thickness_per_coat_m
    coat_vol = perimeter * coat_t * length_m
    coat_mass = coat_vol * m["coat_density"]
    return sub_mass * m["price"] + coat_mass * m["coat_price_per_kg"]


def total_delivered_cost_usd(band, material_key, length_m=1.0, wall_t_m=1.5e-3,
                             coats=1, coat_thickness_per_coat_m=1e-6,
                             launch_cost_per_kg=LAUNCH_COST_PER_KG):
    """Material cost + launch cost (mass x $/kg-to-orbit). The number that
    actually decides a flight design: cheap-but-heavy can cost far more to fly."""
    mat_cost = section_cost_usd(band, material_key, length_m, wall_t_m,
                                coats, coat_thickness_per_coat_m)
    mass = section_mass_kg(band, material_key, length_m, wall_t_m,
                           coats, coat_thickness_per_coat_m)
    return mat_cost + mass * launch_cost_per_kg


# --------------------------- verification / demo ---------------------------
if __name__ == "__main__":
    print("=== VERIFICATION: solid copper WR-90 (X-band) attenuation ===")
    print("Published theoretical value ~0.11-0.13 dB/m near 10 GHz.\n")
    g = BANDS["X  (8-12 GHz)"]
    for f in [8e9, 9e9, 10e9, 11e9, 12e9]:
        ac = te10_attenuation_db_per_m(f, g["a"], g["b"], MATERIALS["copper"]["sigma"])
        print(f"  {f/1e9:4.0f} GHz : {ac:.4f} dB/m")

    print("\n=== Skin depth at 10 GHz ===")
    for name, sig in [("copper", 5.8e7), ("aluminum", 3.5e7), ("MXene", 1e6)]:
        print(f"  {name:9s}: {skin_depth(10e9, sig)*1e6:6.2f} um")

    print("\n=== MXene-coated wood, X-band @10 GHz, coats sweep (1um each) ===")
    print("  (coating must exceed ~3x its 5um skin depth to act like bulk)")
    for coats in [1, 5, 10, 20, 40]:
        ac = te10_attenuation_db_per_m(10e9, g["a"], g["b"],
                                       MATERIALS["mxene_wood"]["sigma"],
                                       coat_thickness_m=coats*1e-6)
        print(f"  {coats:3d} coats ({coats}um): {ac:.4f} dB/m")

    print("\n=== Weight, material cost & TOTAL delivered-to-orbit cost, 1 m (X-band) ===")
    print(f"    (launch cost = ${LAUNCH_COST_PER_KG:,.0f}/kg)\n")
    bd = "X  (8-12 GHz)"
    rows = [("copper", {}), ("aluminum", {}), ("mxene_wood", dict(coats=20))]
    for mat, kw in rows:
        mass = section_mass_kg(bd, mat, **kw)
        mat_c = section_cost_usd(bd, mat, **kw)
        tot = total_delivered_cost_usd(bd, mat, **kw)
        tag = f" ({kw['coats']} coats)" if kw else ""
        print(f"  {mat:11s}: {mass*1000:6.0f} g | material ${mat_c:8.2f} | "
              f"to-orbit ${tot:9.0f}{tag}")
    cu = total_delivered_cost_usd(bd, "copper")
    mx = total_delivered_cost_usd(bd, "mxene_wood", coats=20)
    print(f"\n  -> MXene-wood delivered cost is {100*(1-mx/cu):.0f}% cheaper than copper "
          f"once launch is included.")
