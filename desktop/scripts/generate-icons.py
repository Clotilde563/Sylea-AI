"""
Regenere toutes les icones Tauri (PNG multi-tailles + icon.ico multi-resolution)
a partir de sylea-logo-clean.svg.

Usage :
    python desktop/scripts/generate-icons.py

Dependances :
    pip install pycairo Pillow

Sorties dans desktop/src-tauri/icons/ :
    - 32x32.png, 128x128.png, 128x128@2x.png (256x256), icon.png (maitre haute res)
    - icon.ico avec 7 tailles embarquees (16, 24, 32, 48, 64, 128, 256)
"""
import io
import os
import sys
from pathlib import Path

try:
    import cairo
    from PIL import Image
except ImportError as e:
    print(f"Manque une dep : {e}. Installe avec : pip install pycairo Pillow")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent.parent
SVG_PATH = ROOT / "sylea-logo-clean.svg"
OUT_DIR = ROOT / "desktop" / "src-tauri" / "icons"
OUT_DIR.mkdir(parents=True, exist_ok=True)

if not SVG_PATH.exists():
    print(f"SVG introuvable : {SVG_PATH}")
    sys.exit(1)

# ---- Rendu haute resolution avec pycairo -------------------------------------
CANVAS = 1024
VB_W, VB_H = 280, 280       # canvas carre qui accueille le viewBox 200x280
OFFSET_X = (VB_W - 200) / 2 # centre horizontalement les 200 de large
scale = CANVAS / VB_W

surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS, CANVAS)
ctx = cairo.Context(surface)
ctx.scale(scale, scale)
ctx.translate(OFFSET_X, 0)


def s_path(c):
    """Chemin S re-implemente depuis le SVG (viewBox 200x280)."""
    c.move_to(140, 30)
    c.curve_to(140, 30, 160, 30, 160, 60)
    c.curve_to(160, 90, 100, 100, 100, 130)
    c.curve_to(100, 160, 160, 170, 160, 200)
    c.curve_to(160, 230, 140, 250, 100, 250)
    c.curve_to(60, 250, 40, 230, 40, 200)
    c.curve_to(40, 170, 100, 160, 100, 130)
    c.curve_to(100, 100, 40, 90, 40, 60)
    c.curve_to(40, 30, 60, 10, 100, 10)
    c.curve_to(140, 10, 160, 30, 140, 30)


# Gradients cyan -> bleu -> violet (identiques au SVG)
grad1 = cairo.LinearGradient(0, 0, 200, 280)
grad1.add_color_stop_rgb(0.00, 0x06 / 255, 0xb6 / 255, 0xd4 / 255)  # cyan
grad1.add_color_stop_rgb(0.50, 0x3b / 255, 0x82 / 255, 0xf6 / 255)  # bleu
grad1.add_color_stop_rgb(1.00, 0x8b / 255, 0x5c / 255, 0xf6 / 255)  # violet

grad2 = cairo.LinearGradient(0, 0, 200, 280)
grad2.add_color_stop_rgb(0.00, 0x3b / 255, 0x82 / 255, 0xf6 / 255)
grad2.add_color_stop_rgb(0.50, 0x63 / 255, 0x66 / 255, 0xf1 / 255)
grad2.add_color_stop_rgb(1.00, 0xa8 / 255, 0x55 / 255, 0xf7 / 255)

ctx.set_line_cap(cairo.LINE_CAP_ROUND)
ctx.set_line_join(cairo.LINE_JOIN_ROUND)

# Couche 1 : contour large gradient1
s_path(ctx)
ctx.set_line_width(28)
ctx.set_source(grad1)
ctx.stroke()

# Couche 2 : trait median gradient2
s_path(ctx)
ctx.set_line_width(12)
ctx.set_source(grad2)
ctx.stroke()

# Couche 3 : trait sombre interne pour la profondeur
s_path(ctx)
ctx.set_line_width(4)
ctx.set_source_rgb(0x0a / 255, 0x0a / 255, 0x1a / 255)
ctx.stroke()

# ---- Conversion Cairo -> PIL + padding carre ---------------------------------
buf = io.BytesIO()
surface.write_to_png(buf)
buf.seek(0)
img = Image.open(buf).convert("RGBA")

bbox = img.getbbox()
cropped = img.crop(bbox)
w, h = cropped.size
side = max(w, h)
margin = int(side * 0.08)  # 8 % de respiration
canvas_side = side + 2 * margin
canvas = Image.new("RGBA", (canvas_side, canvas_side), (0, 0, 0, 0))
canvas.paste(cropped, ((canvas_side - w) // 2, (canvas_side - h) // 2), cropped)
print(f"Canvas carre : {canvas.size}")

# ---- Exports PNG Tauri -------------------------------------------------------
master = OUT_DIR / "icon.png"
canvas.save(master, "PNG")
print(f"icon.png (maitre) : {canvas.size} -> {os.path.getsize(master)} octets")

for name, size in [("32x32.png", 32), ("128x128.png", 128), ("128x128@2x.png", 256)]:
    resized = canvas.resize((size, size), Image.LANCZOS)
    path = OUT_DIR / name
    resized.save(path, "PNG")
    print(f"  {name}: {size}x{size} -> {os.path.getsize(path)} octets")

# ---- ICO multi-resolution ----------------------------------------------------
ico_path = OUT_DIR / "icon.ico"
ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
canvas.save(ico_path, format="ICO", sizes=ico_sizes)
print(f"icon.ico : {os.path.getsize(ico_path)} octets avec {len(ico_sizes)} tailles")

with Image.open(ico_path) as ico:
    print(f"  -> tailles embarquees : {sorted(ico.ico.sizes())}")

print("Fini.")
