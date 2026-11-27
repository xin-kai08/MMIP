"""Execute model-authored Pillow-only comparison scripts in a bounded child."""
from __future__ import annotations

import ast
import json
import re
import resource
import sys
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageFont

NODES = {
    "Module", "ImportFrom", "alias", "Assign", "AugAssign", "Expr", "Call", "keyword",
    "Name", "Load", "Store", "Attribute", "Constant", "List", "Tuple", "Dict",
    "Subscript", "Slice", "BinOp", "UnaryOp", "Add", "Sub", "Mult", "Div", "FloorDiv",
    "Mod", "USub", "UAdd", "JoinedStr", "FormattedValue", "For", "If", "IfExp",
    "Compare", "Eq", "NotEq", "Lt", "LtE", "Gt", "GtE", "And", "Or", "Not", "BoolOp",
    "ListComp", "DictComp", "GeneratorExp", "comprehension", "Starred", "With", "withitem",
}
ATTRS = {
    "open", "new", "size", "width", "height", "resize", "thumbnail", "paste", "convert",
    "copy", "save", "close", "append", "Draw", "text", "rectangle", "textbbox",
    "load_default", "Resampling", "LANCZOS", "BICUBIC", "BILINEAR",
}
LIBRARIES = {"Image", "ImageDraw", "ImageFont"}
BUILTINS = {
    item.__name__: item for item in (
        abs, enumerate, float, int, len, list, max, min, print, range, round, str, sum, tuple, zip,
    )
}


def validate_source(code):
    if len(code) > 9000:
        raise ValueError("生成腳本超過 9000 字")
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if type(node).__name__ not in NODES:
            raise ValueError(f"腳本語法未開放：{type(node).__name__}")
        if isinstance(node, ast.ImportFrom) and (
            node.module != "PIL" or node.level
            or any(item.name not in LIBRARIES or item.asname for item in node.names)
        ):
            raise ValueError("只允許 from PIL import Image, ImageDraw, ImageFont")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError("禁止使用私有名稱")
        if isinstance(node, ast.Attribute) and node.attr not in ATTRS:
            raise ValueError(f"Pillow 操作未開放：{node.attr}")
    return tree


def render(script, manifest):
    source = script.read_text(encoding="utf-8")
    tree = validate_source(source)
    allowed = {Path(item["path"]).resolve() for item in manifest["inputs"]}
    output = Path(manifest["output"]).resolve()
    opened, captions, saved_canvases, placements = set(), [], [], []
    origins = {}
    keep_alive = []
    original_save = Image.Image.save
    original_text = ImageDraw.ImageDraw.text
    original_paste = Image.Image.paste
    transforms = {name: getattr(Image.Image, name) for name in ("copy", "resize", "convert")}

    def remember(image, path):
        origins[id(image)] = path
        keep_alive.append(image)
        return image

    def open_input(filename):
        path = Path(filename).resolve()
        if path not in allowed:
            raise ValueError(f"圖片不在本輪准許清單：{filename}")
        opened.add(path)
        with Image.open(path) as image:
            return remember(image.convert("RGB"), path)

    def new_image(mode, size, color=0):
        if mode not in {"RGB", "RGBA"} or len(size) != 2 or not all(1 <= v <= 4096 for v in size):
            raise ValueError("畫布限 RGB/RGBA 且最長邊 4096 像素")
        return Image.new(mode, size, color)

    def save_png(image, filename, format=None, **options):
        if Path(filename).resolve() != output or format not in (None, "PNG") or options:
            raise ValueError(f"只可寫入指定 PNG：{manifest['output']}")
        original_save(image, output, format="PNG")
        saved_canvases.append(id(image))

    def draw_text(draw, xy, text, *args, **kwargs):
        original_text(draw, xy, text, *args, **kwargs)
        font = kwargs.get("font", args[1] if len(args) > 1 else None)
        bounds = draw.textbbox(xy, text, font=font)
        captions.append({"text": str(text), "xy": list(xy), "bounds": bounds, "canvas": id(draw._image)})

    def track_transform(transform):
        def apply(image, *args, **kwargs):
            transformed = transform(image, *args, **kwargs)
            return remember(transformed, origins[id(image)]) if id(image) in origins else transformed
        return apply

    def paste_photo(canvas, image, box=None, mask=None):
        original_paste(canvas, image, box, mask)
        if id(image) in origins:
            x, y = (0, 0) if box is None else box[:2]
            placements.append({"canvas": id(canvas), "source": origins[id(image)],
                               "bounds": (x, y, x + image.width, y + image.height)})

    facade = SimpleNamespace(
        Image=SimpleNamespace(open=open_input, new=new_image, Resampling=Image.Resampling,
                              LANCZOS=Image.Resampling.LANCZOS),
        ImageDraw=SimpleNamespace(Draw=ImageDraw.Draw),
        ImageFont=SimpleNamespace(load_default=ImageFont.load_default),
    )

    def import_pillow(name, globals=None, locals=None, fromlist=(), level=0):
        if name != "PIL" or level or not fromlist or not set(fromlist) <= LIBRARIES:
            raise ImportError("只允許指定的 Pillow 模組")
        return facade

    Image.Image.save = save_png
    Image.Image.paste = paste_photo
    ImageDraw.ImageDraw.text = draw_text
    for name, transform in transforms.items():
        setattr(Image.Image, name, track_transform(transform))
    try:
        exec(compile(tree, str(script), "exec"), {"__builtins__": {
            **BUILTINS, "__import__": import_pillow,
        }})
    finally:
        Image.Image.save = original_save
        Image.Image.paste = original_paste
        ImageDraw.ImageDraw.text = original_text
        for name, transform in transforms.items():
            setattr(Image.Image, name, transform)
    if opened != allowed:
        raise ValueError("腳本未讀取全部三張資料")
    with Image.open(output, formats=["PNG"]) as image:
        image.load()
        size = list(image.size)
    observed = []
    panels = []
    def visible(bounds):
        x0, y0, x1, y1 = bounds
        return 0 <= x0 < x1 <= size[0] and 0 <= y0 < y1 <= size[1]

    def overlaps(a, b):
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

    label_bounds = []
    for item in manifest["inputs"]:
        width, height = item["size"]
        panel = next((entry["bounds"] for entry in placements
                      if entry["source"] == Path(item["path"]).resolve()
                      and saved_canvases and entry["canvas"] == saved_canvases[-1]), None)
        if panel is None:
            raise ValueError(f"比較圖畫布缺少 {item['role']} 影像")
        if not visible(panel):
            raise ValueError(f"{item['role']} paste bounds {panel} exceed canvas {tuple(size)}; "
                             "calculate canvas from the sum along the layout axis")
        x0, y0, x1, y1 = panel
        if abs((x1 - x0) * height - (y1 - y0) * width) > 2 * max(width, height):
            raise ValueError(f"{item['role']} 的縮圖長寬比不符原始影像")
        if any(overlaps(panel, other) for other in panels):
            raise ValueError("三張圖的排版有重疊")
        panels.append(panel)
        pattern = rf"\b{width}\s*[x×*]\s*{height}\b"
        found = next((entry for entry in captions
                      if item["role"].lower() in entry["text"].lower()
                      and re.search(pattern, entry["text"], re.IGNORECASE)
                      and saved_canvases and entry["canvas"] == saved_canvases[-1]
                      and visible(entry["bounds"])), None)
        if found is None:
            raise ValueError(f"缺少可核對的原始尺寸標籤：{item['role']} {width} x {height}")
        observed.append({"role": item["role"], "label": found["text"],
                         "xy": found["xy"], "panel": list(panel)})
        label_bounds.append(found["bounds"])
    if any(overlaps(label, panel) for label in label_bounds for panel in panels):
        raise ValueError("Caption overlaps a photo; reserve a blank band and move the image below the text")
    if any(overlaps(a, b) for index, a in enumerate(label_bounds) for b in label_bounds[index + 1:]):
        raise ValueError("Caption labels overlap each other")
    return {"path": manifest["output"], "size": size, "format": "PNG", "labels": observed}


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024**2, 32 * 1024**2))
    print(json.dumps(render(Path(sys.argv[1]), json.loads(sys.argv[2])), ensure_ascii=False))
