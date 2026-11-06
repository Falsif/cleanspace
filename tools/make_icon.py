"""Генерирует иконку CleanSpace (assets/icon.png и assets/icon.ico). Нужен Pillow."""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024
OUT = Path(__file__).resolve().parent.parent / "assets"


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def build():
    blue, teal, purple = (59, 130, 246), (20, 184, 166), (139, 92, 246)
    grad = Image.new("RGB", (S, S))
    px = grad.load()
    for y in range(S):
        for x in range(S):
            t = (x + y) / (2 * S)
            px[x, y] = lerp(teal, blue, t / 0.45) if t < 0.45 else lerp(blue, purple, (t - 0.45) / 0.55)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=230, fill=255)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    # мягкий блик сверху
    glow = Image.new("L", (S, S), 0)
    ImageDraw.Draw(glow).ellipse([-200, -520, S + 200, 420], fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    white = Image.new("RGBA", (S, S), (255, 255, 255, 0))
    white.putalpha(Image.composite(glow, Image.new("L", (S, S), 0), mask))
    img = Image.alpha_composite(img, white)

    d = ImageDraw.Draw(img)
    cx, cy, r, w = S // 2 - 40, S // 2 + 40, 300, 92
    # кольцо диска (дорожка + заполнение)
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 80), width=w)
    img = Image.alpha_composite(img, layer)
    d = ImageDraw.Draw(img)
    d.arc([cx - r, cy - r, cx + r, cy + r], start=-90, end=170, fill=(255, 255, 255, 255), width=w)
    for ang in (-90, 170):  # скруглённые концы
        a = math.radians(ang)
        ex, ey = cx + (r - w / 2) * math.cos(a), cy + (r - w / 2) * math.sin(a)
        d.ellipse([ex - w / 2, ey - w / 2, ex + w / 2, ey + w / 2], fill=(255, 255, 255, 255))
    # искорка «чистоты»
    sx, sy, R = 760, 270, 150

    def star(x, y, R, k):
        pts = []
        for i in range(8):
            a = math.pi / 4 * i - math.pi / 2
            rr = R if i % 2 == 0 else R * k
            pts.append((x + rr * math.cos(a), y + rr * math.sin(a)))
        return pts
    d.polygon(star(sx, sy, R, 0.26), fill=(255, 255, 255, 255))
    d.polygon(star(sx + 110, sy + 170, 60, 0.3), fill=(255, 255, 255, 230))
    return img


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    img = build()
    img.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")
    img.resize((512, 512), Image.LANCZOS).save(OUT / "icon_512.png")
    img.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("OK:", OUT)
