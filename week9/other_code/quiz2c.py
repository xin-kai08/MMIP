import torch
import time
from importlib.metadata import version
from lmformatenforcer import JsonSchemaParser
from lmformatenforcer.tokenenforcer import TokenEnforcerTokenizerData
from lmformatenforcer.characterlevelparser import CharacterLevelParserConfig
from lmformatenforcer.integrations.transformers import build_transformers_prefix_allowed_tokens_fn, build_token_enforcer_tokenizer_data
from . import quiz2a as a

_TOKENIZER_DATA = {}

def get_safe_tokenizer_data(tokenizer):
    """建立包含完整常用中文字元的單行JSON token資料。"""
    key = id(tokenizer)

    if key not in _TOKENIZER_DATA:
        tokenizer.clean_up_tokenization_spaces = False

        original = build_token_enforcer_tokenizer_data(tokenizer)

        # 排除包含原始控制字元的token
        safe_tokens = [
            (token_id, text, is_word_start)
            for token_id, text, is_word_start
            in original.regular_tokens
            if not any(ord(char) < 32 for char in text)
        ]

        safe_data = TokenEnforcerTokenizerData(regular_tokens=safe_tokens, decoder=original.decoder, eos_token_id=original.eos_token_id, 
                                               use_bitmask=original.use_bitmask, vocab_size=original.vocab_size)

        # 收集每個token內的所有字元，不只看起始字元
        characters = set(safe_data.tokenizer_alphabet)

        for _, text, _ in safe_tokens:
            characters.update(text)

        # 有些中文字需由多個byte token組成，
        # 因此另外補入常用CJK漢字範圍
        characters.update(chr(code) for code in range(0x3400, 0xA000))

        safe_data.tokenizer_alphabet = "".join(
            sorted(
                char for char in characters
                if ord(char) >= 32
            )
        )

        _TOKENIZER_DATA[key] = safe_data

    return _TOKENIZER_DATA[key]

# 生成時限制基本JSON結構、欄位型別與允許選項。
# 完整schema.json仍保留給Prompt與生成後驗證。
DECODING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "status",
        "department",
        "product",
        "summary",
        "missing_fields",
        "reply",
    ],
    "properties": {
        "status": {
            "type": "string",
            "enum": [
                "clarify",
                "route",
                "off_topic",
                "blocked",
                "human",
            ],
        },
        "department": {
            "anyOf": [
                {
                    "type": "string",
                    "enum": [
                        "order_logistics",
                        "returns",
                        "technical_support",
                    ],
                },
                {"type": "null"},
            ],
        },
        "product": {
            "anyOf": [
                {"type": "string"},
                {"type": "null"},
            ],
        },
        "summary": {
            "type": "string",
        },
        "missing_fields": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },
        "reply": {
            "type": "string",
            "minLength": 1,
        },
    },
}


def generate_reply(model, processor, case, system_prompt):
    torch.cuda.synchronize()
    start = time.perf_counter()

    tokenizer_data = get_safe_tokenizer_data(processor.tokenizer)

    parser_config = CharacterLevelParserConfig(alphabet=tokenizer_data.tokenizer_alphabet)

    parser = JsonSchemaParser(DECODING_SCHEMA, config=parser_config)

    prefix_function = (build_transformers_prefix_allowed_tokens_fn(tokenizer_data, parser))

    result = a.generate_reply(model, processor, case, system_prompt, generation_kwargs={"prefix_allowed_tokens_fn": prefix_function,
                                                                                        "eos_token_id": processor.tokenizer.eos_token_id,
                                                                                        "pad_token_id": processor.tokenizer.pad_token_id},)

    torch.cuda.synchronize()
    result["elapsed_seconds"] = time.perf_counter() - start

    return result

def run_benchmark(model, processor, cases, schema, validator):
    """共用A的評估流程，替換成受限生成。"""
    report, result_path = a.run_benchmark(model, processor, cases, schema, validator, method="C_decoding", generate_fn=generate_reply)

    report["decoding"] = {
        "library": "lm-format-enforcer",
        "version": version("lm-format-enforcer"),
        "schema": DECODING_SCHEMA,
        "scope": (
            "生成時限制JSON結構、必填欄位、型別與enum；"
            "完整Schema及跨欄位規則於生成後驗證"
        ),
    }

    report["timing_scope"] = (
        "解碼限制準備、圖片讀取、前處理、生成與解碼；"
        "不含模型載入、暖機與格式驗證"
    )

    a.save_report(report, result_path)

    return report, result_path