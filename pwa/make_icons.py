#!/usr/bin/env python3
"""
Generate the PWA / home-screen icons for the EM Waveguide Simulator.

The mark is the app's own motif: a guided wave travelling inside a rectangular
waveguide — a sine curve inside an open-ended tube, in the app's colours.

Run:  python pwa/make_icons.py        (needs Pillow)
Out:  pwa/icons/*.png
"""
import math, os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "icons")
os.makedirs(OUT, exist_ok=True)

BG      = (13, 17, 23)       # --panel dark, matches the app's dark surfaces
GUIDE   = (61, 220, 151)     # --accent green (waveguide walls)
WAVE    = (231, 240, 235)    # near-white (the wave itself)
COPPER  = (201, 163, 106)    # the app's copper accent (end flanges)


def draw_mark(size, pad_frac, rounded):
    """One icon at `size` px. pad_frac = fraction of the canvas kept clear
    (maskable icons need a generous safe zone because launchers crop them)."""
    S = size * 4                                  # supersample for clean curves
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # background plate
    if rounded:
        r = int(S * 0.22)
        d.rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=BG)
    else:
        d.rectangle([0, 0, S - 1, S - 1], fill=BG)

    pad = int(S * pad_frac)
    x0, x1 = pad, S - pad
    cy = S // 2
    half_h = int((x1 - x0) * 0.30)                # tube half-height
    lw = max(2, int(S * 0.028))                   # wall thickness

    # waveguide walls (top and bottom), open at both ends
    d.line([x0, cy - half_h, x1, cy - half_h], fill=GUIDE, width=lw)
    d.line([x0, cy + half_h, x1, cy + half_h], fill=GUIDE, width=lw)

    # end flanges, copper, to read as a metal guide rather than a plain box
    fl = max(2, int(lw * 0.9))
    d.line([x0, cy - half_h, x0, cy + half_h], fill=COPPER, width=fl)
    d.line([x1, cy - half_h, x1, cy + half_h], fill=COPPER, width=fl)

    # The guided wave: 1.5 periods, amplitude inside the tube. Drawn as a dense run of
    # filled discs rather than a wide polyline — PIL's thick-line joins leave serrated
    # edges on a curve, discs give a clean constant-width stroke with round caps.
    amp = half_h * 0.62
    stroke = max(2, int(S * 0.034))
    rad = stroke / 2.0
    n = 1600
    for i in range(n + 1):
        t = i / n
        x = x0 + (x1 - x0) * t
        y = cy - amp * math.sin(2 * math.pi * 1.5 * t)
        d.ellipse([x - rad, y - rad, x + rad, y + rad], fill=WAVE)

    return img.resize((size, size), Image.LANCZOS)


def save(img, name, keep_alpha=True):
    p = os.path.join(OUT, name)
    if keep_alpha:
        img.save(p, "PNG")
    else:                                          # iOS wants an opaque square
        flat = Image.new("RGB", img.size, BG)
        flat.paste(img, (0, 0), img)
        flat.save(p, "PNG")
    print(f"  {name:28s} {img.size[0]}x{img.size[1]}")


if __name__ == "__main__":
    print("writing icons to", OUT)
    # standard (any) icons — rounded plate, modest padding
    for s in (192, 512):
        save(draw_mark(s, 0.16, rounded=True), f"icon-{s}.png")
    # maskable — square plate, big safe zone so launcher masks never clip the mark
    for s in (192, 512):
        save(draw_mark(s, 0.28, rounded=False), f"icon-maskable-{s}.png")
    # iOS home screen: opaque, square, no transparency (iOS applies its own mask)
    save(draw_mark(180, 0.16, rounded=False), "apple-touch-icon.png", keep_alpha=False)
    # small favicon for the browser tab
    save(draw_mark(32, 0.10, rounded=True), "favicon-32.png")
    print("done")
