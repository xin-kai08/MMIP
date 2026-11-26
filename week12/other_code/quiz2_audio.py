"""Quiz 2 Mandarin voice input and replies for the image Agent."""
from __future__ import annotations

import importlib.util
import os
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
             str(resources), str(temporary)], cwd=ROOT, env={**os.environ, **env},
            input=text, text=True, capture_output=True,
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


def _saved_panorama(agent_trace):
    panoramas = set()
    for entry in agent_trace:
        data = entry["result"]
        if not data.get("ok"):
            continue
        if entry["tool"] == "stitch_images":
            panoramas.add(data["image_id"])
        if entry["tool"] == "save_image" and entry["arguments"].get("image_id") in panoramas:
            try:
                path = _inside(_project_path(data["path"]), _inside(RESULT_DIR))
                with Image.open(path, formats=["PNG"]) as image:
                    image.load()
                return data["path"]
            except (OSError, ValueError):
                continue
    return None


def run_voice_dialog(audio_path, photo_folder, *, vision=None):
    """Run STT, model-selected image tools, and a result-grounded TTS reply."""
    trace = []
    stt = _voice_call(trace, speech_to_text, audio_path=str(audio_path))
    panorama, agent_run, failure = None, None, None
    if stt["ok"]:
        try:
            if vision is None:
                vision = QwenVision(local_only=True)
            agent = ImageAgent(vision, with_local_photos=True)
            agent_run = agent.run(stt["text"], folder=photo_folder)
            trace.extend({**entry, "source": "qwen_model"} for entry in agent_run["trace"])
            panorama = _saved_panorama(agent_run["trace"])
            if panorama is None:
                errors = [entry["result"].get("error") for entry in agent_run["trace"]
                          if entry["tool"] in {"get_local_photos", "stitch_images", "save_image"}
                          and entry["result"].get("error")]
                failure = (errors[-1] if errors else agent_run["error"]) or "未取得可讀的全景匯出"
        except Exception as exc:
            failure = str(exc)
    else:
        failure = stt["error"]

    spoken = ("全景圖已存檔。" if panorama else
              "這次沒有成功存檔。" + " ".join((failure or "").split())[:180])
    tts = _voice_call(trace, text_to_speech, text=spoken)
    return {"registered_tools": voice_tool_names(), "trace": trace, "transcript": stt.get("text"),
            "agent": agent_run, "panorama": panorama, "error": failure,
            "spoken_text": spoken, "reply_wav": tts.get("path")}
