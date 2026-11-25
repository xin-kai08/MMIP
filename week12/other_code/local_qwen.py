"""Run the official Qwen3 weights directly in the Notebook's Python process."""

import json
import os
import re
import ssl
import uuid
from functools import lru_cache

DEFAULT_MODEL = "Qwen/Qwen3-1.7B"
COMPARISON_MODELS = (DEFAULT_MODEL, "Qwen/Qwen3-0.6B")
_loaded = None


class LocalModelError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _configure_hub_tls():
    import requests
    from huggingface_hub import configure_http_backend

    context = ssl.create_default_context()

    class SystemCertificatesAdapter(requests.adapters.HTTPAdapter):
        def build_connection_pool_key_attributes(self, request, verify, cert=None):
            host, keys = super().build_connection_pool_key_attributes(request, verify, cert)
            if verify is True:
                keys["ssl_context"] = context
            return host, keys

    def session_factory():
        session = requests.Session()
        session.mount("https://", SystemCertificatesAdapter())
        return session

    configure_http_backend(backend_factory=session_factory)


def _load(model_id):
    global _loaded
    if _loaded is not None and _loaded[0] == model_id:
        return _loaded[1:]
    if os.name == "nt":
        # Keep Hub downloads on the HTTPS client that uses Windows trust roots.
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError:
        raise LocalModelError("Qwen: 請用 MMIP Python 安裝 requirements.txt 的套件") from None

    _loaded = None
    try:
        _configure_hub_tls()
        use_cuda = False
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            minimum_gib = 2.0 if model_id == COMPARISON_MODELS[1] else 4.5
            use_cuda = torch.cuda.mem_get_info()[0] >= minimum_gib * 1024**3
        device = "cuda" if use_cuda else "cpu"
        dtype = torch.float16 if use_cuda else torch.float32
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForCausalLM.from_pretrained(
            model_id, torch_dtype=dtype, use_safetensors=True,
        ).to(device).eval()
    except (OSError, RuntimeError, ValueError) as exc:
        raise LocalModelError(f"Qwen: 無法下載或載入 {model_id}：{exc}") from None
    _loaded = (model_id, tokenizer, model, torch, device)
    return _loaded[1:]


def _parse_response(text):
    text = re.sub(r"^\s*<think>.*?</think>\s*", "", text, count=1, flags=re.S)
    text = text.split("<|im_end|>", 1)[0].removesuffix("<|endoftext|>").strip()
    pattern = r"<tool_call>\s*(.*?)\s*</tool_call>"
    raw_calls = re.findall(pattern, text, flags=re.S)
    content = re.sub(pattern, "", text, flags=re.S).strip()
    if any(tag in content for tag in ("<tool_call>", "</tool_call>", "<think>")):
        raise LocalModelError("Qwen: 工具呼叫或模型回答未完整產生")
    message = {"role": "assistant", "content": content}
    if raw_calls:
        calls = []
        try:
            for raw in raw_calls:
                call = json.loads(raw)
                if not isinstance(call["name"], str) or not isinstance(call["arguments"], dict):
                    raise ValueError("unexpected tool call")
                calls.append({"id": uuid.uuid4().hex, "type": "function", "function": call})
        except (KeyError, TypeError, ValueError):
            raise LocalModelError("Qwen: 工具呼叫格式錯誤") from None
        message["tool_calls"] = calls
    return message


def qwen_chat(messages, model=DEFAULT_MODEL, tools=None):
    tokenizer, weights, torch, device = _load(model)
    try:
        inputs = tokenizer.apply_chat_template(
            messages, tools=tools, add_generation_prompt=True, enable_thinking=False,
            tokenize=True, return_dict=True, return_tensors="pt",
        ).to(device)
        with torch.inference_mode():
            output = weights.generate(**inputs, max_new_tokens=768, do_sample=False)
        generated = output[0][inputs["input_ids"].shape[-1]:]
        return _parse_response(tokenizer.decode(generated, skip_special_tokens=False))
    except RuntimeError as exc:
        raise LocalModelError(f"Qwen: 本機推論失敗：{exc}") from None
