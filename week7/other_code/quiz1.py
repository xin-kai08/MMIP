import torch
import threading

def generate_answer(question, model, tokenizer, use_prompt_engineering=False):
    messages = [
        {"role": "system", "content": "除非題目另有指定，否則請使用繁體中文回答。"},
        {"role": "user", "content": question},
    ]
    
    if use_prompt_engineering:
        messages.extend([
            {"role": "user", "content": ("# 任務\n"
                                         "回答問題，遵守指定的語言與輸出格式。\n\n"
                                         "## 問題\n"
                                         "一本筆記本35元，買3本共多少元？")},
            {"role": "assistant", "content": "35×3＝105元。"},
            {"role": "user", "content": ("# 任務\n"
                                         "回答問題，遵守指定的語言與輸出格式。\n\n"
                                         "## 問題\n"
                                         "只輸出合法JSON物件，不要加說明或Markdown標記。"
                                         "物件只能包含city欄位，值為字串臺南。")},
            {"role": "assistant", "content": '{"city":"臺南"}'}
        ])

        prompt = ("# 任務\n"
                  "回答問題，遵守指定的語言與輸出格式。\n\n"
                  "## 問題\n"
                  f"{question}")
    else:
        prompt = question

    messages.append({"role": "user","content": prompt})
    
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt", add_special_tokens=False).to(model.device)

    with torch.inference_mode():
        outputs = model.generate(**inputs, max_new_tokens=512, do_sample=False, pad_token_id=tokenizer.eos_token_id)
    new_tokens = outputs[0, inputs["input_ids"].shape[1]:]

    return tokenizer.decode(new_tokens, skip_special_tokens=True)

def answer_with_memory(question, model, tokenizer, use_prompt_engineering=False):
    device = model.device
    samples = []
    stop_event = threading.Event()

    def monitor():
        while not stop_event.is_set():
            samples.append(torch.cuda.memory_allocated(device))
            stop_event.wait(0.05)

    torch.cuda.synchronize(device)
    torch.cuda.reset_peak_memory_stats(device)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()

    try:
        response = generate_answer(question=question, model=model, tokenizer=tokenizer, use_prompt_engineering=use_prompt_engineering)
    finally:
        torch.cuda.synchronize(device)
        stop_event.set()
        thread.join()

    return response, samples, torch.cuda.max_memory_allocated(device)


