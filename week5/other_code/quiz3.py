import torch
import re
import torch.nn as nn
import pandas as pd
from sklearn.model_selection import train_test_split
from pathlib import Path
from PIL import Image
from torch.utils.data import Dataset
from transformers import CLIPModel, GPT2LMHeadModel
from nltk.translate.bleu_score import corpus_bleu

def prepare_splits(caption_path, random_state=42):
    captions = pd.read_csv(caption_path)

    duplicate_to_original = {"3050606344_af711c726c.jpg": "2851198725_37b6027625.jpg"}

    group_ids = captions["image"].replace(duplicate_to_original)
    unique_groups = sorted(group_ids.unique())

    train_groups, remaining_groups = train_test_split(unique_groups, test_size=0.2, random_state=random_state)
    val_groups, test_groups = train_test_split(remaining_groups, test_size=0.5, random_state=random_state)

    train_df = captions[group_ids.isin(train_groups)].reset_index(drop=True)
    val_df = captions[group_ids.isin(val_groups)].reset_index(drop=True)
    test_df = captions[group_ids.isin(test_groups)].reset_index(drop=True)

    return train_df, val_df, test_df

class FlickrCaptionDataset(Dataset):
    def __init__(self, dataframe, image_root, image_processor, tokenizer, max_length=64):
        self.dataframe = dataframe.reset_index(drop=True).copy()
        self.image_root = Path(image_root)
        self.image_processor = image_processor
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self):
        return len(self.dataframe)

    def __getitem__(self, index):
        row = self.dataframe.iloc[index]
        image_path = self.image_root / row["image"]
        caption = row["caption"]

        with Image.open(image_path) as img:
            image = img.convert("RGB")

        pixel_values = self.image_processor(images=image, return_tensors="pt")["pixel_values"].squeeze(0)

        token_ids = self.tokenizer(caption, add_special_tokens=False, truncation=True, max_length=self.max_length - 1,)["input_ids"]
        token_ids.append(self.tokenizer.eos_token_id)

        valid_length = len(token_ids)
        padding_length = self.max_length - valid_length
        input_ids = torch.tensor(token_ids + [self.tokenizer.pad_token_id] * padding_length, dtype=torch.long)
        attention_mask = torch.tensor([1] * valid_length + [0] * padding_length, dtype=torch.long)

        labels = input_ids.clone()
        labels[attention_mask == 0] = -100

        return {"pixel_values": pixel_values, "input_ids": input_ids, "attention_mask": attention_mask, "labels": labels}

class CLIPCaptionModel(nn.Module):
    def __init__(self, clip_model_name="openai/clip-vit-base-patch32", text_model_name="gpt2", prefix_length=10):
        super().__init__()
        self.prefix_length = prefix_length
        
        self.clip = CLIPModel.from_pretrained(clip_model_name)
        self.decoder = GPT2LMHeadModel.from_pretrained(text_model_name)

        image_dim = self.clip.config.projection_dim
        self.text_dim = self.decoder.config.n_embd

        self.projection = nn.Sequential(
            nn.Linear(image_dim, self.text_dim),
            nn.Tanh(),
            nn.Linear(self.text_dim, prefix_length * self.text_dim),
        )

        self.clip.requires_grad_(False)
        self.clip.eval()

        self.decoder.config.pad_token_id = (self.decoder.config.eos_token_id)

    def train(self, mode=True):
        super().train(mode)

        self.clip.eval()
        return self

    def encode_image(self, pixel_values):
        with torch.no_grad():
            image_features = self.clip.get_image_features(pixel_values=pixel_values)

        prefix = self.projection(image_features)
        return prefix.reshape(pixel_values.size(0), self.prefix_length, self.text_dim)

    def forward(self, pixel_values, input_ids, attention_mask, labels=None ):
        image_prefix = self.encode_image(pixel_values)
        text_embeddings = self.decoder.get_input_embeddings()(input_ids)
        inputs_embeds = torch.cat([image_prefix, text_embeddings], dim=1)

        prefix_mask = attention_mask.new_ones((input_ids.size(0), self.prefix_length))
        full_attention_mask = torch.cat([prefix_mask, attention_mask], dim=1)

        full_labels = None

        if labels is not None:
            prefix_labels = labels.new_full((input_ids.size(0), self.prefix_length), -100)
            full_labels = torch.cat([prefix_labels, labels], dim=1)

        return self.decoder(inputs_embeds=inputs_embeds, attention_mask=full_attention_mask, labels=full_labels, use_cache=False)
    
from tqdm.auto import tqdm


def train_one_epoch(model, loader, optimizer, device):
    model.train()
    total_loss = 0.0
    total_tokens = 0

    for batch in tqdm(loader, desc="Train", leave=False):
        batch = {
            name: tensor.to(device)
            for name, tensor in batch.items()
        }

        optimizer.zero_grad(set_to_none=True)
        outputs = model(**batch)
        loss = outputs.loss

        loss.backward()
        torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], max_norm=1.0)
        optimizer.step()

        token_count = (batch["labels"] != -100).sum().item()
        total_loss += loss.item() * token_count
        total_tokens += token_count

    return total_loss / total_tokens

@torch.no_grad()
def evaluate(model, loader, device):
    model.eval()

    total_loss = 0.0
    total_tokens = 0

    for batch in tqdm(loader, desc="Val", leave=False):
        batch = {
            name: tensor.to(device)
            for name, tensor in batch.items()
        }

        outputs = model(**batch)

        token_count = (batch["labels"] != -100).sum().item()
        total_loss += outputs.loss.item() * token_count
        total_tokens += token_count

    return total_loss / total_tokens

@torch.no_grad()
def generate_caption(model, image, image_processor, tokenizer, device, max_new_tokens=64):
    model.eval()
    
    pixel_values = image_processor(images=image, return_tensors="pt")["pixel_values"].to(device)
    inputs_embeds = model.encode_image(pixel_values)

    generated_ids = []

    for _ in range(max_new_tokens):
        attention_mask = torch.ones(inputs_embeds.shape[:2], dtype=torch.long, device=device)

        outputs = model.decoder(inputs_embeds=inputs_embeds, attention_mask=attention_mask, use_cache=False)
        next_token = outputs.logits[:, -1, :].argmax(dim=-1)
        token_id = next_token.item()

        if token_id == tokenizer.eos_token_id:
            break

        generated_ids.append(token_id)

        next_embedding = model.decoder.get_input_embeddings()(next_token.unsqueeze(1))
        inputs_embeds = torch.cat([inputs_embeds, next_embedding], dim=1)

    return tokenizer.decode(generated_ids, skip_special_tokens=True).strip()

def tokenize(text):
    text = text.lower()
    tokens = re.findall(r"[a-z]+(?:'[a-z]+)*", text)
    return tokens

def evaluate_bleu(model, df, image_dir, tokenizer, image_processor, device):
    image_dir = Path(image_dir)

    all_references = []
    all_predictions = []
    results = []

    groups = df.groupby("image", sort=False)

    for index, (image_name, group) in enumerate(groups):
        image_path = image_dir / image_name

        with Image.open(image_path) as img:
            image = img.convert("RGB")

        prediction = generate_caption(model, image, image_processor, tokenizer, device)
        reference_captions = group["caption"].tolist()

        reference_tokens = [
            tokenize(caption)
            for caption in reference_captions
        ]
        prediction_tokens = prediction.split()

        all_references.append(reference_tokens)
        all_predictions.append(prediction_tokens)

        results.append({
            "image": image_name,
            "prediction": prediction,
            "references": reference_captions,
        })

        if (index + 1) % 100 == 0:
            print(f"已完成 {index + 1}/{len(groups)} 張圖片")

    weights = {
        "BLEU-1": (1.0,),
        "BLEU-2": (0.5, 0.5),
        "BLEU-3": (1 / 3, 1 / 3, 1 / 3),
        "BLEU-4": (0.25, 0.25, 0.25, 0.25),
    }

    scores = {
        name: corpus_bleu(
            all_references, all_predictions, weights=weight
        )
        for name, weight in weights.items()
    }

    return scores, results