import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

from image_editor.core import effects
from image_editor.core.pipeline import (
    EditSettings,
    apply_edits,
    make_preview,
    render_preview,
)
from image_editor.core.presets import PRESET_FIELDS, Preset, apply_preset
from image_editor.core.transform import CropRect


def make_detail_image(size=(400, 300)) -> Image.Image:
    """縞模様と円のある画像（輪郭の変化が分かる）。"""
    image = Image.new("RGB", size, (128, 128, 128))
    draw = ImageDraw.Draw(image)
    step = max(4, size[0] // 40)
    for x in range(0, size[0], step * 2):
        draw.rectangle((x, 0, x + step - 1, size[1] // 2), fill=(30, 30, 30))
    draw.ellipse((size[0] // 4, size[1] // 2, size[0] // 2, size[1] - 1), fill=(230, 200, 40))
    return image


def make_noisy_image(size=(300, 200)) -> Image.Image:
    noise = Image.effect_noise(size, 15)
    return Image.merge("RGB", (noise, noise, noise))


def mean_diff(a: Image.Image, b: Image.Image) -> float:
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3


def edge_strength(image: Image.Image) -> float:
    """隣の画素との差の二乗平均（くっきりしているほど大きい）。

    差の平均は、境目がぼけても合計が変わらない（全変動）ので、二乗平均で比べる。
    """
    gray = image.convert("L")
    shifted = ImageChops.offset(gray, 1, 0)
    return ImageStat.Stat(ImageChops.difference(gray, shifted)).rms[0]


@pytest.mark.parametrize("function", [effects.sharpen, effects.blur, effects.denoise])
def test_zero_is_unchanged(function):
    image = make_detail_image()
    result = function(image, 0)
    assert result is not image
    assert result.tobytes() == image.tobytes()


@pytest.mark.parametrize("function", [effects.sharpen, effects.blur, effects.denoise])
@pytest.mark.parametrize("amount", [-1, 101])
def test_amount_out_of_range(function, amount):
    with pytest.raises(ValueError):
        function(make_detail_image(), amount)


def test_sharpen_increases_edges():
    image = make_detail_image().filter(ImageFilter.GaussianBlur(1))
    assert edge_strength(effects.sharpen(image, 100)) > edge_strength(image) * 1.2
    assert edge_strength(effects.sharpen(image, 50)) < edge_strength(effects.sharpen(image, 100))


def test_blur_decreases_edges():
    image = make_detail_image()
    assert edge_strength(effects.blur(image, 30)) < edge_strength(image) * 0.8
    assert edge_strength(effects.blur(image, 100)) < edge_strength(effects.blur(image, 30))


def test_denoise_smooths_noise_but_keeps_edges():
    noisy = make_noisy_image()
    assert ImageStat.Stat(effects.denoise(noisy, 100).convert("L")).stddev[0] < (
        ImageStat.Stat(noisy.convert("L")).stddev[0] * 0.8
    )
    # はっきりした輪郭（白黒の境目）はほぼそのまま残る
    edge = Image.new("RGB", (200, 100), (0, 0, 0))
    edge.paste((255, 255, 255), (100, 0, 200, 100))
    result = effects.denoise(edge, 100)
    assert result.getpixel((98, 50)) == (0, 0, 0)
    assert result.getpixel((101, 50)) == (255, 255, 255)


@pytest.mark.parametrize("function", [effects.sharpen, effects.blur, effects.denoise])
def test_alpha_is_preserved(function):
    image = make_detail_image().convert("RGBA")
    image.putalpha(123)
    result = function(image, 60)
    assert result.mode == "RGBA"
    assert result.getchannel("A").getextrema() == (123, 123)


@pytest.mark.parametrize("function", [effects.sharpen, effects.blur, effects.denoise])
def test_input_is_not_modified(function):
    image = make_detail_image()
    before = image.tobytes()
    function(image, 80)
    assert image.tobytes() == before


def test_reference_scales_radius():
    # 基準の長さを 2 倍にすると、2 倍の大きさの画像と同じ半径でぼける
    image = make_detail_image()
    small = effects.blur(image, 50, reference=300)
    large = effects.blur(image, 50, reference=600)
    assert edge_strength(large) < edge_strength(small)


# --- プレビューと保存結果の効き方 -------------------------------------------------


@pytest.mark.parametrize("settings", [EditSettings(sharpen=80), EditSettings(blur=40)])
@pytest.mark.parametrize("crop", [None, CropRect(200, 150, 1600, 1200)])
@pytest.mark.parametrize("width", [None, 800])
def test_preview_matches_saved_result(settings, crop, width):
    # 原寸で処理して縮小したものと、縮小したプレビューで処理したものの変化量がほぼ同じ
    # （ノイズは縮小するだけで薄れるので、ノイズ除去は原寸とプレビューで効き方が元々そろわない）
    original = make_detail_image((4000, 3000))
    settings = EditSettings(
        crop=crop,
        width=width,
        sharpen=settings.sharpen,
        blur=settings.blur,
        denoise=settings.denoise,
    )
    plain = EditSettings(crop=crop, width=width)
    preview, factor = make_preview(original)

    saved = apply_edits(original, settings)
    saved_plain = apply_edits(original, plain)
    size = render_preview(preview, settings, factor, trimmed=True).size
    saved_change = mean_diff(saved.resize(size), saved_plain.resize(size))

    preview_result = render_preview(preview, settings, factor, trimmed=True)
    preview_plain = render_preview(preview, plain, factor, trimmed=True)
    preview_change = mean_diff(preview_result, preview_plain)

    assert saved_change > 0.3
    assert preview_change == pytest.approx(saved_change, rel=0.5)


def test_whole_view_uses_crop_short_side():
    # 全体表示でも、ぼかしの半径は切り抜く範囲の短辺を基準にする（保存結果と同じ見え方）
    original = make_detail_image((4000, 3000))
    preview, factor = make_preview(original)
    crop = CropRect(0, 0, 1000, 1000)
    whole = render_preview(preview, EditSettings(crop=crop, blur=50), factor)
    trimmed = render_preview(preview, EditSettings(crop=crop, blur=50), factor, trimmed=True)
    box = (40, 40, 360, 360)  # 範囲の内側（縮小率 0.4 で 400x400）
    assert mean_diff(whole.crop(box), trimmed.crop(box)) < 1.0


# --- 設定・プリセット ---------------------------------------------------------------


def test_detail_in_settings_and_presets():
    assert (EditSettings().sharpen, EditSettings().blur, EditSettings().denoise) == (0, 0, 0)
    for key in ("sharpen", "blur", "denoise"):
        assert key in PRESET_FIELDS
    applied = apply_preset(EditSettings(), Preset(name="x", sharpen=20, blur=5, denoise=30))
    assert (applied.sharpen, applied.blur, applied.denoise) == (20, 5, 30)


def test_apply_edits_order_and_output_size():
    image = make_detail_image()
    settings = EditSettings(width=200, sharpen=50, blur=10, denoise=20)
    assert apply_edits(image, settings).size == (200, 150)
