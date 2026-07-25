#!/usr/bin/env python3
"""
Generate the PWA / home-screen icons for the EM Waveguide & RCS Simulator.

The mark packs the whole project into one glyph:
  * a deep radial-gradient field (the dark surfaces the app uses),
  * radar range rings sweeping out from the aperture (the RCS half of the tool),
  * two machined metal rails = the waveguide walls, lit with a copper gradient,
  * a neon guided wave with a real bloom, brightening cyan -> mint -> white as it
    propagates and bursts out of the open end.

Run:  python pwa/make_icons.py        (needs Pillow + numpy)
Out:  pwa/icons/*.png
"""
import math, os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "icons")
os.makedirs(OUT, exist_ok=True)

# palette (drawn from the app's own tokens, pushed a little richer for an icon)
DEEP    = (5, 12, 11)        # outer background
CORE    = (12, 38, 32)       # centre of the radial field
RING    = (61, 220, 151)     # radar rings / accent green
RAIL_SPEC = (255, 244, 226)   # specular hit on the machined edge
RAIL_HI = (238, 190, 132)    # lit face of the copper rail
RAIL_LO = (118, 74, 38)      # shaded face
WAVE_A  = (86, 232, 255)     # wave at the input  (cyan)
WAVE_B  = (120, 255, 190)    # wave mid           (mint)
WAVE_C  = (255, 255, 255)    # wave at the output (white hot)


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def radial_bg(S):
    """Deep radial gradient, brighter in the middle so the mark has depth."""
    y, x = np.mgrid[0:S, 0:S].astype(np.float32)
    cx = cy = (S - 1) / 2.0
    r = np.sqrt(((x - cx) / cx) ** 2 + ((y - cy) / cy) ** 2)
    t = np.clip(r / 1.25, 0.0, 1.0) ** 1.15                 # 0 centre -> 1 corners
    img = np.zeros((S, S, 3), np.float32)
    for i in range(3):
        img[..., i] = CORE[i] + (DEEP[i] - CORE[i]) * t
    return Image.fromarray(img.astype(np.uint8), "RGB")


def wave_points(x0, x1, cy, amp, n=2400, periods=1.5):
    pts = []
    for i in range(n + 1):
        t = i / n
        x = x0 + (x1 - x0) * t
        y = cy - amp * math.sin(2 * math.pi * periods * t)
        pts.append((x, y, t))
    return pts


def draw_mark(size, pad_frac=0.15, rounded=True):
    S = size * 4                                            # supersample
    base = radial_bg(S).convert("RGBA")
    d = ImageDraw.Draw(base, "RGBA")

    # Composition: the guide occupies the LEFT ~56% and the radiated beam fans out
    # into the remaining width, all INSIDE the plate (rings drawn past the edge just
    # get cropped away and the beam disappears).
    pad = int(S * pad_frac)
    W = S - 2 * pad
    x0 = pad
    x1 = pad + int(W * 0.56)                                 # aperture / open end
    cy = S // 2
    half_h = int(W * 0.235)                                  # rail separation
    rail_t = max(3, int(S * 0.032))

    # ---- radar range rings + main-lobe edges, radiating from the aperture -----
    # These carry the RCS half of the tool, so they have to actually read: drawn on
    # their own layer, softened, then composited so they glow rather than outline.
    beam = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bd = ImageDraw.Draw(beam, "RGBA")
    ring_cx, ring_cy = x1, cy
    for i, frac in enumerate((0.13, 0.24, 0.35, 0.44)):
        rr = int(W * frac)
        alpha = int(255 - i * 30)
        w = max(4, int(S * (0.023 - i * 0.0030)))
        bd.arc([ring_cx - rr, ring_cy - rr, ring_cx + rr, ring_cy + rr],
               start=-50, end=50, fill=RING + (alpha,), width=w)
    beam = beam.filter(ImageFilter.GaussianBlur(S * 0.006))
    # a soft bloom under the rings so they glow instead of looking scratched on
    halo = beam.filter(ImageFilter.GaussianBlur(S * 0.022))
    base = Image.alpha_composite(base, halo)
    base = Image.alpha_composite(base, beam)
    d = ImageDraw.Draw(base, "RGBA")

    # ---- the guided wave: bloom pass, then the sharp stroke ------------------
    amp = half_h * 0.54
    pts = wave_points(x0 + rail_t, x1 - rail_t * 0.2, cy, amp, periods=1.25)

    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow, "RGBA")
    gr = max(3, int(S * 0.055))                              # fat, soft
    for (x, y, t) in pts[::5]:
        col = lerp(WAVE_A, WAVE_B, min(1.0, t * 1.6)) if t < 0.62 else lerp(WAVE_B, WAVE_C, (t - 0.62) / 0.38)
        gd.ellipse([x - gr, y - gr, x + gr, y + gr], fill=col + (26,))
    glow = glow.filter(ImageFilter.GaussianBlur(S * 0.028))
    base = Image.alpha_composite(base, glow)
    d = ImageDraw.Draw(base, "RGBA")

    sr = max(2, int(S * 0.0235))                              # sharp core stroke
    for (x, y, t) in pts:
        col = lerp(WAVE_A, WAVE_B, min(1.0, t * 1.6)) if t < 0.62 else lerp(WAVE_B, WAVE_C, (t - 0.62) / 0.38)
        d.ellipse([x - sr, y - sr, x + sr, y + sr], fill=col + (255,))

    # ---- the two machined rails: copper with a specular line, lit from above --
    def rail(y_top, flip=False):
        for k in range(rail_t):
            t = k / max(1, rail_t - 1)
            if flip: t = 1.0 - t
            # bright specular in the upper third, falling to shadow at the bottom
            col = lerp(RAIL_SPEC, RAIL_HI, min(1.0, t / 0.34)) if t < 0.34 else lerp(RAIL_HI, RAIL_LO, (t - 0.34) / 0.66)
            d.line([x0, y_top + k, x1, y_top + k], fill=col + (255,), width=1)
        # a hairline highlight on the inner face catches the wave's glow
        yi = y_top + (rail_t - 1 if not flip else 0)
        d.line([x0, yi, x1, yi], fill=RAIL_SPEC + (170,), width=max(1, rail_t // 6))
    rail(cy - half_h - rail_t // 2)
    rail(cy + half_h - rail_t // 2, flip=True)

    # closed input end (left): a solid short flange, so the guide reads as a tube
    fl_w = max(3, int(S * 0.030))
    for k in range(fl_w):
        t = k / max(1, fl_w - 1)
        d.line([x0 + k, cy - half_h - fl_w // 2, x0 + k, cy + half_h + fl_w // 2],
               fill=lerp(RAIL_HI, RAIL_LO, t) + (255,), width=1)

    # a hot flare where the wave leaves the aperture
    fr = int(S * 0.040)
    flare = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    fd = ImageDraw.Draw(flare, "RGBA")
    fd.ellipse([x1 - fr, cy - fr, x1 + fr, cy + fr], fill=WAVE_C + (185,))
    flare = flare.filter(ImageFilter.GaussianBlur(S * 0.030))
    base = Image.alpha_composite(base, flare)

    # ---- shape the plate ----------------------------------------------------
    if rounded:
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.225), fill=255)
        out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        out.paste(base, (0, 0), mask)
        base = out

    return base.resize((size, size), Image.LANCZOS)


def save(img, name, opaque=False):
    p = os.path.join(OUT, name)
    if opaque:
        flat = Image.new("RGB", img.size, DEEP)
        flat.paste(img, (0, 0), img)
        flat.save(p, "PNG")
    else:
        img.save(p, "PNG")
    print(f"  {name:28s} {img.size[0]}x{img.size[1]}")


if __name__ == "__main__":
    print("writing icons to", OUT)
    for s in (192, 512):
        save(draw_mark(s, 0.15, rounded=True), f"icon-{s}.png")
    # maskable: square plate + big safe zone, launchers crop these
    for s in (192, 512):
        save(draw_mark(s, 0.26, rounded=False), f"icon-maskable-{s}.png")
    # iOS home screen: opaque squares, NO alpha and NO rounding — iOS applies its own mask,
    # and an apple-touch-icon with transparency is a documented way to get no icon at all.
    # One file per device size iOS actually asks for (iPhone 180, iPad Pro 167, iPad 152,
    # older 120); the plain name stays for the root-path probe.
    for s, nm in ((180, "apple-touch-icon.png"), (180, "apple-touch-icon-180.png"),
                  (167, "apple-touch-icon-167.png"), (152, "apple-touch-icon-152.png"),
                  (120, "apple-touch-icon-120.png")):
        save(draw_mark(s, 0.15, rounded=False), nm, opaque=True)
    save(draw_mark(32, 0.08, rounded=True), "favicon-32.png")
    print("done")
