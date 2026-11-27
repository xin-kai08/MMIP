"""Run the requested Quiz 3 panorama with the existing Quiz 2 image tools."""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from unittest.mock import patch

import cv2
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from other_code import quiz2


RUN_DIR = ROOT / "result" / "quiz3" / "codex"
REPORT_PATH = RUN_DIR / "panorama-run.md"
SKILL_PATH = ROOT / ".agents" / "skills" / "panorama-workflow" / "SKILL.md"
LEFT_PATH = "data/quiz2/set1/left.jpg"
RIGHT_PATH = "data/quiz2/set1/right.jpg"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def write_report(lines: list[str]) -> None:
    REPORT_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Panorama run",
        "",
        "## 輸入與設定",
        "",
        f"- 工作根目錄：`{ROOT}`",
        f"- 輸入 1（左）：`{LEFT_PATH}`",
        f"- 輸入 2（右）：`{RIGHT_PATH}`",
        f"- 實際讀取的 Skill：`{rel(SKILL_PATH)}`",
        "- 亮度處理：依要求保留原本亮度，`match_exposure` 未呼叫。",
        "- 拼接模式：Quiz 2 `ImageTools.stitch_images`，OpenCV `Stitcher_PANORAMA`。",
        "- 存檔方式：Quiz 2 `ImageTools.save_image`，暫時將其 `RESULT_DIR` 指向 `result/quiz3/codex/`。",
        f"- OpenCV 版本：`{cv2.__version__}`",
        "",
        "## 工具與順序",
        "",
        "1. `ImageTools.register_photo(left.jpg)`",
        "2. `ImageTools.register_photo(right.jpg)`",
        "3. 跳過 `ImageTools.match_exposure`",
        "4. `ImageTools.stitch_images([left_id, right_id])`",
        "5. `ImageTools.save_image(panorama_id, \"panorama.png\")`",
        "6. Pillow `Image.open` 回讀、限制格式為 PNG、`verify()`，再重新開啟並 `load()` 驗證像素與尺寸。",
        "",
        "## 實際結果",
        "",
        "- 前置啟動重試：首次隔離執行尚未進入拼接即失敗，實際錯誤為 `ModuleNotFoundError: No module named 'other_code'`；將工作根目錄加入 `sys.path` 後重跑。",
    ]

    try:
        if not SKILL_PATH.is_file():
            raise FileNotFoundError(f"找不到 Skill：{SKILL_PATH}")
        # Force an actual UTF-8 read of the selected Skill used by this run.
        SKILL_PATH.read_text(encoding="utf-8")

        tools = quiz2.ImageTools(stitch_cache=False)
        left = tools.register_photo(LEFT_PATH)
        right = tools.register_photo(RIGHT_PATH)
        ordered_ids = [left["image_id"], right["image_id"]]
        lines.extend([
            f"- 左圖 ID：`{left['image_id']}`",
            f"- 右圖 ID：`{right['image_id']}`",
            f"- 傳入拼接的順序：`{json.dumps(ordered_ids, ensure_ascii=False)}`",
        ])

        stitched = tools.stitch_images(ordered_ids)
        lines.extend([
            f"- `stitch_images` 回傳：`{json.dumps(stitched, ensure_ascii=False, sort_keys=True)}`",
            f"- OpenCV 是否實際執行：`{stitched.get('opencv_executed')}`",
            f"- OpenCV 回傳狀態：`{stitched.get('opencv_status', '未回傳')}`",
        ])
        if not stitched.get("ok"):
            raise RuntimeError(stitched.get("error", "拼接失敗，但工具未提供錯誤訊息"))

        with patch.object(quiz2, "RESULT_DIR", RUN_DIR):
            saved = tools.save_image(stitched["image_id"], "panorama.png")
        output_path = ROOT / saved["path"]

        with Image.open(output_path, formats=["PNG"]) as image:
            detected_format = image.format
            image.verify()
        with Image.open(output_path, formats=["PNG"]) as image:
            image.load()
            verified_size = image.size
            verified_mode = image.mode

        lines.extend([
            f"- `save_image` 回傳：`{json.dumps(saved, ensure_ascii=False, sort_keys=True)}`",
            f"- 輸出路徑：`{saved['path']}`",
            f"- 工具回傳尺寸：`{saved['width']} × {saved['height']}`",
            f"- PNG 回讀驗證：成功（格式 `{detected_format}`、模式 `{verified_mode}`）",
            f"- PNG 回讀尺寸：`{verified_size[0]} × {verified_size[1]}`",
            "- 執行狀態：成功。",
        ])
        write_report(lines)
        print(json.dumps({"ok": True, "output": saved["path"], "size": verified_size,
                          "report": rel(REPORT_PATH), "stitch": stitched},
                         ensure_ascii=False, default=list))
        return 0
    except Exception as exc:
        lines.extend([
            "- 執行狀態：失敗。",
            f"- 實際錯誤：`{type(exc).__name__}: {exc}`",
            "",
            "```text",
            traceback.format_exc().rstrip(),
            "```",
        ])
        write_report(lines)
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}",
                          "report": rel(REPORT_PATH)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
