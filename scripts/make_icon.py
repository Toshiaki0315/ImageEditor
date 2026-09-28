"""アプリアイコン (.icns) を Pillow で描画して生成する。

使い方:
    python scripts/make_icon.py build/icon/ImageEditor.icns

macOS の iconutil を使って .iconset から .icns に変換する。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

CANVAS = 1024
# macOS のアイコングリッド: 1024 の中に 824 の角丸四角（余白 100）
MARGIN = 100
RADIUS = 185
# iconutil が要求するサイズ (ポイント, 倍率)
ICONSET_SIZES = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2), (256, 1), (256, 2),
                 (512, 1), (512, 2)]  # fmt: skip


def draw_icon(size: int = CANVAS) -> Image.Image:
    """アイコンを 1024px で描いて size に縮小して返す。"""
    icon = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    box = (MARGIN, MARGIN, CANVAS - MARGIN, CANVAS - MARGIN)

    # 影
    shadow = Image.new("RGBA", icon.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (box[0], box[1] + 12, box[2], box[3] + 12), RADIUS, fill=(0, 0, 0, 90)
    )
    icon.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))

    # 背景: 夕焼けのグラデーション
    top, bottom = (255, 176, 92), (214, 72, 120)
    gradient = Image.linear_gradient("L").resize((CANVAS, CANVAS))
    background = Image.composite(
        Image.new("RGBA", icon.size, (*bottom, 255)),
        Image.new("RGBA", icon.size, (*top, 255)),
        gradient,
    )
    mask = Image.new("L", icon.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, RADIUS, fill=255)
    icon.paste(background, (0, 0), mask)

    # ポラロイド風の白い写真（少し傾ける）
    photo = Image.new("RGBA", (520, 600), (0, 0, 0, 0))
    draw = ImageDraw.Draw(photo)
    draw.rounded_rectangle((0, 0, 519, 599), 18, fill=(255, 253, 248, 255))
    inner = (32, 32, 488, 468)
    draw.rectangle(inner, fill=(92, 170, 230, 255))
    # 太陽と山
    draw.ellipse((300, 80, 410, 190), fill=(255, 214, 90, 255))
    draw.polygon([(32, 468), (190, 250), (300, 380), (360, 310), (488, 468)], fill=(46, 125, 90))
    draw.polygon([(190, 250), (225, 298), (160, 292)], fill=(240, 248, 245))
    photo = photo.rotate(-8, resample=Image.Resampling.BICUBIC, expand=True)

    photo_shadow = Image.new("RGBA", photo.size, (0, 0, 0, 0))
    photo_shadow.paste((0, 0, 0, 110), (0, 0), photo.getchannel("A"))
    photo_shadow = photo_shadow.filter(ImageFilter.GaussianBlur(16))
    x = (CANVAS - photo.width) // 2
    y = (CANVAS - photo.height) // 2
    icon.alpha_composite(photo_shadow, (x + 6, y + 18))
    icon.alpha_composite(photo, (x, y))

    if size != CANVAS:
        icon = icon.resize((size, size), Image.Resampling.LANCZOS)
    return icon


def make_icns(output: Path) -> None:
    """アイコンを描画し、iconutil で .icns に変換して output に書き出す。"""
    if shutil.which("iconutil") is None:
        raise SystemExit("iconutil が見つかりません（macOS でのみ実行できます）")
    master = draw_icon()
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "ImageEditor.iconset"
        iconset.mkdir()
        for points, scale in ICONSET_SIZES:
            suffix = "" if scale == 1 else f"@{scale}x"
            pixels = points * scale
            image = master.resize((pixels, pixels), Image.Resampling.LANCZOS)
            image.save(iconset / f"icon_{points}x{points}{suffix}.png")
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(output)], check=True)


if __name__ == "__main__":
    make_icns(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("build/icon/ImageEditor.icns"))
