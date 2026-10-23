import torch
import json
import math
from pathlib import Path
from datasets import Dataset
from peft import LoraConfig
from trl import DPOConfig, DPOTrainer

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