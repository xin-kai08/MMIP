import torch
import json
import math
from pathlib import Path
from datasets import Dataset, Image as DatasetImage
from peft import LoraConfig
from trl import DPOConfig, DPOTrainer
from PIL import Image, ImageEnhance, ImageOps
from io import BytesIO

@torch.inference_mode()
def generate_quiz3_answer(question, model, tokenizer):
    messages = [
        {"role": "system", "content": "除非題目另有指定，否則請使用繁體中文回答。"},
        {"role": "user", "content": question},
    ]

    inputs = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                           return_dict=True, return_tensors="pt").to(model.device)

    outputs = model.generate(**inputs, max_new_tokens=512, do_sample=False, pad_token_id=tokenizer.pad_token_id)
    generated_ids = outputs[:, inputs["input_ids"].shape[1]:]

    return tokenizer.decode(generated_ids[0], skip_special_tokens=True, clean_up_tokenization_spaces=False)

def load_dpo_dataset(file_path):
    with open(file_path, "r", encoding="utf-8") as f: raw_data = json.load(f)

    ids = [item["id"] for item in raw_data]
    assert len(ids) == 100 and set(ids) == set(range(1, 101)), \
        "訓練資料應為100組，id須為1～100且不重複"

    rows = []

    for item in raw_data:
        rows.append({
            "prompt": [
                {"role": "system", "content": "除非題目另有指定，否則請使用繁體中文回答。"},
                {"role": "user", "content": item["prompt"]},
            ],
            "chosen": [
                {"role": "assistant", "content": item["chosen"]}
            ],
            "rejected": [
                {"role": "assistant", "content": item["rejected"]}
            ],
        })

    return Dataset.from_list(rows)


def create_dpo_trainer(model, tokenizer, train_dataset, output_dir):
    model.config.use_cache = False

    lora_config = LoraConfig(task_type="CAUSAL_LM", r=8, lora_alpha=16, lora_dropout=0.0,
                             bias="none", target_modules=["q_proj", "v_proj"])

    training_args = DPOConfig(output_dir=str(Path(output_dir)), num_train_epochs=3, learning_rate=5e-5, per_device_train_batch_size=1,
                              gradient_accumulation_steps=8, beta=0.1, loss_type="sigmoid", max_prompt_length=768, max_length=1024,
                              fp16=True, bf16=False, gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
                              logging_steps=1, save_strategy="epoch", save_total_limit=1, report_to="none", seed=42)

    return DPOTrainer(model=model, ref_model=None, args=training_args, train_dataset=train_dataset,
                      processing_class=tokenizer, peft_config=lora_config)

def _reject_constant(value):
    raise ValueError(f"非標準JSON值：{value}")

def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"重複欄位：{key}")
        result[key] = value

    return result

def _same_json(actual, expected):
    if isinstance(expected, bool) or expected is None:
        return type(actual) is type(expected) and actual == expected

    if isinstance(expected, (int, float)):
        return (type(actual) in (int, float) and math.isfinite(actual) and actual == expected)

    if type(actual) is not type(expected):
        return False

    if isinstance(expected, dict):
        return (actual.keys() == expected.keys() and all( _same_json(actual[key], expected[key]) for key in expected))

    if isinstance(expected, list):
        return (len(actual) == len(expected) and all( _same_json(a, e) for a, e in zip(actual, expected)))

    return actual == expected

def evaluate_json_test(result_path, answer_path):
    with open(answer_path, "r", encoding="utf-8") as f: answer_rows = json.load(f)
    with open(result_path, "r", encoding="utf-8") as f: results = json.load(f)

    for label, rows in [
        ("答案", answer_rows),
        ("模型回答", results),
    ]:
        ids = [item["id"] for item in rows]
        if len(ids) != 20 or set(ids) != set(range(1, 21)):
            raise ValueError(f"{label}須有20題，id為1～20且不重複")

    answers = {
        item["id"]: item["expected_json"]
        for item in answer_rows
    }

    details = []

    for item in results:
        response = item["response"]
        if not isinstance(response, str):
            raise ValueError(f"id={item['id']}的response必須是字串")

        try:
            parsed = json.loads(response, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
        except ValueError as error:
            format_ok = False
            content_ok = False
            reason = f"JSON格式不通過：{error}"
        else:
            format_ok = True
            content_ok = _same_json(parsed, answers[item["id"]])
            reason = (
                "內容與結構正確"
                if content_ok
                else "JSON可解析，但內容、欄位或型別不符"
            )

        details.append({
            "id": item["id"],
            "format_pass": format_ok,
            "content_schema_pass": content_ok,
            "reason": reason,
        })

    format_count = sum(item["format_pass"] for item in details)
    content_count = sum(item["content_schema_pass"] for item in details)

    return {
        "question_count": 20,
        "format_pass_count": format_count,
        "format_pass_rate_percent": format_count / 20 * 100,
        "content_schema_pass_count": content_count,
        "content_schema_pass_rate_percent": content_count / 20 * 100,
        "details": sorted(details, key=lambda item: item["id"]),
    }

def create_test_images(source_dir, output_dir):
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)

    for image_id in range(1, 7):
        source_path = source_dir / f"{image_id}.jpg"

        if not source_path.is_file():
            raise FileNotFoundError(f"找不到原圖：{source_path}")

    for version in ["dark", "bright", "low_quality"]:
        (output_dir / version).mkdir(parents=True, exist_ok=True)

    for image_id in range(1, 7):
        with Image.open(source_dir / f"{image_id}.jpg") as img:
            image = ImageOps.exif_transpose(img).convert("RGB")

        ImageEnhance.Brightness(image).enhance(0.5).save(output_dir / "dark" / f"{image_id}.png")
        ImageEnhance.Brightness(image).enhance(1.5).save(output_dir / "bright" / f"{image_id}.png" )

        image.save(output_dir / "low_quality" / f"{image_id}.jpg", format="JPEG", quality=20, subsampling=2)

    return output_dir

def load_vlm_dpo_dataset(file_path, base_dir):
    base_dir = Path(base_dir)

    with open(file_path, "r", encoding="utf-8") as f: raw_data = json.load(f)

    ids = [item["id"] for item in raw_data]

    if len(ids) != 100 or set(ids) != set(range(1, 101)):
        raise ValueError("訓練資料須為100組，id為1～100且不重複")

    rows = []

    for item in raw_data:
        image_path = base_dir / item["image"]

        if not image_path.is_file():
            raise FileNotFoundError(f"找不到圖片：{image_path}")

        with Image.open(image_path) as img:
            image = ImageOps.exif_transpose(img).convert("RGB")

        buffer = BytesIO()
        image.save(buffer, format="PNG")

        rows.append({
            "image": {"bytes": buffer.getvalue(), "path": None},
            "prompt": [
                {"role": "system", "content": [{"type": "text", "text": "請根據圖片回答問題。"}]},
                {"role": "user", "content": [{"type": "image"}, {"type": "text", "text": item["prompt"]}]},
            ],
            "chosen": [
                {"role": "assistant", "content": [{"type": "text", "text": item["chosen"]}]}
            ],
            "rejected": [
                {"role": "assistant", "content": [{"type": "text", "text": item["rejected"]}]}
            ],
        })

    dataset = Dataset.from_list(rows)
    return dataset.cast_column("image", DatasetImage())

def create_vlm_dpo_trainer(model, processor, train_dataset, output_dir):
    model.config.use_cache = False

    target_modules = [
        name
        for name, module in model.named_modules()
        if name.endswith((".q_proj", ".v_proj"))
        and "visual" not in name
    ]

    if not target_modules:
        raise ValueError("沒有找到可加入LoRA的Q、V投影層")

    lora_config = LoraConfig(task_type="CAUSAL_LM", r=8, lora_alpha=16, lora_dropout=0.0, bias="none", target_modules=target_modules)
    training_args = DPOConfig(output_dir=str(output_dir), num_train_epochs=3, learning_rate=5e-5, per_device_train_batch_size=1,
                              gradient_accumulation_steps=8, beta=0.1, loss_type=["sigmoid"], max_length=None, fp16=True, bf16=False, 
                              optim="adamw_torch", gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False}, 
                              remove_unused_columns=False, dataloader_num_workers=0, logging_steps=1, save_strategy="epoch", 
                              save_total_limit=1, report_to="none", seed=42)

    return DPOTrainer(model=model, ref_model=None, args=training_args, train_dataset=train_dataset, 
                      processing_class=processor, peft_config=lora_config)