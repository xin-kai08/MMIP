import torch
from pathlib import Path
from PIL import Image

@torch.inference_mode()
def generate_answer(question, image_path, model, processor):
    image_path = Path(image_path)
    
    if not image_path.is_file():
        raise FileNotFoundError(f"找不到圖片：{image_path.resolve()}")

    with Image.open(image_path) as img:
        image = img.convert("RGB")

    messages = [
        {"role": "system", "content": ("請根據圖片回答問題。"
                                       "除非題目另有指定，否則請使用繁體中文回答。")},
        {"role": "user", "content": [{"type": "image"}, {"type": "text", "text": question}]},
    ]

    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], images=[image], padding=True, return_tensors="pt").to(model.device)

    outputs = model.generate(**inputs, max_new_tokens=512, do_sample=False)
    generated_ids = outputs[:, inputs["input_ids"].shape[1]:]
    response = processor.batch_decode(generated_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]

    return response.strip()

@torch.inference_mode()
def generate_answer_gemma(question, image_path, model, processor):
    image_path = Path(image_path)

    with Image.open(image_path) as img:
        image = img.convert("RGB")

    messages = [
        {"role": "system", "content": [{"type": "text", "text": ("請根據圖片回答問題。"
                                                                 "除非題目另有指定，否則請使用繁體中文回答。")}]},
        {"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": question}]},
    ]

    inputs = processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=True,
                                           return_dict=True, return_tensors="pt").to(model.device)

    if "pixel_values" in inputs:
        inputs["pixel_values"] = inputs["pixel_values"].to(model.dtype)

    outputs = model.generate(**inputs, max_new_tokens=512, do_sample=False)
    generated_ids = outputs[:, inputs["input_ids"].shape[1]:]
    response = processor.batch_decode(generated_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]

    return response.strip()