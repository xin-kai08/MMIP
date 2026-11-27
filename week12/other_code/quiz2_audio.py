"""Quiz 2 Mandarin voice input and replies for the image Agent."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import wave
from contextlib import contextmanager
from functools import lru_cache
from math import gcd
from pathlib import Path
from uuid import uuid4

import numpy as np
from PIL import Image

from .quiz2 import IMAGE_SCHEMAS, RESULT_DIR, ROOT, ImageAgent, QwenVision, _inside, _project_path

AUDIO_CACHE = ROOT / ".cache" / "quiz2" / "audio"
WHISPER_ID = "openai/whisper-small"
PIPER_ID = "rhasspy/piper-voices"
PIPER_VOICE = "zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx"
SAMPLE_RATE = 16000
VOICE_TOOLS = ("speech_to_text", "text_to_speech")
DEMO_INSTRUCTION = "請把這個資料夾裡兩張有重疊的照片拼成全景圖並存檔。"


def _audio_env():
    root = _inside(AUDIO_CACHE)
    subdirs = {
        "HF_HOME": "hf", "HF_HUB_CACHE": "hf/hub", "HF_XET_CACHE": "hf/xet",
        "HF_ASSETS_CACHE": "hf/assets", "XDG_CACHE_HOME": "xdg", "TORCH_HOME": "torch",
        "CUDA_CACHE_PATH": "cuda", "TMPDIR": "tmp", "TMP": "tmp", "TEMP": "tmp",
    }
    paths = {name: _inside(root / subdir, root) for name, subdir in subdirs.items()}
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return {**{name: str(path) for name, path in paths.items()},
            "HF_ENDPOINT": "https://huggingface.co", "HF_HUB_DISABLE_XET": "1",
            "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
            "HF_HUB_DISABLE_PROGRESS_BARS": "1", "PYTHONDONTWRITEBYTECODE": "1"}


@contextmanager
def _audio_runtime():
    settings = _audio_env()
    old = {name: os.environ.get(name) for name in settings}
    old_bytecode = sys.dont_write_bytecode
    os.environ.update(settings)
    sys.dont_write_bytecode = True
    try:
        yield
    finally:
        sys.dont_write_bytecode = old_bytecode
        for name, value in old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _snapshot(repo_id, patterns):
    """Use a separate process so Hub cache constants use the project paths."""
    settings = _audio_env()
    code = """
import sys
from huggingface_hub import snapshot_download
print(snapshot_download(sys.argv[1], allow_patterns=sys.argv[2:], token=False, max_workers=3))
"""
    response = subprocess.run(
        [sys.executable, "-c", code, repo_id, *patterns], cwd=ROOT,
        env={**os.environ, **settings}, capture_output=True, text=True,
    )
    if response.returncode:
        detail = response.stderr.strip().splitlines()
        raise RuntimeError(f"下載 {repo_id} 失敗：" + (detail[-1] if detail else "無錯誤摘要"))
    return _inside(response.stdout.strip(), _inside(AUDIO_CACHE))


def _read_wav(audio_path):
    from scipy.io import wavfile
    from scipy.signal import resample_poly

    path = _project_path(audio_path)
    if path.suffix.lower() != ".wav" or not path.is_file():
        raise ValueError(f"找不到本機 WAV：{audio_path}")
    rate, pcm = wavfile.read(path)
    if np.issubdtype(pcm.dtype, np.unsignedinteger):
        midpoint = (np.iinfo(pcm.dtype).max + 1) / 2
        samples = (pcm.astype(np.float32) - midpoint) / midpoint
    elif np.issubdtype(pcm.dtype, np.signedinteger):
        samples = pcm.astype(np.float32) / -float(np.iinfo(pcm.dtype).min)
    else:
        samples = pcm.astype(np.float32)
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    if not samples.size or not np.isfinite(samples).all() or not np.any(samples):
        raise ValueError("WAV 沒有可轉錄的有效訊號")
    if rate != SAMPLE_RATE:
        divisor = gcd(rate, SAMPLE_RATE)
        samples = resample_poly(samples, SAMPLE_RATE // divisor, rate // divisor)
    return path, np.clip(samples, -1, 1)


@lru_cache(maxsize=1)
def _whisper():
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    if not torch.cuda.is_available():
        raise RuntimeError("現有 Notebook kernel 無法使用 CUDA")
    snapshot = _snapshot(WHISPER_ID, ("*.json", "*.txt", "model.safetensors"))
    processor = WhisperProcessor.from_pretrained(snapshot, local_files_only=True)
    model = WhisperForConditionalGeneration.from_pretrained(
        snapshot, local_files_only=True, use_safetensors=True, dtype=torch.float16,
    ).to("cuda").eval()
    return torch, processor, model


def speech_to_text(audio_path):
    """Transcribe a project-local Mandarin WAV with multilingual Whisper."""
    with _audio_runtime():
        path, samples = _read_wav(audio_path)
        torch, processor, model = _whisper()
        is_long = len(samples) > 30 * SAMPLE_RATE
        inputs = processor(
            samples, sampling_rate=SAMPLE_RATE, return_tensors="pt",
            return_attention_mask=True, truncation=not is_long,
            padding="longest" if is_long else "max_length",
        )
        with torch.inference_mode():
            predicted = model.generate(
                input_features=inputs.input_features.to(device=model.device, dtype=model.dtype),
                attention_mask=inputs.attention_mask.to(model.device),
                language="zh", task="transcribe", return_timestamps=is_long,
            )
        text = processor.batch_decode(predicted, skip_special_tokens=True)[0].strip()
    if not text:
        raise RuntimeError("Whisper 沒有轉錄出文字")
    return {"path": path.relative_to(ROOT).as_posix(), "text": text,
            "model": WHISPER_ID, "device": str(model.device)}


def missing_piper_packages():
    dependencies = {"piper": "piper-tts", "onnxruntime": "onnxruntime"}
    return [package for module, package in dependencies.items()
            if importlib.util.find_spec(module) is None]


def text_to_speech(text):
    """Synthesize a local Mandarin WAV with Piper and its paired ONNX config."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("請提供要合成的文字")
    missing = missing_piper_packages()
    if missing:
        raise RuntimeError("目前 Notebook kernel 缺少：" + "、".join(missing))
    snapshot = _snapshot(PIPER_ID, (PIPER_VOICE, f"{PIPER_VOICE}.json"))
    model_path = snapshot / PIPER_VOICE
    config_path = snapshot / f"{PIPER_VOICE}.json"
    env = _audio_env()
    cache = _inside(AUDIO_CACHE)
    resources = _inside(cache / "piper", cache)
    resources.mkdir(parents=True, exist_ok=True)
    result_dir = _inside(RESULT_DIR)
    result_dir.mkdir(parents=True, exist_ok=True)
    tag = uuid4().hex
    output = result_dir / f"voice_{tag[:12]}.wav"
    temporary = _inside(cache / "tmp" / f"voice_{tag}.wav", cache)
    code = """
import sys
import wave
from piper import PiperVoice
voice = PiperVoice.load(sys.argv[1], config_path=sys.argv[2], download_dir=sys.argv[3])
with wave.open(sys.argv[4], "wb") as stream:
    voice.synthesize_wav(sys.stdin.read(), stream)
"""
    try:
        response = subprocess.run(
            [sys.executable, "-c", code, str(model_path), str(config_path),
             str(resources), str(temporary)], cwd=ROOT,
            env={**os.environ, **env, "PYTHONIOENCODING": "utf-8"},
            input=text, encoding="utf-8", capture_output=True,
        )
        if response.returncode:
            detail = response.stderr.strip().splitlines()
            raise RuntimeError("Piper 合成失敗：" + (detail[-1] if detail else "無錯誤摘要"))
        with wave.open(str(temporary), "rb") as audio:
            frames, rate = audio.getnframes(), audio.getframerate()
            if not frames or not rate:
                raise RuntimeError("Piper 未產生可播放的 WAV")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": output.relative_to(ROOT).as_posix(), "voice": Path(PIPER_VOICE).stem,
            "sample_rate": rate, "seconds": round(frames / rate, 3)}


def voice_tool_names():
    from .quiz1 import TOOLS

    return [tool["function"]["name"] for tool in TOOLS] + list(IMAGE_SCHEMAS) + list(VOICE_TOOLS)


def _voice_call(trace, function, **arguments):
    started = time.perf_counter()
    try:
        result = {"ok": True, **function(**arguments)}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    trace.append({"source": "voice_workflow", "tool": function.__name__,
                  "arguments": arguments, "result": result,
                  "seconds": round(time.perf_counter() - started, 3)})
    return result


def _verified_image_exports(agent_trace):
    processed, exports = {}, []
    for entry in agent_trace:
        data = entry["result"]
        if not data.get("ok"):
            continue
        tool = entry["tool"]
        if tool in {"stitch_images", "match_exposure"}:
            processed[data["image_id"]] = tool
        source = processed.get(entry["arguments"].get("image_id"))
        if tool == "save_image" and source:
            try:
                path = _inside(_project_path(data["path"]), _inside(RESULT_DIR))
                with Image.open(path, formats=["PNG"]) as image:
                    image.load()
                exports.append({"path": data["path"], "processed_by": source})
            except (OSError, ValueError):
                continue
    return exports


def _spoken_reply(vision, transcript, agent_run, exports, failure):
    trace = agent_run["trace"] if agent_run else []
    completed, pending_errors = {}, {}
    labels = {
        "get_local_photos": "讀取照片",
        "match_exposure": "亮度校正",
        "stitch_images": "全景拼接",
        "save_image": "存檔",
    }
    for entry in trace:
        tool, result = entry["tool"], entry["result"]
        if tool not in labels:
            continue
        if result.get("ok"):
            if tool == "get_local_photos":
                completed[tool] = f"已讀取 {len(result['photos'])} 張照片"
            elif tool == "stitch_images":
                completed[tool] = "已拼成全景圖"
            elif tool == "match_exposure":
                completed[tool] = "已校正亮度"
            pending_errors.pop(tool, None)
        elif result.get("error"):
            pending_errors[tool] = f"{labels[tool]}未完成，{result['error']}"

    if any(item["processed_by"] == "stitch_images" for item in exports):
        storage = "全景圖已存檔。"
    elif exports:
        storage = "處理後的圖片已存檔。"
    else:
        storage = "這次沒有匯出圖片。"
    remaining = list(pending_errors.values())
    if failure and failure not in {entry["result"].get("error") for entry in trace}:
        remaining.append(failure)
    facts = {
        "使用者要求": transcript,
        "已完成的影像步驟": list(completed.values()),
        "未完成的工具步驟": remaining,
        "是否成功執行額外亮度校正": "match_exposure" in completed,
        "Agent 的最後說明（僅供理解，不作為成功證據）": agent_run["final"] if agent_run else "",
    }
    fallback_parts = [*completed.values(), *remaining]
    if "match_exposure" not in completed and any(word in (transcript or "") for word in ("亮度", "曝光")):
        fallback_parts.append("沒有另外做亮度校正")
    if not fallback_parts and agent_run and agent_run["final"]:
        fallback_parts.append("目前的工具沒有執行這項操作")
    fallback = "。".join(" ".join(part.split()).rstrip("。") for part in fallback_parts)
    fallback = f"{fallback[:160]}。{storage}" if fallback else storage
    if vision is None or agent_run is None:
        return fallback, "voice_workflow"
    storage_instruction = (
        f"已核實的存檔狀態為「{storage}」，可以自然地融入回覆，但不要念檔案路徑。"
        if exports else "存檔狀態由程式另行播報，請不要提到存檔、匯出或檔案路徑。"
    )
    try:
        text, _ = vision.reply([
            {"role": "system", "content": (
                "你負責把影像工具結果整理成自然、簡短的繁體中文口語，供語音朗讀。"
                "用一到兩句回覆，先說已做的步驟，再說未完成事項。"
                "如果使用者在意亮度，照實說是否另外校正過。"
                "有失敗時用工具回傳的原因，避免推測；需求不明確時可請對方補充。"
                "只能用已驗證的工具結果描述實際成果。沒有執行的步驟不可說有完成。"
                + storage_instruction
                + "省略制式道歉和客套結尾，不要輸出標題、Markdown、工具名稱或 JSON。"
            )},
            {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
        ], [])
        storage_words = (
            "存檔", "存档", "匯出", "导出", "儲存", "保存", "存储", "寫入", "写入",
            "存好", "存下", "存成", "存到", "存了",
        )
        blocked_words = ("檔名", "路徑", "路径", "/", "`", "{", "}", "#")
        if not exports:
            blocked_words += storage_words
        sentences = re.split(r"(?<=[。！？!?])|\n+", text)
        text = "".join(part.strip() for part in sentences
                       if not any(word in part for word in blocked_words))
        if text and len(text) <= 160:
            if ("get_local_photos" in completed and "stitch_images" in pending_errors
                    and not any(word in text for word in ("讀取", "讀到", "找到", "取到"))):
                text = f"{completed['get_local_photos']}。{text}"
            if text[-1] not in "。！？!?":
                text += "。"
            if exports and any(word in text for word in storage_words):
                return text, "qwen_model"
            return f"{text}{storage}", "qwen_model"
    except Exception:
        pass
    return fallback, "voice_workflow"


def run_voice_dialog(audio_path, photo_folder, *, vision=None):
    """Run STT, model-selected image tools, and a result-grounded TTS reply."""
    trace = []
    stt = _voice_call(trace, speech_to_text, audio_path=str(audio_path))
    agent_run, failure, exports = None, None, []
    if stt["ok"]:
        try:
            if vision is None:
                vision = QwenVision(local_only=True)
            agent = ImageAgent(vision, with_local_photos=True)
            folder = _project_path(photo_folder).relative_to(ROOT).as_posix()
            first_call = json.dumps(
                {"name": "get_local_photos", "arguments": {"folder": folder}},
                ensure_ascii=False,
            )
            instruction = (
                f"使用者語音指令：{stt['text']}\n"
                "請依這次的完整口語要求完成影像任務，尊重使用者明確要求做或略過的步驟。"
                "本次只提供照片資料夾，尚未載入圖片。需要查看或處理圖片時，第一輪先取圖，"
                f"輸出這個工具呼叫：{first_call}\n"
                "取得照片後，再依實際影像和工具回傳決定後續動作。"
                "只使用工具回傳的真實圖片 ID，ID1 和 ID2 只是範例。"
                "每輪只呼叫一個工具。如使用者要求存檔，處理成功後用對應的圖片 ID 存檔。"
                "只完成一部分時，說明有哪些已完成、哪些未完成及已知原因。"
                "如果缺少必要資訊或工具不支援，請明確說明，不要擅自替換任務。"
            )
            agent_run = agent.run(instruction, folder=folder)
            trace.extend({**entry, "source": "qwen_model"} for entry in agent_run["trace"])
            exports = _verified_image_exports(agent_run["trace"])
            failure = agent_run["error"]
        except Exception as exc:
            failure = str(exc)
    else:
        failure = stt["error"]

    panorama = next((item["path"] for item in exports if item["processed_by"] == "stitch_images"), None)
    spoken, reply_source = _spoken_reply(vision, stt.get("text"), agent_run, exports, failure)
    tts = _voice_call(trace, text_to_speech, text=spoken)
    return {"registered_tools": voice_tool_names(), "trace": trace, "transcript": stt.get("text"),
            "agent": agent_run, "panorama": panorama, "image_exports": exports, "error": failure,
            "spoken_text": spoken, "spoken_text_source": reply_source, "reply_wav": tts.get("path")}
