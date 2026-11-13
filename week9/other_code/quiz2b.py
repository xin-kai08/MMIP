import torch
import hashlib
import json
import time
from pathlib import Path
from PIL import Image
from torch.utils.data import Dataset
from transformers import Trainer, TrainingArguments, set_seed
from peft import LoraConfig, PeftModel, get_peft_model

from . import quiz2a as a

PROJECT_ROOT = a.PROJECT_ROOT
TRAIN_PATH = PROJECT_ROOT / "dataset/quiz2/SFT/train.json"

def file_hash(path):
    """檢查訓練圖片是否與Benchmark圖片完全相同。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_training_data(validator):
    """檢查SFT資料、圖片與標準JSON答案。"""
    with TRAIN_PATH.open("r", encoding="utf-8") as f:
        rows = json.load(f)

    if not isinstance(rows, list) or not rows:
        raise ValueError("train.json必須是非空陣列")

    ids = [row["id"] for row in rows]

    if len(ids) != len(set(ids)):
        raise ValueError("SFT資料包含重複id")

    # Benchmark只用於檢查資料隔離，不拿來訓練
    benchmark, _, _ = a.load_assets()
    benchmark_hashes = {
        file_hash(PROJECT_ROOT / case["image"])
        for case in benchmark
    }

    for row in rows:
        image_path = PROJECT_ROOT / row["image"]

        if not image_path.is_file():
            raise FileNotFoundError(image_path)

        with Image.open(image_path) as img:
            img.verify()

        if file_hash(image_path) in benchmark_hashes:
            raise ValueError(
                f"{row['id']}使用了Benchmark的相同圖片，"
                "請保持訓練與測試資料分開。"
            )

        if not isinstance(row["text"], str):
            raise ValueError(f"{row['id']}的text必須是字串")

        for message in row.get("history", []):
            if message["role"] not in ("user", "assistant"):
                raise ValueError(
                    f"{row['id']}的history角色不正確"
                )

            if not isinstance(message["content"], str):
                raise ValueError(
                    f"{row['id']}的history內容必須是字串"
                )

        # 標準答案必須符合我們的輸出Spec
        validator.validate(row["output"])

    return rows

class SFTDataset(Dataset):
    def __init__(self, rows):
        self.rows = rows

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        return self.rows[index]


class SFTCollator:
    """
    組合圖文輸入與標準答案。
    只計算標準答案部分的loss，不訓練模型背誦輸入。
    """

    def __init__(self, processor, system_prompt):
        self.processor = processor
        self.system_prompt = system_prompt

    def __call__(self, examples):
        # 先以batch size 1控制V100的記憶體用量
        if len(examples) != 1:
            raise ValueError("目前設定只支援batch size 1")

        row = examples[0]

        with Image.open(PROJECT_ROOT / row["image"]) as img:
            image = img.convert("RGB")

        messages = [
            {
                "role": "system",
                "content": self.system_prompt,
            }
        ]

        # 先前顯示給使用者的文字對話
        messages.extend(row.get("history", []))

        # 本輪圖片與使用者文字
        messages.append({
            "role": "user",
            "content": [{"type": "image"}, {"type": "text", "text": row["text"]}],
        })

        # Prompt結尾為assistant開始回答的位置
        prompt = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

        answer = json.dumps(row["output"], ensure_ascii=False)

        eos = self.processor.tokenizer.eos_token

        if eos is None:
            raise ValueError("Tokenizer沒有設定eos_token")

        full_text = prompt + answer + eos

        # 不截斷，避免切掉圖片token或標準答案
        prompt_inputs = self.processor(text=[prompt], images=[image], padding=False, return_tensors="pt")

        full_inputs = self.processor(text=[full_text], images=[image], padding=False, return_tensors="pt")

        prompt_length = prompt_inputs["input_ids"].shape[1]

        # 確認標準答案確實接在相同的Prompt後面
        if not torch.equal(
            full_inputs["input_ids"][:, :prompt_length],
            prompt_inputs["input_ids"],
        ):
            raise ValueError(
                f"{row['id']}的Prompt與答案token邊界不一致"
            )

        labels = full_inputs["input_ids"].clone()

        # -100表示不計算這些位置的訓練loss
        labels[:, :prompt_length] = -100
        labels[full_inputs["attention_mask"] == 0] = -100

        if not (labels != -100).any():
            raise ValueError(
                f"{row['id']}沒有可訓練的答案token"
            )

        full_inputs["labels"] = labels
        return full_inputs

def train_sft(epochs=3, learning_rate=1e-4):
    """從原始Qwen模型開始，訓練LoRA adapter。"""
    set_seed(42)

    _, schema, validator = a.load_assets()
    rows = load_training_data(validator)
    system_prompt = a.build_prompt(schema)

    print("SFT樣本數：", len(rows))
    print("不同圖片數：", len({row["image"] for row in rows}))

    model, processor = a.load_model()
    model.config.use_cache = False

    # 只在語言模型的Attention投影層新增LoRA
    lora_config = LoraConfig(task_type="CAUSAL_LM", r=8, lora_alpha=16, lora_dropout=0.05, 
                             target_modules=["q_proj",
                                             "k_proj",
                                             "v_proj",
                                             "o_proj"], bias="none")

    model = get_peft_model(model, lora_config)

    # V100使用FP16混合精度；
    # 可訓練的LoRA參數保留FP32供梯度縮放使用
    for parameter in model.parameters():
        if parameter.requires_grad:
            parameter.data = parameter.data.float()

    model.print_trainable_parameters()

    collator = SFTCollator(processor, system_prompt)

    # 在正式訓練前，先檢查一筆資料能否轉換
    sample = collator([rows[0]])

    print("第一筆輸入token數：", sample["input_ids"].shape[1])
    print(
        "第一筆答案token數：",
        int((sample["labels"] != -100).sum()),
    )

    del sample

    run_dir = (PROJECT_ROOT / "result/quiz2" / f"B_sft_training_{time.time_ns()}")
    adapter_dir = run_dir / "adapter"

    args = TrainingArguments(output_dir=str(run_dir), num_train_epochs=epochs, per_device_train_batch_size=1,
                             gradient_accumulation_steps=4, learning_rate=learning_rate, warmup_ratio=0.1, weight_decay=0.0,
                             fp16=True, bf16=False, gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
                             optim="adamw_torch", logging_steps=1, save_strategy="no", report_to="none", remove_unused_columns=False,
                             dataloader_num_workers=0, dataloader_pin_memory=False, label_names=["labels"], seed=42)

    trainer = Trainer(model=model, args=args, train_dataset=SFTDataset(rows), data_collator=collator, processing_class=processor)

    # 使用模型原本的loss計算方式
    trainer.model_accepts_loss_kwargs = False

    print("開始SFT＋LoRA訓練")
    train_result = trainer.train()

    # 儲存LoRA權重與Processor
    trainer.save_model(str(adapter_dir))
    processor.save_pretrained(str(adapter_dir))

    training_report = {
        "method": "B_sft",
        "base_model": a.MODEL_ID,
        "train_file": str(TRAIN_PATH),
        "train_file_sha256": file_hash(TRAIN_PATH),
        "sample_count": len(rows),
        "image_count": len({row["image"] for row in rows}),
        "epochs": epochs,
        "learning_rate": learning_rate,
        "lora_r": 8,
        "lora_alpha": 16,
        "lora_dropout": 0.05,
        "seed": 42,
        "system_prompt": system_prompt,
        "metrics": train_result.metrics,
        "log_history": trainer.state.log_history,
        "adapter_dir": str(adapter_dir),
    }

    a.save_report(training_report, run_dir / "training_report.json")

    # 訓練結束，切回推論設定
    model.gradient_checkpointing_disable()
    model.config.use_cache = True
    model.eval()

    print("訓練完成")
    print("LoRA儲存位置：", adapter_dir)

    return model, processor, adapter_dir


def load_sft_model(adapter_dir):
    """之後重開Notebook時，載入已訓練好的LoRA。"""
    base_model, processor = a.load_model()

    model = PeftModel.from_pretrained(base_model, str(adapter_dir), is_trainable=False)

    model.config.use_cache = True
    model.eval()

    return model, processor


def run_benchmark(model, processor, cases, schema, validator, adapter_dir):
    """使用A的相同評估流程，記錄為實驗B。"""
    report, result_path = a.run_benchmark(model, processor, cases, schema, validator, method="B_sft")

    report["adapter_dir"] = str(adapter_dir)
    a.save_report(report, result_path)

    return report, result_path