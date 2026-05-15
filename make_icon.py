#!/usr/bin/env python3
"""
Generate AppIcon.icns from the Delivery Hero favicon.
Re-run if you want to refresh the icon (e.g. after the favicon changes).

Output: ./AppIcon.icns and ClaudeLocal.app/Contents/Resources/AppIcon.icns

Requires Pillow. Install with: python3 -m pip install --user Pillow
"""
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path
from urllib.request import urlretrieve

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
FAVICON_URL = (
    "https://benefits.deliveryhero.net/wp-content/themes/wp-delivery-hero-core-v2"
    "/assets/img/intranet/favicons/favicon-32x32.png"
)
FAVICON = HERE / ".cache" / "dh_favicon.png"
ICONSET = HERE / ".cache" / "ClaudeLocal.iconset"
ICNS_DEST_TOP = HERE / "AppIcon.icns"
ICNS_DEST_APP = HERE / "ClaudeLocal.app" / "Contents" / "Resources" / "AppIcon.icns"

CREAM = (245, 244, 238, 255)

# Apple-spec iconset entries (filename -> pixel size)
SIZES = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]


def main() -> None:
    FAVICON.parent.mkdir(parents=True, exist_ok=True)
    if not FAVICON.exists():
        print(f"Downloading {FAVICON_URL}")
        urlretrieve(FAVICON_URL, FAVICON)

    if ICONSET.exists():
        shutil.rmtree(ICONSET)
    ICONSET.mkdir()

    fav = Image.open(FAVICON).convert("RGBA")

    for fname, size in SIZES:
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

        # Cream rounded-square background (macOS squircle approximation)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, size - 1, size - 1),
            radius=int(size * 0.225),
            fill=255,
        )
        cream = Image.new("RGBA", (size, size), CREAM)
        canvas.paste(cream, (0, 0), mask)

        # Foreground: favicon scaled to ~60% of canvas, centered
        fg_size = max(8, int(size * 0.60))
        fg = fav.resize((fg_size, fg_size), Image.LANCZOS)
        fg_offset = ((size - fg_size) // 2, (size - fg_size) // 2)

        # Soft drop shadow under the foreground (large icons only)
        if size >= 128:
            shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            s_off = (fg_offset[0], fg_offset[1] + max(1, size // 96))
            shadow.paste(Image.new("RGBA", (fg_size, fg_size), (0, 0, 0, 60)), s_off, fg)
            shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, size // 96)))
            canvas = Image.alpha_composite(canvas, shadow)

        fg_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        fg_layer.paste(fg, fg_offset, fg)
        canvas = Image.alpha_composite(canvas, fg_layer)

        canvas.save(ICONSET / fname, "PNG")

    print(f"Iconset assembled at {ICONSET}")

    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET), "-o", str(ICNS_DEST_TOP)],
        check=True,
    )
    print(f"Wrote {ICNS_DEST_TOP}")

    if ICNS_DEST_APP.parent.exists():
        shutil.copy(ICNS_DEST_TOP, ICNS_DEST_APP)
        print(f"Wrote {ICNS_DEST_APP}")


if __name__ == "__main__":
    main()
