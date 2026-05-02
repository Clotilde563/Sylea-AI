"""
Regenere toutes les icones Tauri (PNG multi-tailles + icon.ico multi-resolution)
en reproduisant FIDELEMENT le logo du composant React `SyleaLogo.tsx` desktop
(S ouvert, pas figure-8 fermee).

Chaque taille ICO est rendue NATIVEMENT avec des contours adaptes :
les petites tailles (16-32) utilisent des strokes proportionnellement plus
epais pour rester lisibles dans la barre des taches Windows.

Version retro rose/violet — palette desktop qui se distingue du web
(violet -> cyan).

Usage :
    python desktop/scripts/generate-icons.py

Dependances :
    pip install pycairo Pillow
"""
import io
import os
import struct
import sys
from pathlib import Path

try:
    import cairo
    from PIL import Image
except ImportError as e:
    print(f"Manque une dep : {e}. Installe avec : pip install pycairo Pillow")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = ROOT / "desktop" / "src-tauri" / "icons"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---- Parametres geometriques (identiques au composant React SyleaLogo) ------
# ViewBox 120 x 120, centre (60, 54). Chemin S ouvert a deux bulges.
VB = 120
CX, CY = 60, 54
# S_PATH React : M 60 21 C 88 21, 88 45, 60 54 C 32 63, 32 87, 60 87
P0 = (CX, CY - 33)              # (60, 21)
C1 = (CX + 28, CY - 33)         # (88, 21)
C2 = (CX + 28, CY - 9)          # (88, 45)
P1 = (CX, CY)                   # (60, 54)
C3 = (CX - 28, CY + 9)          # (32, 63)
C4 = (CX - 28, CY + 33)         # (32, 87)
P2 = (CX, CY + 33)              # (60, 87)


def s_path(c):
    """Trace le chemin S ouvert identique au composant React."""
    c.move_to(*P0)
    c.curve_to(*C1, *C2, *P1)
    c.curve_to(*C3, *C4, *P2)


# ---- Palette retro rose/violet ----------------------------------------------
# Gradient vertical : plum profond (bas) -> rose chaud (haut)
GRADIENT_STOPS = [
    (0.00, 0x3d, 0x14, 0x61),   # plum profond — bas
    (0.30, 0x7c, 0x3a, 0xed),   # violet electrique
    (0.65, 0xd9, 0x46, 0xef),   # fuchsia
    (1.00, 0xec, 0x48, 0x99),   # rose chaud — haut
]

SPECULAR_RGBA = (0xff, 0xdc, 0xf0, 0.60)
DARK_BG = (0x05, 0x08, 0x10)
DARK_OUTLINE = (0x02, 0x04, 0x10, 0.97)


def render_logo(size_px: int, bold: bool = False) -> Image.Image:
    """Rend le logo a la taille indiquee.

    STRATEGIE DE LISIBILITE PAR TAILLE :
    - bold=True (tailles <= 32 px) : on rend un S SOLIDE (pas de canal central
      creux, pas de reflet speculaire). Le canal creux cree deux boucles
      fermees aux petites tailles, ce qui fait lire "8". Sans lui, le S est
      un trait plein continu — lisible et sans ambiguite.
    - bold=False (tailles >= 48 px) : rendu complet a 4 couches (contour,
      corps gradient, canal creux, reflet) comme dans SyleaLogo.tsx — il y
      a assez de pixels pour que le canal creux se lise comme un effet tube
      et non comme deux trous.
    """
    # Super-sampling eleve (12x pour small, 4x pour large) pour avoir des
    # strokes parfaitement lisses apres downscale LANCZOS — pas de pixelisation.
    render_px = max(size_px * 12, 768) if bold else max(size_px * 4, 512)
    scale = render_px / VB

    if bold:
        # Tailles <= 32 px : S plein, contour epais, bulges exageres
        sw_outline  = 28   # contour sombre bien visible
        sw_body     = 22   # corps plein (pas de canal creux en dessous)
    else:
        # Tailles >= 48 px : proportions du composant React
        sw_outline  = 20
        sw_body     = 16
        sw_center   = 6
        sw_specular = 1.2

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, render_px, render_px)
    ctx = cairo.Context(surface)
    ctx.scale(scale, scale)

    # Gradient vertical (bas -> haut) — Cairo : (CX, VB) -> (CX, 0)
    grad = cairo.LinearGradient(CX, VB, CX, 0)
    for offset, r, g, b in GRADIENT_STOPS:
        grad.add_color_stop_rgb(offset, r / 255, g / 255, b / 255)

    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)

    # Couche 1 — contour exterieur sombre
    s_path(ctx)
    ctx.set_line_width(sw_outline)
    ctx.set_source_rgba(DARK_OUTLINE[0] / 255, DARK_OUTLINE[1] / 255,
                        DARK_OUTLINE[2] / 255, DARK_OUTLINE[3])
    ctx.stroke()

    # Couche 2 — corps gradient (plein en mode bold, tube en mode normal)
    s_path(ctx)
    ctx.set_line_width(sw_body)
    ctx.set_source(grad)
    ctx.stroke()

    if not bold:
        # Couche 3 — canal central creux (UNIQUEMENT en mode normal >= 48 px)
        # cap plat pour ne pas deborder aux extremites
        ctx.set_line_cap(cairo.LINE_CAP_BUTT)
        s_path(ctx)
        ctx.set_line_width(sw_center)
        ctx.set_source_rgb(DARK_BG[0] / 255, DARK_BG[1] / 255, DARK_BG[2] / 255)
        ctx.stroke()

        # Couche 4 — reflet speculaire
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        s_path(ctx)
        ctx.set_line_width(sw_specular)
        ctx.set_source_rgba(SPECULAR_RGBA[0] / 255, SPECULAR_RGBA[1] / 255,
                            SPECULAR_RGBA[2] / 255, SPECULAR_RGBA[3])
        ctx.stroke()
    else:
        # Mode bold : un mini reflet clair sur le rail, donne du relief
        # sans creer de canal sombre qui lit comme "8".
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        s_path(ctx)
        ctx.set_line_width(3)
        ctx.set_source_rgba(1, 1, 1, 0.25)
        ctx.stroke()

    # Cairo -> PIL
    buf = io.BytesIO()
    surface.write_to_png(buf)
    buf.seek(0)
    img = Image.open(buf).convert("RGBA")

    # Crop + padding carre
    bbox = img.getbbox()
    if bbox is None:
        raise RuntimeError("Image vide")
    cropped = img.crop(bbox)
    w, h = cropped.size
    side = max(w, h)
    # Marge un peu plus grande en mode bold pour que le S ne touche pas le
    # bord de l'icone (Windows ajoute parfois un halo autour)
    margin_ratio = 0.10 if bold else 0.12
    margin = int(side * margin_ratio)
    canvas_side = side + 2 * margin
    canvas = Image.new("RGBA", (canvas_side, canvas_side), (0, 0, 0, 0))
    canvas.paste(cropped, ((canvas_side - w) // 2, (canvas_side - h) // 2), cropped)

    # Downscale final LANCZOS — donne des bords propres et nets
    return canvas.resize((size_px, size_px), Image.LANCZOS)


# ---- Rendu de toutes les tailles --------------------------------------------
# (px, bold) — bold=True pour les tailles <= 32 ou le S a besoin de strokes
# epaissies pour rester lisible
SIZE_CONFIG = [
    (16,  True),
    (24,  True),
    (32,  True),
    (48,  False),
    (64,  False),
    (128, False),
    (256, False),
]

frames = []
for size_px, bold in SIZE_CONFIG:
    frame = render_logo(size_px, bold=bold)
    frames.append(frame)
    print(f"rendu {size_px}x{size_px}" + (" (bold)" if bold else ""))

# ---- Exports PNG Tauri (tailles Tauri standard) ------------------------------
# icon.png maitre = 512x512 (utilise pour packaging Linux/macOS)
master = render_logo(512, bold=False)
master_path = OUT_DIR / "icon.png"
master.save(master_path, "PNG")
print(f"icon.png : {master.size} -> {os.path.getsize(master_path)} octets")

size_map = {(s, s): f for (s, _), f in zip(SIZE_CONFIG, frames)}
for name, (w, h) in [
    ("32x32.png",      (32, 32)),
    ("128x128.png",    (128, 128)),
    ("128x128@2x.png", (256, 256)),
]:
    frame = size_map.get((w, h))
    if frame is None:
        frame = render_logo(w, bold=(w <= 32))
    frame.save(OUT_DIR / name, "PNG")
    print(f"  {name}: {w}x{h} -> {os.path.getsize(OUT_DIR / name)} octets")

# ---- ICO multi-resolution (chaque taille rendue nativement) -----------------
# PIL's ICO writer ne supporte pas fiablement append_images avec des frames
# a resolutions differentes (selon la version, il downscale la frame de base
# ou ignore les autres). On ecrit donc le fichier ICO manuellement en
# embarquant un PNG pour chaque taille — format supporte nativement par
# Windows Vista+ et Tauri.
#
# Format ICO :
#   6 octets header : reserved(2) + type(2=ICO) + count(2)
#   Par image, 16 octets :
#     width(1, 0=256) + height(1, 0=256) + colors(1) + reserved(1)
#     planes(2) + bpp(2) + byteSize(4) + offset(4)
#   Puis les blobs PNG concatenes.

def build_ico(frame_list) -> bytes:
    count = len(frame_list)
    png_blobs = []
    for img in frame_list:
        buf = io.BytesIO()
        img.save(buf, "PNG")
        png_blobs.append(buf.getvalue())

    header = struct.pack("<HHH", 0, 1, count)
    dir_size = 16 * count
    first_offset = len(header) + dir_size

    directory = b""
    offset = first_offset
    for img, blob in zip(frame_list, png_blobs):
        w, h = img.size
        directory += struct.pack(
            "<BBBBHHII",
            0 if w == 256 else w,   # width (0 = 256)
            0 if h == 256 else h,   # height
            0,                       # palette colors (0 for PNG)
            0,                       # reserved
            1,                       # color planes
            32,                      # bits per pixel
            len(blob),               # image data size
            offset,                  # image data offset
        )
        offset += len(blob)

    return header + directory + b"".join(png_blobs)


ico_path = OUT_DIR / "icon.ico"
with open(ico_path, "wb") as f:
    f.write(build_ico(frames))
print(f"icon.ico : {os.path.getsize(ico_path)} octets")

with Image.open(ico_path) as ico:
    print(f"  -> tailles embarquees : {sorted(ico.ico.sizes())}")

# Nettoyage des previews temporaires eventuels
for f in OUT_DIR.glob("_preview_*.png"):
    f.unlink()

print("Fini.")
