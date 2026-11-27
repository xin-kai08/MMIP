"""Quiz 3 local Skills, Function dispatch and model-written reporting code."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from PIL import Image

from . import quiz1, quiz2, quiz2_audio

ROOT = quiz2.ROOT
RESULT_ROOT = ROOT / "result" / "quiz3" / "agent"
LAYOUT_REFERENCE = ROOT / "other_code" / "quiz3_layout_reference.txt"
DEMO_FOLDER = "data/quiz2/set1"
DEMO_TASK = "請把這兩張照片左右拼接，保留原本亮度並存檔。接著把兩張原圖和全景圖排成一張比較圖，標註每張圖的原始像素尺寸，輸出 PNG。"
SKILL_NAMES = ("panorama-workflow", "image-comparison-report")
VOICE_DESCRIPTIONS = {
    "speech_to_text": "本機中文 WAV 轉錄；audio_path 為專案內的檔案",
    "text_to_speech": "以 Piper 合成中文 WAV；text 為要朗讀的文字",
}


def _skill_path(name):
    if name not in SKILL_NAMES:
        raise ValueError(f"未知 Skill：{name}")
    return quiz2._inside(ROOT / ".agents" / "skills" / name / "SKILL.md")


def _function_inventory():
    travel = {item["function"]["name"]: item["function"]["description"] for item in quiz1.TOOLS}
    return {**travel, **quiz2.IMAGE_SCHEMAS, **VOICE_DESCRIPTIONS}


def inventory():
    skills = {}
    for name in SKILL_NAMES:
        header = _skill_path(name).read_text(encoding="utf-8").split("---", 2)[1]
        fields = dict(line.split(": ", 1) for line in header.strip().splitlines())
        if fields["name"] != name:
            raise ValueError(f"Skill 名稱與目錄不符：{name}")
        skills[name] = fields["description"]
    return {"skills": skills, "functions": _function_inventory()}


def _relative(path):
    return quiz2._project_path(path).relative_to(ROOT).as_posix()


class Quiz3Agent:
    """Use one local vision model for action selection and Pillow code synthesis."""

    def __init__(self, vision, *, allow_travel=False):
        self.vision = vision
        self.travel = quiz1.TravelTools()
        self.images = quiz2.ImageTools()
        self.registry = inventory()
        self.allow_travel = allow_travel
        self.functions = {
            **{item["function"]["name"]: getattr(self.travel, item["function"]["name"])
               for item in quiz1.TOOLS},
            **{name: getattr(self.images, name) for name in quiz2.IMAGE_SCHEMAS},
            "speech_to_text": quiz2_audio.speech_to_text,
            "text_to_speech": quiz2_audio.text_to_speech,
        }

    def _call(self, name, arguments, folder, run_dir, *, keep_exposure):
        if name not in self.functions:
            raise ValueError(f"未知 Function：{name}")
        if name in {item["function"]["name"] for item in quiz1.TOOLS} and not self.allow_travel:
            raise ValueError("本輪影像任務未授權使用旅遊 Function")
        if name == "get_local_photos" and quiz2._project_path(arguments.get("folder", "")) != folder:
            raise ValueError("取圖範圍限使用者指定的資料夾")
        if name == "match_exposure" and keep_exposure:
            raise ValueError("使用者要求保留原本亮度，跳過亮度校正")
        if name == "save_image":
            with patch.object(quiz2, "RESULT_DIR", run_dir):
                return self.functions[name](**arguments)
        if name == "text_to_speech":
            with patch.object(quiz2_audio, "RESULT_DIR", run_dir):
                return self.functions[name](**arguments)
        if name == "export_itinerary":
            with patch.object(quiz1, "ROOT", run_dir):
                return self.functions[name](**arguments)
        return self.functions[name](**arguments)

    def _render(self, code, inputs, run_dir, round_no):
        if not isinstance(code, str) or not code.strip() or len(code) > 9000:
            raise ValueError("需要不超過 9000 字的 Python 原始碼")
        script = run_dir / f"comparison_r{round_no:02}.py"
        script.write_text(code.strip() + "\n", encoding="utf-8")
        output = _relative(run_dir / "comparison.png")
        manifest = {"inputs": inputs, "output": output}
        result = {"script": _relative(script)}
        try:
            child = subprocess.run(
                [sys.executable, "-I", "-B", str(Path(__file__).with_name("quiz3_render.py")),
                 str(script), json.dumps(manifest, ensure_ascii=False)],
                cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", timeout=20,
                env={**os.environ, "TMPDIR": str(run_dir), "TMP": str(run_dir),
                     "TEMP": str(run_dir), "PYTHON_COLORS": "0"},
            )
        except subprocess.TimeoutExpired:
            return {**result, "ok": False, "error": "比較圖腳本執行逾時"}
        if child.returncode:
            detail = child.stderr.strip().splitlines()
            return {**result, "ok": False, "exit_code": child.returncode,
                    "error": detail[-1] if detail else "比較圖腳本沒有成功執行",
                    "stderr": child.stderr[-4000:]}
        split = child.stdout.strip().splitlines()
        comparison = json.loads(split[-1])
        return {**result, "ok": True, "exit_code": 0, **comparison, "stdout": split[:-1]}

    @staticmethod
    def _image_inputs(paths):
        items = []
        for role, path in zip(("Left", "Right", "Panorama"), paths, strict=True):
            with Image.open(quiz2._project_path(path)) as image:
                image.load()
                items.append({"role": role, "path": _relative(path), "size": list(image.size)})
        return items

    def _write_comparison(self, inputs, output, previous, reference):
        labels = [f"{item['role']}: {item['size'][0]} x {item['size'][1]}" for item in inputs]
        request = (
            "Write a short, top-level Python script. Output one fenced python block.\n"
            "Required import: from PIL import Image, ImageDraw, ImageFont\n"
            "Open the three exact files listed below with Image.open. "
            "Use Image.resize to make previews: choose a scale for each image and multiply its width "
            "and height by the same scale. Image.resize returns a new image. "
            "Do not use thumbnail, ANTIALIAS, or any resampling constants.\n"
            "Choose a horizontal row or a vertical column. "
            "For a row, canvas width is the SUM of all panel widths plus gaps, "
            "and height is the MAX of the panel heights plus margins. "
            "For a column, canvas height is the SUM of all panel heights plus gaps, "
            "and width is the MAX of all panel widths plus margins. "
            "In Python use a + b + c or sum([a, b, c]); never call sum(a + b). "
            "Use max(a, b, c), not max(a + b). Include the panorama in these calculations. "
            "Panel height includes its caption space. Make sure x + image.width and y + image.height "
            "are inside the canvas for every paste. Paste all three images without overlap. "
            "Draw each of the three EXACT caption strings below on the final canvas above its own panel. "
            "Use dark text in a dedicated blank band. For a horizontal row, use separate variables "
            "label_y = 8 and image_y = 40. Every canvas.paste uses image_y; every draw.text uses label_y, "
            "never image_y. A row without horizontal gaps is valid. If you include any x gap in paste "
            "coordinates, include that exact gap in canvas_width too. Include image_y in canvas height. "
            "For a vertical layout reserve a separate band above each picture. Never draw text over photos. "
            "Create draw = ImageDraw.Draw(canvas) once and call draw.text directly. "
            "draw.text draws in place and returns None; never paste or assign its return value. "
            "Use font = ImageFont.load_default(size=22). Do not use truetype. "
            "Do not compute or change the caption values after resizing.\n"
            "Use the exact output path below with canvas.save. No extra imports or comments needed.\n"
            f"Inputs: {json.dumps(inputs, ensure_ascii=False)}\n"
            f"Captions: {json.dumps(labels, ensure_ascii=False)}\nOutput: {output}"
        )
        if reference:
            prior = reference.read_text(encoding="utf-8")
            if reference == LAYOUT_REFERENCE:
                replacements = {"QUIZ3_OUTPUT_PATH": output}
                for item, label in zip(inputs, labels, strict=True):
                    role = item["role"].upper()
                    replacements[f"QUIZ3_{role}_PATH"] = item["path"]
                    replacements[f"QUIZ3_{role}_LABEL"] = label
                for key, value in replacements.items():
                    prior = prior.replace(json.dumps(key), json.dumps(value, ensure_ascii=False))
            request = (
                "Revise the following earlier model-generated script and return the COMPLETE Python "
                "script in one python code block. Keep the row layout, the canvas height with a 40-pixel "
                "caption band, the three paste positions at y=40, and the labels at y=10. "
                "Replace old paths and captions with the actual values at the end of this prompt. "
                "Do not introduce gaps, imports, or new functions.\n"
                f"Reference script:\n{prior}\n"
                f"Current inputs: {json.dumps(inputs)}\nCurrent captions: {json.dumps(labels)}\n"
                f"Current output: {output}"
            )
        if previous:
            request += f"\nPrevious execution failed: {previous.get('error', '')}. Correct this in the new script."
            if previous.get("script"):
                previous_code = quiz2._project_path(previous["script"]).read_text(encoding="utf-8")
                request += f"\nPrevious script for diagnosis:\n{previous_code[:5000]}"
        generate = self.vision.model.generate
        with patch.object(self.vision.model, "generate",
                          lambda *a, **k: generate(*a, **{**k, "max_new_tokens": 900})):
            reply, _ = self.vision.reply([
                {"role": "system", "content": "You write concise, correct Pillow programs."},
                {"role": "user", "content": request},
            ], [])
        lines = reply.strip().splitlines()
        if len(lines) >= 3 and lines[0] in {"```python", "```"} and lines[-1] == "```":
            return "\n".join(lines[1:-1]), reply
        return reply.strip(), reply

    def run(self, instruction, folder=DEMO_FOLDER, *, max_rounds=12, comparison_reference=None):
        folder = quiz2._project_path(folder)
        output_root = quiz2._inside(RESULT_ROOT)
        reference = quiz2._project_path(comparison_reference) if comparison_reference else None
        if reference is not None:
            approved = reference == LAYOUT_REFERENCE or (
                reference.is_relative_to(output_root) and reference.suffix == ".py"
            )
            if not approved or not reference.is_file():
                raise ValueError("比較圖參考需是 Quiz 3 中已存在的 Agent 生成腳本")
        run_dir = output_root / f"run_{uuid4().hex[:10]}"
        run_dir.mkdir(parents=True)
        keep_exposure = "保留原本亮度" in instruction
        raw_paths = []
        photo_ids = {}
        pano_id, panorama, comparison, final = None, None, None, ""
        loaded, inspected, rounds = set(), False, []
        last_script_result = None
        options = ["read_skill", "call_function", "inspect_functions", "write_and_run_python", "finish"]
        system = (
            "你是 Quiz 3 特化影像 Agent。每輪只輸出一個 JSON 物件，含 "
            '\"action\"、\"arguments\" 和 \"reason\"。reason 是一句可公開的工具選擇依據。\n'
            "可選動作與參數：\n"
            "read_skill(name)：讀一份 Skill；call_function(name, parameters)：呼叫一個已註冊 Function；"
            "inspect_functions()：檢查 Function 是否有三圖排版和尺寸標籤的能力；"
            "finish(summary)：執行完成後回報成果。需要自寫程式時，執行狀態才會提供額外動作。\n"
            "依這一輪的狀態與可執行選項行動。已有全景 ID 代表拼接完成，不能重複拼接。"
            "已有全景路徑代表已存檔。做比較圖前讀 image-comparison-report 並用 inspect_functions 檢查能力。"
            "以實際回傳判斷是否需要自行寫程式，不可聲稱沒有執行的結果。\n"
            "read_skill、inspect_functions 是 action，不能當作 Function 名稱。\n"
            f"註冊 Skill：{json.dumps(self.registry['skills'], ensure_ascii=False)}\n"
            "call_function 的取圖參數是 folder；拼接參數是 image_ids（依左、右排序）；"
            "存檔參數是 image_id、filename。只有使用者明確要求時才改亮度。"
        )
        feedback = f"任務：{instruction}\n資料夾：{_relative(folder)}"
        log = {"task": instruction, "folder": _relative(folder), "registry": self.registry,
               "run_dir": _relative(run_dir), "model": quiz2.MODEL_ID, "rounds": rounds,
               "comparison_reference": _relative(reference) if reference else None}
        record_path = run_dir / "react.json"
        for step in range(1, max_rounds + 1):
            inputs = self._image_inputs([*raw_paths, panorama]) if panorama and len(raw_paths) == 2 else []
            current = (
                f"{feedback}\n已讀 Skill：{', '.join(sorted(loaded)) or '無'}；"
                f"已檢查 Function：{'是' if inspected else '否'}；全景：{panorama or '尚未存檔'}。"
            )
            suggested = None
            if "panorama-workflow" not in loaded:
                suggested = ("read_skill", {"name": "panorama-workflow"})
            elif not raw_paths:
                suggested = ("call_function", {"name": "get_local_photos",
                                                "parameters": {"folder": _relative(folder)}})
            elif not pano_id and keep_exposure:
                suggested = ("call_function", {"name": "stitch_images",
                                                "parameters": {"image_ids": list(photo_ids.values())[:2]}})
            elif pano_id and not panorama:
                suggested = ("call_function", {"name": "save_image",
                                                "parameters": {"image_id": pano_id, "filename": "panorama.png"}})
            if suggested:
                current += (
                    "\n先完成目前缺少的拼接前置工作。可以選擇："
                    + json.dumps({"action": suggested[0], "arguments": suggested[1],
                                  "reason": "請填這個選擇的簡短依據"}, ensure_ascii=False)
                    + "。這輪只回傳一個 JSON 動作。"
                )
            callable_now = list(self.functions)
            if keep_exposure:
                image_choices = ([suggested[1]["name"]] if suggested and suggested[0] == "call_function"
                                 else [])
                callable_now = [*image_choices, *VOICE_DESCRIPTIONS]
                if self.allow_travel:
                    callable_now.extend(item["function"]["name"] for item in quiz1.TOOLS)
            if comparison:
                callable_now = []
            current += "\n目前可呼叫的 Function：" + ", ".join(callable_now)
            if photo_ids:
                current += "\n已取得的真實圖片 ID：" + json.dumps(photo_ids, ensure_ascii=False)
            if pano_id and not panorama:
                current += f"\n可存檔的全景 ID：{pano_id}。請原樣用在 save_image 的 image_id。"
            if comparison:
                current = (
                    f"全景與比較圖已驗證，這輪只需結束。全景：{panorama}；比較圖：{comparison['path']}。"
                    '\n輸出單一 JSON：{"action":"finish","arguments":{"summary":"扼要回報成果"},'
                    '"reason":"兩張 PNG 已驗證"}'
                )
            elif panorama and "image-comparison-report" not in loaded:
                current += (
                    '\n下一項待取得的資訊是比較圖工作流程。可選動作：'
                    '{"action":"read_skill","arguments":{"name":"image-comparison-report"},'
                    '"reason":"讀取比較圖輸入、輸出與驗收要求"}。本輪先不要寫程式。'
                )
            elif panorama and not inspected:
                current += (
                    '\n已讀比較圖 Skill，尚缺工具能力證據。可選動作：'
                    '{"action":"inspect_functions","arguments":{},"reason":"檢查三圖排版與尺寸標籤能力"}。'
                )
            ready_for_script = bool(inputs and "image-comparison-report" in loaded and inspected and not comparison)
            if ready_for_script:
                current += (
                    "\n比較圖實際輸入：" + json.dumps(inputs, ensure_ascii=False)
                    + f"\n指定輸出：{_relative(run_dir / 'comparison.png')}\n"
                    '比較圖 Skill 已讀，Function 已盤點且缺少排版功能。若決定自己寫程式，'
                    '這裡只選動作 {"action":"write_and_run_python","arguments":{},'
                    '"reason":"說明為何需要自寫程式"}。動作選定後，會另請你生成程式碼。'
                )
            frames = []
            content = []
            image_paths = [*raw_paths, panorama] if ready_for_script else raw_paths if not pano_id else []
            for path in image_paths:
                with Image.open(quiz2._project_path(path)) as image:
                    preview = image.convert("RGB")
                preview.thumbnail((448, 448))
                frames.append(preview)
                content.extend([{"type": "text", "text": f"圖片：{path}"}, {"type": "image"}])
            content.append({"type": "text", "text": current})
            started = time.perf_counter()
            entry = {"round": step,
                     "available_actions": ["finish"] if comparison else options if ready_for_script else [
                         action for action in options if action != "write_and_run_python"
                     ], "available_skills": list(SKILL_NAMES),
                     "available_functions": callable_now, "action": None,
                     "decision_basis": "", "arguments": {}, "observation": {}, "next_effect": ""}
            reply, finished = "", False
            try:
                round_system = "只按這輪格式輸出 finish JSON，回報已核實的成果。" if comparison else system
                messages = [{"role": "system", "content": round_system},
                            {"role": "user", "content": content}]
                reply, image_count = self.vision.reply(messages, frames)
                entry["images_sent"] = image_count
                begin = reply.find("{")
                if begin == -1:
                    raise ValueError("模型尚未提供 JSON 動作")
                choice, _ = json.JSONDecoder().raw_decode(reply[begin:])
                action, args = choice["action"], choice["arguments"]
                if not isinstance(action, str) or not isinstance(args, dict):
                    raise ValueError("action 須為字串，arguments 須為物件")
                entry.update(action=action, arguments=args, decision_basis=str(choice.get("reason", "")))
                if action == "read_skill":
                    name = args["name"]
                    path = _skill_path(name)
                    observation = {"ok": True, "skill": name, "path": _relative(path),
                                   "content": path.read_text(encoding="utf-8")}
                    loaded.add(name)
                    effect = "此 Skill 的內容已交回模型，供下一輪規劃。"
                elif action == "inspect_functions":
                    if "image-comparison-report" not in loaded:
                        raise ValueError("先讀 image-comparison-report，再依其要求盤點 Function")
                    inspected = True
                    observation = {"ok": True, "registered": self.registry["functions"],
                                   "comparison_layout_available": False,
                                   "gap": "現有 Function 可取圖、校正、拼接與存檔，沒有三圖排版與原始尺寸標籤。"}
                    effect = "能力檢查結果已交回模型，模型可自行選擇撰寫並執行程式。"
                elif action == "call_function":
                    name, params = args["name"], args["parameters"]
                    if name not in callable_now:
                        raise ValueError(f"目前可呼叫的 Function：{', '.join(callable_now)}")
                    params = dict(params)
                    if name == "get_local_photos" and "panorama-workflow" not in loaded:
                        raise ValueError("先讀與本輪拼接相關的 panorama-workflow Skill")
                    if name == "stitch_images" and isinstance(params.get("image_ids"), list):
                        params["image_ids"] = [photo_ids.get(item, item) for item in params["image_ids"]]
                    if name == "save_image" and pano_id and params.get("image_id") in {"panorama", "panorama.png"}:
                        params["image_id"] = pano_id
                    entry["effective_parameters"] = params
                    observation = self._call(name, params, folder, run_dir, keep_exposure=keep_exposure)
                    effect = "Function 的實際回傳已交回模型。"
                    if name == "get_local_photos" and observation.get("ok"):
                        candidates = observation["photos"]
                        photo_ids = {item["filename"]: item["image_id"] for item in candidates}
                        raw_paths = [item["path"] for item in candidates[:2]]
                        effect = "下一輪將附上照片，模型可使用回傳的真實 ID。"
                    if name == "stitch_images" and observation.get("ok"):
                        pano_id = observation["image_id"]
                        effect = "下一輪可用回傳的全景 ID 存檔。"
                    if name == "save_image" and observation.get("ok") and params["image_id"] == pano_id:
                        panorama = observation["path"]
                        effect = "可讀的全景路徑將與左、右原圖一同作為比較圖輸入。"
                elif action == "write_and_run_python":
                    if "image-comparison-report" not in loaded or not inspected or not inputs:
                        raise ValueError("先讀比較圖 Skill、檢查 Function，並存好全景")
                    output = _relative(run_dir / "comparison.png")
                    code, entry["code_generation_reply"] = self._write_comparison(
                        inputs, output, last_script_result, reference,
                    )
                    observation = self._render(code, inputs, run_dir, step)
                    last_script_result = observation
                    if observation["ok"]:
                        comparison = observation
                    effect = "腳本執行與 PNG 尺寸標籤驗收結果已交回模型。"
                elif action == "finish":
                    if not panorama or not comparison:
                        raise ValueError("尚未完成可驗證的全景與比較圖")
                    final = str(args["summary"])
                    observation = {"ok": True, "panorama": panorama, "comparison": comparison["path"]}
                    effect, finished = "兩個成果皆已驗證，本次結束。", True
                else:
                    raise ValueError(f"未知動作：{action}")
            except Exception as exc:
                observation = {"ok": False, "error": quiz1.redact(exc)}
                effect = "錯誤結果已交回模型，可修正動作或參數後再試。"
            entry.update(observation=observation, next_effect=effect, model_reply=reply,
                         seconds=round(time.perf_counter() - started, 3))
            rounds.append(entry)
            feedback = "上一輪實際結果：" + json.dumps(observation, ensure_ascii=False)
            log.update(panorama=panorama, comparison=comparison, final=final,
                       completed=finished, record=_relative(record_path))
            record_path.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"Quiz 3 第 {step} 輪：{entry['action']} "
                  f"{entry['arguments'].get('name', '')} → {observation.get('error', '成功')}", flush=True)
            if finished:
                break
        return log


def run_demo(vision=None, *, comparison_reference=None):
    return Quiz3Agent(vision or quiz2.QwenVision(local_only=True)).run(
        DEMO_TASK, comparison_reference=comparison_reference,
    )
