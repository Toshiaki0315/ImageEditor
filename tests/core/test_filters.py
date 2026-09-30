import subprocess
import sys

import pytest
from PIL import Image, ImageChops, ImageStat

from image_editor.core.filters import (
    FilterType,
    add_grain,
    apply_filter,
)

WHITE = (255, 255, 255)


def make_sample(mode: str = "RGB") -> Image.Image:
    """4 色の帯を持つ 200x100 画像。"""
    image = Image.new("RGB", (200, 100))
    for i, color in enumerate([(200, 60, 40), (40, 160, 80), (50, 70, 210), (128, 128, 128)]):
        image.paste(color, (i * 50, 0, (i + 1) * 50, 100))
    return image.convert(mode)


def sample_points(image: Image.Image, offset: tuple[int, int] = (0, 0)):
    ox, oy = offset
    return [image.getpixel((ox + 25 + i * 50, oy + 50)) for i in range(4)]


# --- FilterType -------------------------------------------------------------


def test_filter_labels():
    assert [f.label for f in FilterType] == [
        "なし",
        "セピア",
        "モノトーン",
        "ハイトーン",
        "ポラロイド風",
        "ポジフィルム風",
        "レトロカメラ風",
        "ハイキー",
        "ローキー",
        "ドラマチック",
        "モダン",
        "ナチュラル",
        "シネマティック",
        "ノワール",
        "ブリーチバイパス",
        "パステル",
        "クロスプロセス",
        "青写真",
        "夏らしい",
        "秋らしい",
        "ソフトフォーカス",
        "HDR 風",
        "赤外線風",
    ]


# --- 各フィルター -------------------------------------------------------------


def test_none_returns_equal_copy():
    image = make_sample()

    result = apply_filter(image, FilterType.NONE)

    assert result is not image
    assert result.tobytes() == image.tobytes()


def test_sepia():
    image = make_sample()

    result = apply_filter(image, FilterType.SEPIA)

    assert result.mode == "RGB"
    assert result.size == image.size
    for r, g, b in sample_points(result):
        assert r >= g >= b
        assert r > b


def test_sepia_clips_to_255():
    result = apply_filter(Image.new("RGB", (4, 4), WHITE), FilterType.SEPIA)
    assert result.getpixel((0, 0)) == (255, 189, 110)


def test_monotone():
    image = make_sample()

    result = apply_filter(image, FilterType.MONOTONE)

    assert result.mode == "RGB"
    assert result.size == image.size
    points = sample_points(result)
    for r, g, b in points:
        assert r == g == b
    assert len(set(points)) > 1  # 階調が残っている


def test_high_tone_is_brighter():
    image = make_sample()

    result = apply_filter(image, FilterType.HIGH_TONE)

    assert result.mode == "RGB"
    assert result.size == image.size
    gray_before = image.getpixel((175, 50))
    gray_after = result.getpixel((175, 50))
    assert sum(gray_after) > sum(gray_before)


def test_polaroid_changes_only_color():
    image = make_sample()

    result = apply_filter(image, FilterType.POLAROID)

    # 白枠は付けない（フレームは core.frames で付ける）
    assert result.mode == "RGB"
    assert result.size == image.size
    # 黄みがかる（グレーの R > B）
    r, _, b = result.getpixel((175, 50))
    assert r > b


@pytest.mark.parametrize("filter_type", list(FilterType))
def test_size_is_unchanged(filter_type):
    assert apply_filter(make_sample(), filter_type).size == (200, 100)


# --- アルファ ----------------------------------------------------------------


@pytest.mark.parametrize("filter_type", list(FilterType))
def test_alpha_is_preserved(filter_type):
    image = make_sample("RGBA")
    alpha = Image.new("L", image.size, 0)
    alpha.paste(200, (0, 0, 100, 100))
    image.putalpha(alpha)

    result = apply_filter(image, filter_type)

    assert result.mode == "RGBA"
    alphas = [p[3] for p in sample_points(result, (0, 0))]
    assert alphas == [200, 200, 0, 0]


@pytest.mark.parametrize("mode", ["L", "P", "LA"])
def test_other_modes_are_normalized(mode):
    result = apply_filter(make_sample(mode), FilterType.SEPIA)
    assert result.mode in ("RGB", "RGBA")


# --- 非破壊 -------------------------------------------------------------------


@pytest.mark.parametrize("filter_type", list(FilterType))
@pytest.mark.parametrize("mode", ["RGB", "RGBA"])
def test_input_is_not_modified(filter_type, mode):
    image = make_sample(mode)
    before = (image.mode, image.size, image.tobytes())

    apply_filter(image, filter_type)

    assert (image.mode, image.size, image.tobytes()) == before


# --- 設計ルール ---------------------------------------------------------------


def test_core_filters_does_not_import_qt():
    code = (
        "import sys, image_editor.core.filters; "
        "print(any(m.startswith('PyQt6') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"


# --- ポジフィルム風・レトロカメラ風 -------------------------------------------------


def mean_saturation(image: Image.Image) -> float:
    return ImageStat.Stat(image.convert("HSV")).mean[1]


def test_positive_film_increases_saturation():
    image = make_sample()

    result = apply_filter(image, FilterType.POSITIVE_FILM)

    assert result.mode == "RGB"
    assert result.size == image.size
    assert mean_saturation(result) > mean_saturation(image) * 1.1


def test_positive_film_s_curve():
    # 暗いところはより暗く、明るいところはより明るくなる（緑は色味補正の影響を受けない）
    dark = apply_filter(Image.new("RGB", (4, 4), (64, 64, 64)), FilterType.POSITIVE_FILM)
    bright = apply_filter(Image.new("RGB", (4, 4), (192, 192, 192)), FilterType.POSITIVE_FILM)

    assert dark.getpixel((0, 0))[1] < 64
    assert bright.getpixel((0, 0))[1] > 192


def test_positive_film_cool_shadows_warm_highlights():
    dark = apply_filter(Image.new("RGB", (4, 4), (40, 40, 40)), FilterType.POSITIVE_FILM)
    bright = apply_filter(Image.new("RGB", (4, 4), (220, 220, 220)), FilterType.POSITIVE_FILM)

    r, _, b = dark.getpixel((0, 0))
    assert b > r  # 暗部は青寄り
    r, _, b = bright.getpixel((0, 0))
    assert r > b  # 明部は暖色寄り


def test_retro_camera_lifts_blacks_and_lowers_whites():
    black = apply_filter(Image.new("RGB", (64, 64), (0, 0, 0)), FilterType.RETRO_CAMERA)
    white = apply_filter(Image.new("RGB", (64, 64), (255, 255, 255)), FilterType.RETRO_CAMERA)

    # 粒子があるので平均で比べる
    assert min(ImageStat.Stat(black).mean) > 15
    assert max(ImageStat.Stat(white).mean) < 245


def test_retro_camera_is_warm_and_muted():
    gray = apply_filter(Image.new("RGB", (64, 64), (128, 128, 128)), FilterType.RETRO_CAMERA)
    r, _, b = ImageStat.Stat(gray).mean
    assert r > b + 10

    image = make_sample()
    assert mean_saturation(apply_filter(image, FilterType.RETRO_CAMERA)) < mean_saturation(image)


def test_retro_camera_has_grain():
    result = apply_filter(Image.new("RGB", (128, 128), (128, 128, 128)), FilterType.RETRO_CAMERA)

    stddev = ImageStat.Stat(result).stddev
    assert all(2 < s < 10 for s in stddev)
    # 粒子はモノクロ: R と G の差（暖色補正による一定の差）は画素によらず一定
    r, g, _ = result.split()
    low, high = ImageChops.subtract(r, g, offset=128).getextrema()
    assert high - low <= 2


def test_retro_camera_grain_is_deterministic():
    image = make_sample()
    first = apply_filter(image, FilterType.RETRO_CAMERA)
    second = apply_filter(image, FilterType.RETRO_CAMERA)
    assert first.tobytes() == second.tobytes()


def test_add_grain_strength():
    image = Image.new("RGB", (256, 256), (128, 128, 128))

    result = add_grain(image, 10, seed=1)

    low, high = result.getchannel("G").getextrema()
    assert 118 <= low < 128 < high <= 138
    assert add_grain(image, 0, seed=1).tobytes() == image.tobytes()


# --- ハイキー・ローキー・ドラマチック・モダン・ナチュラル -----------------------------


def tones() -> Image.Image:
    """暗・中・明の灰色と色の帯を持つ 200x40 画像。"""
    image = Image.new("RGB", (200, 40))
    for i, color in enumerate(
        [(0, 0, 0), (64, 64, 64), (128, 128, 128), (192, 192, 192), (255, 255, 255)]
    ):
        image.paste(color, (i * 20, 0, (i + 1) * 20, 40))
    for i, color in enumerate([(200, 60, 40), (40, 160, 80), (50, 70, 210), (230, 190, 60)]):
        image.paste(color, (100 + i * 25, 0, 100 + (i + 1) * 25, 40))
    return image


def level(image: Image.Image, index: int) -> int:
    """index 番目の灰色の帯（0: 黒 〜 4: 白）の G の値。"""
    return image.getpixel((index * 20 + 10, 20))[1]


def color_saturation(image: Image.Image) -> float:
    return ImageStat.Stat(image.crop((100, 0, 200, 40)).convert("HSV")).mean[1]


def luma(image: Image.Image) -> float:
    return ImageStat.Stat(image.convert("L")).mean[0]


def test_high_key_is_bright_and_soft():
    image = tones()
    result = apply_filter(image, FilterType.HIGH_KEY)

    assert luma(result) > luma(image) + 25
    assert level(result, 0) >= 15  # 黒も少し浮く
    assert level(result, 1) > 64 + 40  # 暗部を大きく持ち上げる
    assert level(result, 4) == 255
    assert color_saturation(result) < color_saturation(image)


def test_low_key_is_dark_and_keeps_highlights():
    image = tones()
    result = apply_filter(image, FilterType.LOW_KEY)

    assert luma(result) < luma(image) - 20
    assert level(result, 2) < 128 - 40  # 中間を沈める
    assert level(result, 4) == 255  # 明部は残す
    assert level(result, 0) == 0


def test_dramatic_widens_tonal_range():
    image = tones()
    result = apply_filter(image, FilterType.DRAMATIC)

    assert level(result, 1) < 64 - 20
    assert level(result, 3) > 192
    assert level(result, 4) < 255  # 全体をやや締める
    assert color_saturation(result) < color_saturation(image)


def test_modern_is_matte_and_cool():
    result = apply_filter(tones(), FilterType.MODERN)

    assert level(result, 0) >= 15  # 黒が浮く
    assert level(result, 4) <= 246  # 白を抑える
    r, _, b = result.getpixel((50, 20))  # 中間の灰色
    assert b > r


def test_natural_is_subtle():
    image = tones()
    result = apply_filter(image, FilterType.NATURAL)

    assert abs(luma(result) - luma(image)) < 6  # 明るさはほぼ同じ
    ratio = color_saturation(result) / color_saturation(image)
    assert 1.0 < ratio < 1.3  # 彩度はわずかに上がる
    r, _, b = result.getpixel((50, 20))
    assert r > b  # ほんのり暖色


@pytest.mark.parametrize(
    "filter_type",
    [
        FilterType.HIGH_KEY,
        FilterType.LOW_KEY,
        FilterType.DRAMATIC,
        FilterType.MODERN,
        FilterType.NATURAL,
    ],
)
def test_new_tastes_keep_size_and_mode(filter_type):
    image = tones()
    result = apply_filter(image, filter_type)
    assert result.size == image.size and result.mode == "RGB"


# --- シネマティック〜赤外線風 ------------------------------------------------------


def apply(filter_type: FilterType, image: Image.Image | None = None) -> Image.Image:
    return apply_filter(tones() if image is None else image, filter_type)


def gray_at(result: Image.Image, index: int) -> tuple[int, int, int]:
    """index 番目の灰色の帯（0: 黒 〜 4: 白）の色。"""
    return result.getpixel((index * 20 + 10, 20))


def test_cinematic_teal_shadows_orange_highlights():
    result = apply(FilterType.CINEMATIC)
    r, g, b = gray_at(result, 1)  # 暗い灰色
    assert b > r and g > r  # 青緑
    r, _, b = gray_at(result, 3)  # 明るい灰色
    assert r > b  # オレンジ


def test_noir_is_harder_black_and_white_than_monotone():
    noir = apply(FilterType.NOIR)
    mono = apply(FilterType.MONOTONE)
    for index in range(5):
        r, g, b = gray_at(noir, index)
        assert r == g == b
    assert gray_at(noir, 1)[0] < gray_at(mono, 1)[0] - 20  # 黒が深い
    assert gray_at(noir, 2)[0] < gray_at(mono, 2)[0]
    assert color_saturation(noir) == 0


def test_bleach_bypass_is_desaturated_contrasty_and_grainy():
    image = tones()
    result = apply(FilterType.BLEACH_BYPASS, image)
    assert color_saturation(result) < color_saturation(image) * 0.6
    assert ImageStat.Stat(result.crop((20, 0, 40, 40))).mean[1] < 64 - 10
    assert ImageStat.Stat(result.crop((60, 0, 80, 40))).mean[1] > 192 + 10
    flat = apply(FilterType.BLEACH_BYPASS, Image.new("RGB", (64, 64), (128,) * 3))
    assert ImageStat.Stat(flat).stddev[1] > 1  # 粒子
    assert apply(FilterType.BLEACH_BYPASS, image).tobytes() == result.tobytes()  # 毎回同じ


def test_pastel_is_light_and_soft():
    image = tones()
    result = apply(FilterType.PASTEL, image)
    assert gray_at(result, 0)[1] >= 60  # 黒が大きく浮く
    assert luma(result) > luma(image) + 30
    assert color_saturation(result) < color_saturation(image)


def test_cross_process_shifts_colors():
    result = apply(FilterType.CROSS_PROCESS)
    r, _, b = gray_at(result, 1)
    assert b > r  # 暗部は青紫
    r, g, b = gray_at(result, 3)
    assert r > b and g > b  # 明部は黄〜緑
    assert gray_at(result, 4)[2] < 200  # 白も青が抜けて黄色っぽい


def test_cyanotype_is_blue_monochrome():
    result = apply(FilterType.CYANOTYPE)
    assert gray_at(result, 0) == (10, 35, 80)
    assert gray_at(result, 4) == (220, 236, 248)
    for x in range(0, 200, 10):
        r, g, b = result.getpixel((x, 20))
        assert b >= g >= r  # どこも青系


def test_summer_is_bright_fresh_and_vivid():
    image = tones()
    result = apply(FilterType.SUMMER, image)
    assert luma(result) > luma(image)
    assert color_saturation(result) > color_saturation(image)
    r, _, b = gray_at(result, 2)
    assert b > r


def test_autumn_is_warm():
    image = tones()
    result = apply(FilterType.AUTUMN, image)
    r, _, b = gray_at(result, 2)
    assert r > b + 20
    assert abs(luma(result) - luma(image)) < 15  # 落ち着いた明るさ


def edge_image() -> Image.Image:
    """左半分が黒、右半分が白の 200x100 画像。"""
    image = Image.new("RGB", (200, 100), (0, 0, 0))
    image.paste((255, 255, 255), (100, 0, 200, 100))
    return image


def test_soft_focus_glows_around_highlights():
    # 800x400 ではぼかしの半径は短辺の 1.5% = 6px
    result = apply(FilterType.SOFT_FOCUS, edge_image().resize((800, 400)))
    assert result.getpixel((394, 200))[1] > 10  # 白の光が黒の側に 6px ほどにじむ
    assert result.getpixel((350, 200))[1] < 5  # 離れた黒はそのまま
    assert result.getpixel((600, 200)) == (255, 255, 255)


def test_soft_focus_radius_scales_with_image():
    small = apply(FilterType.SOFT_FOCUS, edge_image().resize((800, 400)))
    large = apply(FilterType.SOFT_FOCUS, edge_image().resize((1600, 800)))
    # 2 倍の画像では 2 倍の距離で同じくらいにじむ（縮小プレビューと原寸で見た目がそろう）
    assert abs(small.getpixel((394, 200))[1] - large.getpixel((788, 400))[1]) <= 6


def test_hdr_enhances_local_contrast_and_lifts_shadows():
    image = Image.new("RGB", (200, 100), (60, 60, 60))
    image.paste((180, 180, 180), (100, 0, 200, 100))
    result = apply(FilterType.HDR, image)
    near_dark, far_dark = result.getpixel((97, 50))[1], result.getpixel((5, 50))[1]
    assert near_dark < far_dark  # 境目の暗い側がより暗く（細部の明暗差が強まる）
    assert far_dark > 60  # 暗部は持ち上がる


def test_infrared_makes_foliage_glow_and_sky_dark():
    image = Image.new("RGB", (2, 1))
    image.putpixel((0, 0), (60, 160, 60))  # 草木
    image.putpixel((1, 0), (90, 160, 235))  # 青空
    result = apply(FilterType.INFRARED, image).convert("L")
    assert result.getpixel((0, 0)) > 170
    assert result.getpixel((1, 0)) < 110


@pytest.mark.parametrize(
    "filter_type",
    [getattr(FilterType, name) for name in (
        "CINEMATIC", "NOIR", "BLEACH_BYPASS", "PASTEL", "CROSS_PROCESS", "CYANOTYPE",
        "SUMMER", "AUTUMN", "SOFT_FOCUS", "HDR", "INFRARED",
    )],
)  # fmt: skip
def test_more_tastes_keep_size_and_mode(filter_type):
    image = tones()
    result = apply_filter(image, filter_type)
    assert result.size == image.size and result.mode == "RGB"
