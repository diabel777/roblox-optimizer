"""Generuje assets/icon.ico (wielorozmiarowa ikona: fioletowy kafelek z błyskawicą). Uruchamia to build.ps1."""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "assets" / "icon.ico"


def render(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # gradient po przekątnej: #7C5CFF -> #A78BFF
    grad = Image.new("RGBA", (size, size))
    px = grad.load()
    a, b = (124, 92, 255), (167, 139, 255)
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            px[x, y] = (*(round(a[i] + (b[i] - a[i]) * t) for i in range(3)), 255)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=int(size * 0.23), fill=255)
    img.paste(grad, (0, 0), mask)
    s = size / 100
    bolt = [(57, 12), (24, 56), (46, 56), (40, 88), (76, 42), (53, 42)]
    ImageDraw.Draw(img).polygon([(x * s, y * s) for x, y in bolt], fill=(255, 255, 255, 255))
    return img


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    big = render()
    big.save(OUT, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("Zapisano", OUT)


if __name__ == "__main__":
    main()
