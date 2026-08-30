#!/usr/bin/env python3
"""Згенерувати комплект іконок PWA з ЄДИНОГО джерела — design/icon.svg.

Іконка, закомічена як бінарник без генератора, — артефакт без походження: її не
можна ні перевірити, ні відтворити, ні змінити разом із темою. Тут PNG завжди
похідні від SVG, а SVG повторює `clip-path` знака `.mark` зі styles.css.

    python3 apps/web/scripts/generate_icons.py

`maskable` робиться окремим файлом із запасом: Android вписує іконку в маску
довільної форми й обрізає все поза центральним колом у 80% ширини. Той самий
файл не може бути одночасно `any` і `maskable` — у першому випадку поля
виглядають зайвими, у другому їх бракує.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cairosvg

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "design" / "icon.svg"
OUT = ROOT / "public" / "icons"

#: (ім'я, розмір, поле у частках сторони). Поле 0 — знак на всю площину.
#: 0.1 — 10% з кожного боку: знак лягає у центральні 80%, тобто в безпечну зону
#: маски Android.
TARGETS = [
    ("icon-192.png", 192, 0.0),
    ("icon-512.png", 512, 0.0),
    ("icon-maskable-512.png", 512, 0.10),
    ("apple-touch-icon.png", 180, 0.06),
]


def render(size: int, pad: float) -> bytes:
    inner = round(size * (1 - 2 * pad))
    png = cairosvg.svg2png(url=str(SRC), output_width=inner, output_height=inner)
    if pad == 0.0:
        return png
    from io import BytesIO

    from PIL import Image

    canvas = Image.new("RGBA", (size, size), (1, 1, 1, 255))
    mark = Image.open(BytesIO(png)).convert("RGBA")
    off = (size - inner) // 2
    canvas.alpha_composite(mark, (off, off))
    buf = BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def main() -> int:
    if not SRC.is_file():
        print(f"немає джерела: {SRC}", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size, pad in TARGETS:
        data = render(size, pad)
        (OUT / name).write_bytes(data)
        print(f"  {name:<26} {size}×{size}  {len(data):>6} б")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
