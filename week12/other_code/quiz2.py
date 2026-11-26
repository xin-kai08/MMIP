"""Quiz 2 local image tools and the Qwen2.5-VL agent."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "Qwen/Qwen2.5-VL-3B-Instruct"
CACHE_DIR = ROOT / ".cache" / "quiz2" / "huggingface"
RESULT_DIR = ROOT / "result" / "quiz2"
STITCH_CACHE_DIR = RESULT_DIR / "cache"
STITCH_MODE = cv2.Stitcher_PANORAMA
PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def _inside(path, root=ROOT):
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("路徑超出允許的目錄")
    return resolved


def download_model(*, local_only=False):
    """Download the official snapshot with isolated Hub and temporary paths."""
    cache = _inside(CACHE_DIR)
    folders = {name: _inside(cache / suffix, cache) for name, suffix in {
        "HF_HUB_CACHE": "hub", "HF_XET_CACHE": "xet",
        "HF_ASSETS_CACHE": "assets", "TMPDIR": "tmp",
    }.items()}
    marker = _inside(cache / "snapshot.txt", cache)
    if marker.is_file():
        snapshot = _inside(cache / marker.read_text(encoding="utf-8").strip(), cache)
        index = snapshot / "model.safetensors.index.json"
        if index.is_file():
            shards = set(json.loads(index.read_text(encoding="utf-8"))["weight_map"].values())
            if all(_inside(snapshot / name, cache).is_file() for name in
                   shards | {"config.json", "preprocessor_config.json", "tokenizer.json"}):
                return snapshot
    if local_only:
        raise FileNotFoundError("Quiz 2 專用模型快取不完整，無法離線載入")
    for folder in folders.values():
        folder.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({name: str(folder) for name, folder in folders.items()})
    env.update(HF_HOME=str(cache), HF_ENDPOINT="https://huggingface.co",
               TEMP=str(folders["TMPDIR"]), TMP=str(folders["TMPDIR"]),
               HF_HUB_DISABLE_XET="1", HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
               HF_HUB_DISABLE_TELEMETRY="1", HF_HUB_OFFLINE="0",
               HF_HUB_DISABLE_PROGRESS_BARS="1", PYTHONDONTWRITEBYTECODE="1")
    code = """
from huggingface_hub import snapshot_download
import sys
print(snapshot_download(sys.argv[1], repo_type="model", token=False,
    cache_dir=sys.argv[2], max_workers=3,
    allow_patterns=["*.json", "*.safetensors", "*.txt", "*.jinja"]))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, MODEL_ID, str(folders["HF_HUB_CACHE"])],
        cwd=ROOT, env=env, check=True, stdout=subprocess.PIPE, text=True,
    )
    snapshot = _inside(completed.stdout.strip(), cache)
    marker.write_text(str(snapshot.relative_to(cache)), encoding="utf-8")
    return snapshot


def _project_path(path):
    return _inside(ROOT / path)


def _relative(path):
    return path.relative_to(ROOT).as_posix()


def _stitch_cache_key(frames):
    settings = {"version": 1, "opencv": cv2.__version__, "mode": STITCH_MODE,
                "frame_count": len(frames)}
    digest = hashlib.sha256(json.dumps(settings, sort_keys=True).encode("utf-8"))
    for frame in frames:
        # The shape and dtype delimit the bytes of each ordered BGR frame.
        digest.update(f"\n{frame.shape}:{frame.dtype.str}\n".encode("ascii"))
        digest.update(memoryview(frame).cast("B"))
    return digest.hexdigest()


def _read_cached_panorama(path):
    try:
        with Image.open(path, formats=["PNG"]) as image:
            return image.convert("RGB")
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return None


def _write_cached_panorama(path, image):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
            temp = Path(stream.name)
            image.save(stream, format="PNG")
        temp.replace(path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def make_test_photos():
    """Write a deterministic, textured scene and two overlapping test crops."""
    folder = _project_path("data/quiz2/_synthetic")
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(2026)
    scene = np.full((420, 1000, 3), (145, 174, 196), np.uint8)
    for _ in range(420):
        x, y = map(int, rng.integers((0, 0), (1000, 420)))
        colour = tuple(map(int, rng.integers(20, 240, 3)))
        size = int(rng.integers(4, 22))
        cv2.circle(scene, (x, y), size, colour, int(rng.integers(1, 5)))
    for x, label in ((45, "LEFT"), (370, "OVERLAP"), (790, "RIGHT")):
        cv2.putText(scene, label, (x, 210), cv2.FONT_HERSHEY_SIMPLEX,
                    1.35, (36, 50, 78), 3, cv2.LINE_AA)
    photos = {"synthetic_left.png": scene[:, :670],
              "synthetic_right_dark.png": (scene[:, 330:] * 0.63).astype(np.uint8)}
    for name, pixels in photos.items():
        path = _inside(folder / name, folder)
        if not path.exists():
            Image.fromarray(pixels).save(path, format="PNG")
    return _relative(folder), tuple(photos)


class ImageTools:
    """Keep intermediate images in one session and save only on request."""

    def __init__(self, *, stitch_cache=False, cache_namespace=None):
        if cache_namespace is not None and (
            not cache_namespace or Path(cache_namespace).name != cache_namespace
            or cache_namespace in {".", ".."} or "\\" in cache_namespace
        ):
            raise ValueError("快取子目錄須為單一目錄名稱")
        self._files = {}
        self._images = {}
        self.stitch_cache = stitch_cache
        self._cache_namespace = cache_namespace

    def register_photo(self, path):
        photo = _project_path(path)
        if not photo.is_file() or photo.suffix.lower() not in PHOTO_SUFFIXES:
            raise ValueError(f"找不到支援的照片：{path}")
        with Image.open(photo) as image:
            image.verify()
        image_id = f"photo:{_relative(photo)}"
        self._files[image_id] = photo
        return {"image_id": image_id, "filename": photo.name, "path": _relative(photo)}

    def get_local_photos(self, folder):
        """Register readable photos directly inside the chosen folder."""
        directory = _project_path(folder)
        if not directory.is_dir():
            raise ValueError(f"找不到照片資料夾：{folder}")
        photos, unreadable = [], []
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix.lower() not in PHOTO_SUFFIXES:
                continue
            try:
                photos.append(self.register_photo(path))
            except (OSError, ValueError, Image.DecompressionBombError):
                unreadable.append(path.name)
        return {"ok": bool(photos), "folder": _relative(directory), "photos": photos,
                "unreadable": unreadable, **({} if photos else {"error": "資料夾沒有可讀照片"})}

    def image(self, image_id):
        if image_id in self._images:
            return self._images[image_id]
        if image_id not in self._files:
            raise ValueError(f"未知圖片 ID：{image_id}")
        with Image.open(_inside(self._files[image_id])) as image:
            return ImageOps.exif_transpose(image).convert("RGB")

    def _remember(self, label, image):
        image_id = f"{label}:{uuid4().hex[:8]}"
        self._images[image_id] = image
        return {"ok": True, "image_id": image_id, "width": image.width, "height": image.height}

    def match_exposure(self, reference_id, target_id):
        """Scale the target's luminance toward the reference's mean."""
        reference, target = self.image(reference_id), self.image(target_id)
        reference_mean = float(np.asarray(reference.convert("L")).mean())
        before = float(np.asarray(target.convert("L")).mean())
        if before < 1:
            return {"ok": False, "error": "待校正照片近乎全黑，無法可靠估算增益"}
        gain = float(np.clip(reference_mean / before, 0.25, 4.0))
        corrected = Image.fromarray(np.clip(np.asarray(target) * gain, 0, 255).astype(np.uint8))
        return {**self._remember("exposure", corrected), "reference_id": reference_id,
                "target_id": target_id, "gain": round(gain, 3),
                "reference_mean": round(reference_mean, 2), "target_mean_before": round(before, 2),
                "target_mean_after": round(float(np.asarray(corrected.convert("L")).mean()), 2)}

    def stitch_images(self, image_ids):
        """Find overlapping features and stitch a panorama with OpenCV."""
        info = {"cache_status": "off", "opencv_executed": False}
        if self.stitch_cache:
            info["cache_status"] = "not_checked"
        if not isinstance(image_ids, list) or len(image_ids) < 2 or len(set(image_ids)) != len(image_ids):
            return {**info, "ok": False, "error": "拼接需要至少兩張不同的照片"}
        frames = [np.ascontiguousarray(np.asarray(self.image(image_id))[:, :, ::-1])
                  for image_id in image_ids]  # RGB -> OpenCV BGR, also on a hit
        cache_path = None
        if self.stitch_cache:
            directory = _inside(STITCH_CACHE_DIR)
            if self._cache_namespace is not None:
                directory = _inside(directory / self._cache_namespace, directory)
            key = _stitch_cache_key(frames)
            cache_path = directory / f"{key}.png"
            if cache_path.is_symlink():
                raise ValueError("拼接快取檔不得是符號連結")
            info.update(cache_status="miss", cache_key=key)
            cached = _read_cached_panorama(cache_path)
            if cached is not None:
                info.update(cache_status="hit", cache_path=_relative(cache_path))
                return {**self._remember("panorama", cached), **info,
                        "source_ids": image_ids, "opencv_status": int(cv2.Stitcher_OK)}
        info["opencv_executed"] = True
        try:
            status, panorama = cv2.Stitcher_create(STITCH_MODE).stitch(frames)
        except cv2.error as exc:
            return {**info, "ok": False, "error": f"OpenCV 拼接例外：{exc}"}
        reasons = {
            cv2.Stitcher_ERR_NEED_MORE_IMGS: "可配對的重疊影像不足",
            cv2.Stitcher_ERR_HOMOGRAPHY_EST_FAIL: "無法估算影像對齊所需的單應矩陣",
            cv2.Stitcher_ERR_CAMERA_PARAMS_ADJUST_FAIL: "相機參數調整失敗",
        }
        if status != cv2.Stitcher_OK or panorama is None or not panorama.size:
            return {**info, "ok": False, "opencv_status": int(status),
                    "error": reasons.get(status, "OpenCV 未產生全景影像")}
        image = Image.fromarray(cv2.cvtColor(panorama, cv2.COLOR_BGR2RGB))
        if cache_path is not None:
            try:
                _write_cached_panorama(cache_path, image)
                info["cache_path"] = _relative(cache_path)
            except OSError as exc:
                info["cache_error"] = f"無法寫入拼接快取：{exc}"
        return {**self._remember("panorama", image), **info, "source_ids": image_ids,
                "opencv_status": int(status)}

    def save_image(self, image_id, filename="panorama.png"):
        """Save a processed image under result/quiz2 without overwriting."""
        if image_id not in self._images:
            raise ValueError("請提供已處理圖片的 ID")
        name = Path(filename)
        if name.name != filename or name.suffix.lower() != ".png" or "\\" in filename:
            raise ValueError("請提供單一 PNG 檔名")
        directory = _inside(RESULT_DIR)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name.stem}_{uuid4().hex[:8]}.png"
        image = self._images[image_id]
        with path.open("xb") as stream:
            image.save(stream, format="PNG")
        return {"ok": True, "image_id": image_id, "path": _relative(path),
                "width": image.width, "height": image.height}


IMAGE_SCHEMAS = {
    "match_exposure": "以 reference_id 為亮度基準校正 target_id，回傳新 image_id",
    "stitch_images": "以 image_ids（字串陣列，至少兩張）拼接重疊照片，回傳全景 image_id",
    "save_image": "以 image_id 儲存已處理影像，filename 可省略或給 PNG 檔名",
    "get_local_photos": "以 folder（相對於專案）讀取本機照片，回傳候選 image_id",
}


@contextmanager
def _local_runtime():
    cache = _inside(CACHE_DIR)
    cuda_cache = _inside(cache / "cuda", cache)
    cuda_cache.mkdir(parents=True, exist_ok=True)
    old_path = os.environ.get("CUDA_CACHE_PATH")
    old_bytecode = sys.dont_write_bytecode
    os.environ["CUDA_CACHE_PATH"] = str(cuda_cache)
    sys.dont_write_bytecode = True
    try:
        yield
    finally:
        sys.dont_write_bytecode = old_bytecode
        if old_path is None:
            os.environ.pop("CUDA_CACHE_PATH", None)
        else:
            os.environ["CUDA_CACHE_PATH"] = old_path


class QwenVision:
    """Local GPU inference using Qwen's image tokens and chat template."""

    def __init__(self, *, local_only=False):
        with _local_runtime():
            import torch
            from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

            if not torch.cuda.is_available():
                raise RuntimeError("現有 Notebook kernel 未能使用 CUDA")
            snapshot = download_model(local_only=local_only)
            self.processor = AutoProcessor.from_pretrained(
                snapshot, local_files_only=True, trust_remote_code=False,
                min_pixels=56 * 56, max_pixels=448 * 448,
            )
            self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                snapshot, local_files_only=True, use_safetensors=True,
                dtype=torch.float16, attn_implementation="sdpa",
            ).to("cuda").eval()
        self.torch = torch

    def reply(self, messages, images):
        with _local_runtime(), self.torch.inference_mode():
            prompt = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True,
            )
            inputs = self.processor(text=[prompt], images=images or None,
                                    return_tensors="pt").to(self.model.device)
            image_grids = inputs.get("image_grid_thw")
            count = 0 if image_grids is None else len(image_grids)
            if count != len(images):
                raise RuntimeError("模型收到的影像數量和輸入不符")
            output = self.model.generate(**inputs, max_new_tokens=384, do_sample=False)
            generated = output[:, inputs["input_ids"].shape[1]:]
            reply = self.processor.batch_decode(generated, skip_special_tokens=True)[0].strip()
        return reply, count


def _tool_request(reply):
    """Parse one model-selected action, if there is one."""
    start = reply.find("{")
    if start < 0:
        return None
    try:
        action, _ = json.JSONDecoder().raw_decode(reply[start:])
    except ValueError as exc:
        raise ValueError("工具呼叫不是有效的 JSON") from exc
    name, args = action.get("name"), action.get("arguments")
    if not isinstance(name, str) or not isinstance(args, dict):
        raise ValueError("工具呼叫須包含名稱和參數物件")
    return name, args


class ImageAgent:
    """Run a bounded observation, tool action, and feedback loop."""

    def __init__(self, vision, with_local_photos=False, allow_travel=False, *,
                 stitch_cache=False, cache_namespace=None):
        from .quiz1 import TOOLS as TRAVEL_SCHEMAS, TravelTools

        self.vision = vision
        self.images = ImageTools(stitch_cache=stitch_cache, cache_namespace=cache_namespace)
        self.travel = TravelTools()
        self.allow_travel = allow_travel
        self.travel_names = {schema["function"]["name"] for schema in TRAVEL_SCHEMAS}
        image_count = 4 if with_local_photos else 3
        self.image_names = set(list(IMAGE_SCHEMAS)[:image_count])
        self.tool_names = self.travel_names | self.image_names
        self.description = json.dumps(TRAVEL_SCHEMAS, ensure_ascii=False) + "\n" + "\n".join(
            f"{name}: {meaning}" for name, meaning in IMAGE_SCHEMAS.items()
            if name in self.image_names
        )

    def _call(self, name, args, folder):
        if name not in self.tool_names:
            raise ValueError(f"工具未註冊：{name}")
        if name in self.travel_names:
            if not self.allow_travel:
                raise ValueError("本次照片任務未授權旅遊工具")
            return getattr(self.travel, name)(**args)
        if name == "get_local_photos":
            if folder is None or _project_path(args.get("folder", "")) != folder:
                raise ValueError("只能讀取使用者指定的資料夾")
        return getattr(self.images, name)(**args)

    def run(self, instruction, photo_paths=(), folder=None, max_rounds=9, *, prepared_photos=()):
        """Accept file paths or (name, PIL image) pairs prepared before the run."""
        from .quiz1 import ServiceError, redact

        folder = _project_path(folder) if folder is not None else None
        photos = [self.images.register_photo(path) for path in photo_paths]
        for filename, image in prepared_photos:
            info = self.images._remember("prepared", image.convert("RGB"))
            photos.append({"image_id": info["image_id"], "filename": filename})
        frames = {photo["image_id"]: self.images.image(photo["image_id"]) for photo in photos}
        system = (
            "你是繁體中文多模態影像助手。每輪依照圖片與上次的實際工具結果選擇下一個動作。"
            '呼叫工具時只輸出一個 JSON，例如 {"name":"stitch_images","arguments":{"image_ids":["ID1","ID2"]}}。'
            "只使用已提供的圖片 ID。若是拼接並存檔的任務，成功存下全景圖後才用繁體中文回答，"
            "並照抄工具回傳的檔案路徑。無法完成時說明實際原因。不要虛構工具結果。"
            "資料夾中若有多張照片，觀察提供的預覽選擇畫面重疊的照片。"
            "亮度有明顯差異才校正，校正成功時用新 ID 取代原目標。"
            "以下是註冊的工具。\n" + self.description
        )
        history = [{"role": "system", "content": system}]
        request = instruction
        if folder is not None:
            request += f"\n指定資料夾：{_relative(folder)}"
        if photos:
            request += "\n使用者指定的照片：" + json.dumps(photos, ensure_ascii=False)
        feedback = request
        trace, exports, observations = [], [], []
        final, error = "", None
        started = time.perf_counter()
        for round_no in range(1, max_rounds + 1):
            visible = list(frames.items())[-10:]
            content = [{"type": "text", "text": feedback}]
            for image_id, _ in visible:
                content.extend([{"type": "text", "text": f"圖片 ID：{image_id}"},
                                {"type": "image"}])
            model_start = time.perf_counter()
            reply, image_count = self.vision.reply(
                history + [{"role": "user", "content": content}],
                [image for _, image in visible],
            )
            model_seconds = round(time.perf_counter() - model_start, 3)
            observations.append({"round": round_no, "image_ids": [item[0] for item in visible],
                                 "images_sent": image_count, "model_reply": reply,
                                 "model_seconds": model_seconds})
            history.extend([{"role": "user", "content": feedback},
                            {"role": "assistant", "content": reply}])
            try:
                action = _tool_request(reply)
            except ValueError as exc:
                feedback = str(exc) + "。請重新送出一個 JSON 工具呼叫。"
                continue
            if action is None:
                final = reply
                break
            name, args = action
            tool_start = time.perf_counter()
            try:
                result = self._call(name, args, folder)
                if name == "get_local_photos" and result.get("ok"):
                    frames.update((photo["image_id"], self.images.image(photo["image_id"]))
                                  for photo in result["photos"][:8])
                if name in {"match_exposure", "stitch_images"} and result.get("ok"):
                    frames[result["image_id"]] = self.images.image(result["image_id"])
                if name == "save_image" and result.get("ok"):
                    exports.append(result["path"])
            except (OSError, ValueError, TypeError, KeyError, ServiceError,
                    Image.DecompressionBombError) as exc:
                result = {"ok": False, "error": redact(exc)}
            trace.append({"round": round_no, "tool": name, "arguments": args,
                          "result": result, "seconds": round(time.perf_counter() - tool_start, 3)})
            feedback = f"{name} 實際回傳：" + json.dumps(result, ensure_ascii=False)
        else:
            error = "已到達工具輪數上限"
        return {"registered_tools": sorted(self.tool_names), "trace": trace,
                "observations": observations, "exports": exports, "final": final,
                "error": error, "seconds": round(time.perf_counter() - started, 3)}


def show_call(tool, arguments, result):
    print(json.dumps({"tool": tool, "arguments": arguments, "result": result},
                     ensure_ascii=False, indent=2))


def show_preview(label, image):
    from IPython.display import display

    preview = image.copy()
    preview.thumbnail((900, 500))
    print(label, f"（原尺寸 {image.width} × {image.height}）")
    display(preview)


def show_run(result):
    print(json.dumps(result, ensure_ascii=False, indent=2))
    for path in result["exports"]:
        with Image.open(_project_path(path)) as image:
            show_preview(path, image)
