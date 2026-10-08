#!/usr/bin/env python3
"""
offset_weight.py — generate a faux bold or light UFO master from a single
source UFO, by offsetting every outline outward (bold) or inward (light).

This is the "Offset Curve" technique Glyphs/FontLab ship natively and
FontForge's Embolden used to do. It is NOT a substitute for real interpolation
masters — sharp corners get miter joins instead of proper optical correction,
counters can end up looking mechanical, and results are worth eyeballing
glyph-by-glyph in Fontra afterward. Treat this as a fast first pass, not a
finished bold.

Requirements:
    pip install ufoLib2 fonttools pyclipper --break-system-packages

Usage:
    python offset_weight.py Karrik-Regular.ufo Karrik-Bold.ufo --delta 32
    python offset_weight.py Karrik-Regular.ufo Karrik-Light.ufo --delta -20

`delta` is in font units (same units as the UFO's unitsPerEm, usually 1000).
Positive = bolder, negative = lighter. Start small (15-40) and look at real
glyphs before committing to a value across the whole set — how much offset
"reads" as one weight step depends entirely on Karrik's own stem widths,
which I haven't measured for you.

Glyphs made only of components (accented letters etc.) are left untouched
on purpose: they reference base glyphs that get offset in the same pass, so
they inherit the new weight automatically. Glyphs with real contours plus
components are offset only on their own contours — the component references
are left alone.

Three opt-in corrections, added after testing on the real Karrik outlines
(a plain uniform offset closes the apertures of a/e/S/6/9 well before it
reaches a bold weight, moves every glyph off the baseline and cap height,
and eats the sidebearings):

    --delta-y N           vertical offset, if different from --delta. Horizontal
                          strokes then gain less than vertical stems, which keeps
                          the (mostly vertical) aperture gaps open.
    --zones Z [Z ...]     vertical zones to hold in place, e.g. -190 0 500 680
                          (descender, baseline, x-height, cap height). Zones <= 0
                          are treated as bottom edges, zones > 0 as top edges.
    --keep-sidebearings   shift outlines by delta and add 2*delta to the advance
                          width, so sidebearings (and kerning) stay valid.

Output is a set of straight-line polygons (pyclipper doesn't speak Bezier).
That's fine for further scripted work or for pyclipper unioning purposes,
but it means every curved glyph will come out looking faceted rather than
smooth. Fontra's "Add extrema" / manual curve clean-up (or FontForge's
"Simplify" if you still have a working install, since that step in
particular is harmless) is the intended next step, not a bug to fix here.
"""

import argparse
import sys

import ufoLib2
import pyclipper
from fontTools.pens.basePen import BasePen

SCALE = 1000  # pyclipper needs integer coordinates; this preserves ~0.001 unit precision


class FlattenPen(BasePen):
    """Samples curves into short line segments so pyclipper can consume the outline."""

    def __init__(self, steps=10):
        super().__init__(glyphSet={})
        self.steps = steps
        self.contours = []
        self._current = []

    def _moveTo(self, pt):
        self._current = [pt]

    def _lineTo(self, pt):
        self._current.append(pt)

    def _curveToOne(self, p1, p2, p3):
        p0 = self._current[-1]
        for i in range(1, self.steps + 1):
            t = i / self.steps
            mt = 1 - t
            x = (mt**3) * p0[0] + 3 * (mt**2) * t * p1[0] + 3 * mt * (t**2) * p2[0] + (t**3) * p3[0]
            y = (mt**3) * p0[1] + 3 * (mt**2) * t * p1[1] + 3 * mt * (t**2) * p2[1] + (t**3) * p3[1]
            self._current.append((x, y))

    def _qCurveToOne(self, p1, p2):
        p0 = self._current[-1]
        for i in range(1, self.steps + 1):
            t = i / self.steps
            mt = 1 - t
            x = (mt**2) * p0[0] + 2 * mt * t * p1[0] + (t**2) * p2[0]
            y = (mt**2) * p0[1] + 2 * mt * t * p1[1] + (t**2) * p2[1]
            self._current.append((x, y))

    def _closePath(self):
        if self._current:
            self.contours.append(self._current)
        self._current = []

    def _endPath(self):
        # open paths shouldn't really occur in a filled glyph, but handle it rather than crash
        if self._current:
            self.contours.append(self._current)
        self._current = []


def offset_contours(contours, delta, miter_limit=2.5):
    """Runs all of a glyph's contours through pyclipper's offset engine at once,
    so contours that grow into each other get unioned instead of overlapping."""
    pco = pyclipper.PyclipperOffset()
    pco.MiterLimit = miter_limit
    for pts in contours:
        scaled = [(int(round(x * SCALE)), int(round(y * SCALE))) for x, y in pts]
        pco.AddPath(scaled, pyclipper.JT_MITER, pyclipper.ET_CLOSEDPOLYGON)
    result = pco.Execute(delta * SCALE)
    return [[(x / SCALE, y / SCALE) for x, y in p] for p in result]


def zone_shift(y, delta_y, zones):
    """Pre-compensation for the vertical growth: bottom zones (<= 0) are moved
    by +delta_y and top zones (> 0) by -delta_y before offsetting, so that edges
    sitting on a zone land back on it afterwards. Linear in between."""
    shifts = [(z, delta_y if z <= 0 else -delta_y) for z in sorted(zones)]
    if y <= shifts[0][0]:
        return y + shifts[0][1]
    if y >= shifts[-1][0]:
        return y + shifts[-1][1]
    for (z0, s0), (z1, s1) in zip(shifts, shifts[1:]):
        if z0 <= y <= z1:
            return y + s0 + (s1 - s0) * (y - z0) / (z1 - z0)


def process_glyph(glyph, delta, steps=10, delta_y=None, zones=None, x_shift=0):
    if len(glyph.contours) == 0:
        return False  # component-only glyph, nothing to offset

    fp = FlattenPen(steps=steps)
    glyph.draw(fp)
    if not fp.contours:
        return False

    if delta_y is None:
        delta_y = delta
    contours = fp.contours
    if zones:
        contours = [[(x, zone_shift(y, delta_y, zones)) for x, y in pts] for pts in contours]
    # pyclipper only offsets uniformly, so stretch y, offset by delta, squash back
    k = delta / delta_y
    contours = [[(x, y * k) for x, y in pts] for pts in contours]
    new_contours = offset_contours(contours, delta)
    new_contours = [[(x + x_shift, y / k) for x, y in pts] for pts in new_contours]

    glyph.clearContours()
    pen = glyph.getPen()
    for pts in new_contours:
        if len(pts) < 3:
            continue  # degenerate sliver, drop it
        pen.moveTo(pts[0])
        for pt in pts[1:]:
            pen.lineTo(pt)
        pen.closePath()
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input_ufo")
    ap.add_argument("output_ufo")
    ap.add_argument("--delta", type=float, required=True,
                     help="Offset in font units. Positive = bolder, negative = lighter.")
    ap.add_argument("--delta-y", type=float, default=None,
                     help="Vertical offset, if different from --delta (same sign, non-zero).")
    ap.add_argument("--zones", type=float, nargs="*", default=None,
                     help="Vertical zones to hold in place, e.g. --zones -190 0 500 680.")
    ap.add_argument("--keep-sidebearings", action="store_true",
                     help="Shift outlines by delta and widen advances by 2*delta.")
    ap.add_argument("--style-name", default=None,
                     help="Set styleName / PostScript names in the output fontinfo (e.g. Bold).")
    ap.add_argument("--copyright", default=None,
                     help="Set the copyright string (and OFL licence fields) in the output fontinfo.")
    ap.add_argument("--weight-class", type=int, default=None,
                     help="Set openTypeOS2WeightClass in the output fontinfo (e.g. 700).")
    ap.add_argument("--glyph-delta", nargs="*", default=[], metavar="NAME=DELTA",
                     help="Per-glyph --delta override, e.g. germandbls=14. 0 leaves the glyph untouched.")
    ap.add_argument("--steps", type=int, default=10,
                     help="Curve-flattening resolution per segment (default 10). Higher = smoother but more points.")
    ap.add_argument("--glyphs", nargs="*", default=None,
                     help="Only process these glyph names (e.g. --glyphs H O S g). Default: every glyph.")
    args = ap.parse_args()

    if args.delta_y is not None and args.delta_y * args.delta <= 0:
        ap.error("--delta-y must be non-zero and have the same sign as --delta")

    font = ufoLib2.Font.open(args.input_ufo)
    overrides = {k: float(v) for k, v in (item.split("=") for item in args.glyph_delta)}

    names = args.glyphs if args.glyphs else list(font.keys())
    changed, skipped = 0, 0
    for name in names:
        if name not in font:
            print(f"  ! glyph {name!r} not found, skipping", file=sys.stderr)
            continue
        glyph = font[name]
        # ponytail: overridden glyphs must not be component bases (shift would
        # no longer match the composites); true for the ones overridden so far
        delta = overrides.get(name, args.delta)
        if delta == 0:
            skipped += 1
            continue
        x_shift = delta if args.keep_sidebearings else 0
        if process_glyph(glyph, delta, steps=args.steps, delta_y=args.delta_y,
                         zones=args.zones, x_shift=x_shift):
            changed += 1
        else:
            skipped += 1
        if x_shift and (glyph.contours or glyph.components):
            if glyph.width > 0:
                glyph.width += 2 * x_shift
            for anchor in glyph.anchors:
                anchor.x += x_shift
            # base glyphs moved by x_shift in their own space; keep that true
            # through flipped/scaled component transforms too
            for comp in glyph.components:
                xx, xy, yx, yy, dx, dy = comp.transformation
                comp.transformation = (xx, xy, yx, yy,
                                       dx + x_shift - xx * x_shift, dy - xy * x_shift)

    info = font.info
    if args.style_name:
        info.styleName = args.style_name
        info.openTypeNamePreferredSubfamilyName = args.style_name
        info.postscriptWeightName = args.style_name
        info.postscriptFontName = f"{info.familyName}-{args.style_name}".replace(" ", "")
        info.postscriptFullName = f"{info.familyName} {args.style_name}"
        info.openTypeNameCompatibleFullName = info.postscriptFullName
        # style-linking: Bold / Bold Italic link to the base family, any other
        # weight becomes its own style-map family with regular / italic members
        words = args.style_name.split()
        italic = "Italic" in words
        weight = " ".join(w for w in words if w != "Italic")
        if weight == "Bold":
            info.styleMapFamilyName = info.familyName
            info.styleMapStyleName = "bold italic" if italic else "bold"
        else:
            info.styleMapFamilyName = f"{info.familyName} {weight}".strip()
            info.styleMapStyleName = "italic" if italic else "regular"
    if args.weight_class:
        info.openTypeOS2WeightClass = args.weight_class
    if args.copyright:
        info.copyright = args.copyright
        info.openTypeNameLicense = ("This Font Software is licensed under the SIL Open Font License, "
                                    "Version 1.1. This license is available with a FAQ at: "
                                    "https://openfontlicense.org")
        info.openTypeNameLicenseURL = "https://openfontlicense.org"

    font.save(args.output_ufo, overwrite=True)
    print(f"Wrote {args.output_ufo} — offset {changed} glyphs, left {skipped} untouched "
          f"(components / empty).")


if __name__ == "__main__":
    main()
