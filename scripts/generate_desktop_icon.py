#!/usr/bin/env python3
"""
Genere les icones binaires desktop (PNG + ICO) du logo Syléa en rose.

Le SVG du logo utilise un path Bezier cubique multi-couches (tube creux).
Pillow ne supporte pas directement les courbes Bezier ni les SVG, donc on :
  1. Discretise la courbe Bezier en N segments
  2. Dessine chaque couche (halo, bordure, gradient, canal, reflet) avec line()
  3. Pour le gradient : on dessine la ligne en sections de couleurs interpolees

Sorties (toutes ecrites dans desktop/src-tauri/icons/) :
  - icon.png        : 1024x1024 (source)
  - 128x128.png     : 128x128
  - 128x128@2x.png  : 256x256
  - 32x32.png       : 32x32
  - icon.ico        : multi-resolution ICO Windows

Usage :
  python scripts/generate_desktop_icon.py
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


# ─────────────────────────────────────────────────────────────────────────────
# Palette rose Syléa (identique au desktop SyleaLogo.tsx)
# ─────────────────────────────────────────────────────────────────────────────
# Bas (profond) -> Haut (clair)
GRADIENT_STOPS = [
    (0.00, (159, 18, 57)),     # #9f1239 - rose-900
    (0.30, (190, 24, 93)),     # #be185d - pink-700
    (0.65, (236, 72, 153)),    # #ec4899 - pink-500
    (1.00, (251, 207, 232)),   # #fbcfe8 - pink-200
]

# Couleur de halo (pour le flou exterieur)
HALO_COLOR = (236, 72, 153)  # #ec4899

# Bordure exterieure sombre
BORDER_COLOR = (2, 4, 16)

# Canal central creux
CHANNEL_COLOR = (5, 8, 16)

# Reflet speculaire (rose pale + transparence)
SPECULAR_COLOR = (255, 205, 225)


# ─────────────────────────────────────────────────────────────────────────────
# Geometrie du logo (path SVG Bezier cubique)
# ─────────────────────────────────────────────────────────────────────────────
# Path SVG : M 60 21 C 88 21, 88 45, 60 54 C 32 63, 32 87, 60 87
# Centre (60, 54) dans un viewBox 120x120.
# Decomposition :
#   - Curve 1 : start (60,21), c1=(88,21), c2=(88,45), end=(60,54)
#   - Curve 2 : start (60,54), c1=(32,63), c2=(32,87), end=(60,87)

VIEWBOX = 120
CURVE_SEGMENTS = 80  # 40 par sous-courbe x 2

# Tailles de stroke proportionnelles au viewBox 120
HALO_WIDTH = 30
BORDER_WIDTH = 20
BODY_WIDTH = 16
CHANNEL_WIDTH = 6
SPECULAR_WIDTH = 1.2


def cubic_bezier(t: float, p0, p1, p2, p3):
    """Retourne le point (x, y) a t (0..1) sur la courbe Bezier cubique."""
    u = 1.0 - t
    x = (u**3) * p0[0] + 3 * (u**2) * t * p1[0] + 3 * u * (t**2) * p2[0] + (t**3) * p3[0]
    y = (u**3) * p0[1] + 3 * (u**2) * t * p1[1] + 3 * u * (t**2) * p2[1] + (t**3) * p3[1]
    return (x, y)


def build_path_points(n: int = CURVE_SEGMENTS) -> list[tuple[float, float]]:
    """Discretise les 2 courbes Bezier du logo en N+1 points (en coords 0..120)."""
    half = n // 2
    points = []
    # Curve 1
    for i in range(half):
        t = i / half
        points.append(cubic_bezier(t, (60, 21), (88, 21), (88, 45), (60, 54)))
    # Curve 2 (inclut le point final)
    for i in range(half + 1):
        t = i / half
        points.append(cubic_bezier(t, (60, 54), (32, 63), (32, 87), (60, 87)))
    return points


def lerp_color(c1, c2, t):
    """Interpolation lineaire entre 2 couleurs RGB."""
    return tuple(int(c1[k] + (c2[k] - c1[k]) * t) for k in range(3))


def gradient_at(t: float) -> tuple[int, int, int]:
    """Retourne la couleur a t (0..1) en interpolant les stops du gradient.

    Le gradient SVG est applique de BAS (t=0 dans le path) -> HAUT (t=1).
    Notre path va de HAUT (premier point) -> BAS (dernier point).
    Donc on inverse t.
    """
    t = 1.0 - t  # haut du path = haut visuel = t=1 visuel = bas du SVG gradient
    # Bas du gradient (t=0) = rose fonce, haut (t=1) = rose pale
    for i in range(len(GRADIENT_STOPS) - 1):
        stop_a, color_a = GRADIENT_STOPS[i]
        stop_b, color_b = GRADIENT_STOPS[i + 1]
        if stop_a <= t <= stop_b:
            local_t = (t - stop_a) / (stop_b - stop_a) if stop_b > stop_a else 0
            return lerp_color(color_a, color_b, local_t)
    return GRADIENT_STOPS[-1][1]


def draw_thick_path(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    color: tuple,
    width: float,
    scale: float,
):
    """Dessine un path en segments avec une couleur uniforme (round caps)."""
    scaled = [(p[0] * scale, p[1] * scale) for p in points]
    w = max(1, int(round(width * scale)))
    # ImageDraw.line avec width >= 1 + joints rounds
    draw.line(scaled, fill=color + (255,) if len(color) == 3 else color, width=w, joint="curve")
    # Dessine des cercles aux extremites pour le strokeLinecap="round"
    for p in (scaled[0], scaled[-1]):
        r = w / 2
        draw.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=color + (255,) if len(color) == 3 else color)


def draw_gradient_path(
    img: Image.Image,
    points: list[tuple[float, float]],
    width: float,
    scale: float,
):
    """Dessine un path avec gradient en N segments couleur interpolee."""
    n = len(points) - 1
    w = max(1, int(round(width * scale)))
    draw = ImageDraw.Draw(img)
    for i in range(n):
        t = i / n
        color = gradient_at(t) + (255,)
        p1 = (points[i][0] * scale, points[i][1] * scale)
        p2 = (points[i + 1][0] * scale, points[i + 1][1] * scale)
        draw.line([p1, p2], fill=color, width=w)
        # Cercle au point pour eviter les trous aux joints
        r = w / 2
        draw.ellipse(
            [p1[0] - r, p1[1] - r, p1[0] + r, p1[1] + r],
            fill=color,
        )
    # Dernier cercle a la fin
    pn = (points[-1][0] * scale, points[-1][1] * scale)
    r = w / 2
    color_end = gradient_at(1.0) + (255,)
    draw.ellipse(
        [pn[0] - r, pn[1] - r, pn[0] + r, pn[1] + r],
        fill=color_end,
    )


def render_logo(size: int) -> Image.Image:
    """Genere une image PNG du logo Syléa rose a la taille `size`.

    Approche multi-couches comme dans le SVG :
      1. Halo flou (blur 5px)
      2. Bordure exterieure sombre
      3. Corps gradient (rose fonce -> rose pale)
      4. Canal central creux (sombre)
      5. Reflet speculaire (rose pale)

    Le fond reste TRANSPARENT pour avoir une icone propre.
    """
    scale = size / VIEWBOX
    points = build_path_points()

    # Image finale avec alpha
    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # ── Couche 1 : Halo (path epais + blur) ─────────────────────────────────
    halo = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    halo_draw = ImageDraw.Draw(halo)
    halo_color = HALO_COLOR + (90,)  # alpha 90/255 = ~0.35 (opacite du halo)
    w_halo = max(1, int(HALO_WIDTH * scale))
    scaled_pts = [(p[0] * scale, p[1] * scale) for p in points]
    halo_draw.line(scaled_pts, fill=halo_color, width=w_halo, joint="curve")
    for p in (scaled_pts[0], scaled_pts[-1]):
        r = w_halo / 2
        halo_draw.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=halo_color)
    # Blur le halo
    halo = halo.filter(ImageFilter.GaussianBlur(radius=max(2, int(5 * scale))))
    base.alpha_composite(halo)

    # ── Couche 2 : Bordure exterieure sombre ────────────────────────────────
    border = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    border_draw = ImageDraw.Draw(border)
    draw_thick_path(border_draw, points, BORDER_COLOR + (247,), BORDER_WIDTH, scale)
    base.alpha_composite(border)

    # ── Couche 3 : Corps gradient (rails) ───────────────────────────────────
    body = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw_gradient_path(body, points, BODY_WIDTH, scale)
    base.alpha_composite(body)

    # ── Couche 4 : Canal central creux ──────────────────────────────────────
    channel = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    channel_draw = ImageDraw.Draw(channel)
    # strokeLinecap=butt : ne pas dessiner de cercles aux extremites
    # On dessine juste la ligne sans ellipses
    w_chan = max(1, int(round(CHANNEL_WIDTH * scale)))
    scaled_pts = [(p[0] * scale, p[1] * scale) for p in points]
    channel_draw.line(scaled_pts, fill=CHANNEL_COLOR + (255,), width=w_chan, joint="curve")
    base.alpha_composite(channel)

    # ── Couche 5 : Reflet speculaire ────────────────────────────────────────
    spec = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    spec_draw = ImageDraw.Draw(spec)
    # Specular avec alpha ~165/255 = 0.65
    spec_color = SPECULAR_COLOR + (165,)
    w_spec = max(1, int(round(SPECULAR_WIDTH * scale)))
    scaled_pts = [(p[0] * scale, p[1] * scale) for p in points]
    spec_draw.line(scaled_pts, fill=spec_color, width=w_spec, joint="curve")
    for p in (scaled_pts[0], scaled_pts[-1]):
        r = w_spec / 2
        spec_draw.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=spec_color)
    base.alpha_composite(spec)

    return base


def main():
    # Repertoire des icones Tauri
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    icons_dir = repo_root / "desktop" / "src-tauri" / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)

    # Tailles a generer (correspond aux fichiers attendus par Tauri)
    sizes = {
        "icon.png": 1024,        # source haute resolution
        "128x128@2x.png": 256,
        "128x128.png": 128,
        "32x32.png": 32,
    }

    print(f"[icons] Generation dans {icons_dir}")
    for filename, size in sizes.items():
        out_path = icons_dir / filename
        print(f"  - {filename} ({size}x{size})...", end=" ", flush=True)
        img = render_logo(size)
        img.save(out_path, format="PNG", optimize=True)
        print("OK")

    # ICO multi-resolution Windows
    print("  - icon.ico (multi-res Windows)...", end=" ", flush=True)
    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    base_img = render_logo(256)
    base_img.save(
        icons_dir / "icon.ico",
        format="ICO",
        sizes=[(s, s) for s in ico_sizes],
    )
    print("OK")

    # ICNS macOS (best effort - Pillow >= 8.0)
    try:
        print("  - icon.icns (macOS)...", end=" ", flush=True)
        icns_img = render_logo(1024)
        icns_img.save(icons_dir / "icon.icns", format="ICNS")
        print("OK")
    except Exception as e:
        print(f"SKIP ({e})")

    print("\n[icons] DONE. Pour appliquer au desktop :")
    print("  1. cd desktop && npm run tauri build  (release, ~5-10 min)")
    print("  2. Ou pour tester rapidement : npm run tauri dev")


if __name__ == "__main__":
    main()
