#!/usr/bin/env python3
"""Create a labeled comparison of the two source images and their panorama."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[3]
LEFT_PATH = ROOT / "data/quiz2/set1/left.jpg"
RIGHT_PATH = ROOT / "data/quiz2/set1/right.jpg"
PANORAMA_PATH = ROOT / "result/quiz3/codex/panorama_75ee1c23.png"
OUTPUT_PATH = ROOT / "result/quiz3/codex/comparison.png"

CANVAS_SIZE = (2000, 2260)
BACKGROUND = "#111827"
CARD = "#1f2937"
IMAGE_BACKGROUND = "#0b1020"
TEXT = "#f9fafb"
MUTED = "#cbd5e1"
ACCENT = "#60a5fa"


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / name
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def open_image(path: Path) -> tuple[Image.Image, tuple[int, int]]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing input image: {path}")
    with Image.open(path) as source:
        original_size = source.size
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.load()
    return image, original_size


def draw_panel(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    image: Image.Image,
    role: str,
    original_size: tuple[int, int],
) -> None:
    draw = ImageDraw.Draw(canvas)
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=24, fill=CARD, outline="#334155", width=3)

    title_font = load_font(37, bold=True)
    size_font = load_font(32)
    label_y = y0 + 24
    draw.text((x0 + 30, label_y), role, font=title_font, fill=TEXT)
    dimension = f"{original_size[0]} × {original_size[1]} px"
    dimension_box = draw.textbbox((0, 0), dimension, font=size_font)
    dimension_width = dimension_box[2] - dimension_box[0]
    draw.text((x1 - 30 - dimension_width, label_y + 4), dimension, font=size_font, fill=ACCENT)

    image_box = (x0 + 24, y0 + 88, x1 - 24, y1 - 24)
    draw.rounded_rectangle(image_box, radius=14, fill=IMAGE_BACKGROUND)
    max_size = (image_box[2] - image_box[0], image_box[3] - image_box[1])
    shown = ImageOps.contain(image, max_size, method=Image.Resampling.LANCZOS)
    paste_x = image_box[0] + (max_size[0] - shown.width) // 2
    paste_y = image_box[1] + (max_size[1] - shown.height) // 2
    canvas.paste(shown, (paste_x, paste_y))


def main() -> None:
    left, left_size = open_image(LEFT_PATH)
    right, right_size = open_image(RIGHT_PATH)
    panorama, panorama_size = open_image(PANORAMA_PATH)

    canvas = Image.new("RGB", CANVAS_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    heading_font = load_font(48, bold=True)
    subtitle_font = load_font(25)
    draw.text((48, 28), "Panorama comparison", font=heading_font, fill=TEXT)
    draw.text(
        (48, 90),
        "Labels show each input file's original pixel dimensions.",
        font=subtitle_font,
        fill=MUTED,
    )

    draw_panel(canvas, (48, 142, 976, 1160), left, "Left original", left_size)
    draw_panel(canvas, (1024, 142, 1952, 1160), right, "Right original", right_size)
    draw_panel(canvas, (48, 1208, 1952, 2212), panorama, "Stitched panorama", panorama_size)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUTPUT_PATH, format="PNG", optimize=True)

    with Image.open(OUTPUT_PATH) as check:
        if check.format != "PNG":
            raise ValueError(f"Expected PNG output, got {check.format}")
        if check.size != CANVAS_SIZE:
            raise ValueError(f"Unexpected output size: {check.size}")
        check.verify()
    with Image.open(OUTPUT_PATH) as check:
        check.load()

    print(f"output={OUTPUT_PATH.relative_to(ROOT)}")
    print(f"canvas={CANVAS_SIZE[0]}x{CANVAS_SIZE[1]}")
    print(f"left={left_size[0]}x{left_size[1]}")
    print(f"right={right_size[0]}x{right_size[1]}")
    print(f"panorama={panorama_size[0]}x{panorama_size[1]}")
    print("verification=PNG readable and pixel data loaded")


if __name__ == "__main__":
    main()
