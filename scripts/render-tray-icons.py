#!/usr/bin/env python3
"""
Render assets/icon-{gray,red,green,yellow}.svg to assets/icon-{color}.png for the tray.
Run from repo root: python3 scripts/render-tray-icons.py
Requires: cairosvg, Pillow
"""
import io
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ASSETS = os.path.join(ROOT, "assets")
SIZE = 64  # match tray icon size exactly so no resize = sharp

def main():
    try:
        import cairosvg
        from PIL import Image
    except ImportError as e:
        sys.stderr.write(f"Need cairosvg and Pillow: pip install cairosvg Pillow\n")
        sys.exit(1)

    colors = ("gray", "red", "green", "yellow")
    for color in colors:
        svg_path = os.path.join(ASSETS, f"icon-{color}.svg")
        png_path = os.path.join(ASSETS, f"icon-{color}.png")
        if not os.path.isfile(svg_path):
            sys.stderr.write(f"Skip {color}: missing {svg_path}\n")
            continue
        try:
            with open(svg_path, "rb") as f:
                png_bytes = cairosvg.svg2png(
                    file_obj=f,
                    output_width=SIZE,
                    output_height=SIZE,
                )
            img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
            img.save(png_path, "PNG")
            print(f"Wrote {png_path}")
        except Exception as e:
            sys.stderr.write(f"Error rendering {color}: {e}\n")
            sys.exit(1)
    print("Done.")

if __name__ == "__main__":
    main()
