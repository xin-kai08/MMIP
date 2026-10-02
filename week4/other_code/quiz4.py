import torch
import re
import timm
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from collections import Counter
from pathlib import Path
from PIL import Image
from torch.utils.data import Dataset
from torchvision import transforms
from torch.nn.utils.rnn import pad_sequence
from torch import nn
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

def tokenize(text):
    text = text.lower()
    tokens = re.findall(r"[a-z]+(?:'[a-z]+)*", text)
    return tokens

def build_vocab(captions, max_vocab_size=10000):
    word_counts = Counter()

    for caption in captions:
        word_counts.update(tokenize(caption))

    vocab = {
        "<PAD>": 0,
        "<UNK>": 1,
        "<BOS>": 2,
        "<EOS>": 3,
    }

    for word, count in word_counts.most_common(max_vocab_size - 4):
        vocab[word] = len(vocab)

    return vocab

def text_to_ids(text, vocab):
    tokens = tokenize(text)

    ids = [vocab["<BOS>"]]

    for token in tokens:
        ids.append(vocab.get(token, vocab["<UNK>"]))

    ids.append(vocab["<EOS>"])

    return ids

def create_transform():
    return transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225]
        ),
    ])

class CaptionDataset(Dataset):
    def __init__(self, df, image_dir, vocab, transform):
        self.image_names = df["image"].tolist()
        self.captions = df["caption"].tolist()
        self.image_dir = Path(image_dir)
        self.vocab = vocab
        self.transform = transform

    def __len__(self):
        return len(self.captions)

    def __getitem__(self, index):
        image_path = self.image_dir / self.image_names[index]

        with Image.open(image_path) as img:
            image = self.transform(img.convert("RGB"))

        ids = text_to_ids(self.captions[index], self.vocab)
        caption_ids = torch.tensor(ids, dtype=torch.long)

        return image, caption_ids
    
def collate_fn(batch):
    images, captions = zip(*batch)

    images = torch.stack(images)

    captions = pad_sequence(captions, batch_first=True, padding_value=0)

    return images, captions

class CaptionModel(nn.Module):
    def __init__(self, vocab_size, embedding_dim=256, hidden_size=256, dropout=0.3):
        super().__init__()
        self.encoder = timm.create_model("vit_tiny_patch16_224", pretrained=True, num_classes=0)

        for parameter in self.encoder.parameters():
            parameter.requires_grad = False

        feature_dim = self.encoder.num_features

        self.feature_to_hidden = nn.Linear(feature_dim, hidden_size)
        self.feature_to_cell = nn.Linear(feature_dim, hidden_size)

        self.embedding = nn.Embedding(
            num_embeddings=vocab_size,
            embedding_dim=embedding_dim,
            padding_idx=0
        )

        self.dropout = nn.Dropout(dropout)

        self.lstm = nn.LSTM(
            input_size=embedding_dim,
            hidden_size=hidden_size,
            num_layers=1,
            batch_first=True
        )

        self.output_layer = nn.Linear(hidden_size, vocab_size)

    def forward(self, images, input_ids):
        self.encoder.eval()

        with torch.no_grad():
            features = self.encoder(images)

        hidden = self.feature_to_hidden(features).unsqueeze(0)
        cell = self.feature_to_cell(features).unsqueeze(0)

        embeddings = self.dropout(self.embedding(input_ids))

        outputs, _ = self.lstm(embeddings, (hidden, cell))

        logits = self.output_layer(self.dropout(outputs))

        return logits
    
def train_one_epoch(model, loader, criterion, optimizer, device):
    model.train()

    total_loss = 0.0
    total_correct = 0
    total_tokens = 0

    for images, captions in loader:
        images = images.to(device)
        captions = captions.to(device)

        input_ids = captions[:, :-1]
        targets = captions[:, 1:]

        optimizer.zero_grad()
        logits = model(images, input_ids)
        loss = criterion(logits.reshape(-1, logits.size(-1)), targets.reshape(-1))

        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()

        predictions = logits.argmax(dim=-1)
        mask = targets != 0

        token_count = mask.sum().item()

        total_loss += loss.item() * token_count
        total_correct += ((predictions == targets) & mask).sum().item()
        total_tokens += token_count

    return total_loss / total_tokens, total_correct / total_tokens
    
def evaluate(model, loader, criterion, device):
    model.eval()

    total_loss = 0.0
    total_correct = 0
    total_tokens = 0

    with torch.no_grad():
        for images, captions in loader:
            images = images.to(device)
            captions = captions.to(device)

            input_ids = captions[:, :-1]
            targets = captions[:, 1:]

            logits = model(images, input_ids)
            loss = criterion(logits.reshape(-1, logits.size(-1)), targets.reshape(-1))

            predictions = logits.argmax(dim=-1)
            mask = targets != 0

            token_count = mask.sum().item()

            total_loss += loss.item() * token_count
            total_correct += ((predictions == targets) & mask).sum().item()
            total_tokens += token_count

    return total_loss / total_tokens, total_correct / total_tokens

def plot_history(history, result_path):
    result_path = Path(result_path)
    result_path.mkdir(parents=True, exist_ok=True)

    epochs = range(1, len(history["train_loss"]) + 1)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))

    axes[0].plot(epochs, history["train_loss"], label="Train")
    axes[0].plot(epochs, history["val_loss"], label="Validation")
    axes[0].set_xlabel("Epoch")
    axes[0].set_ylabel("Loss")
    axes[0].set_title("loss curve")
    axes[0].legend()

    axes[1].plot(epochs, history["train_acc"], label="Train")
    axes[1].plot(epochs, history["val_acc"], label="Validation")
    axes[1].set_xlabel("Epoch")
    axes[1].set_ylabel("Accuracy")
    axes[1].set_title("accuracy curve")
    axes[1].legend()

    fig.tight_layout()
    fig.savefig(result_path / "training_curves.png", dpi=150)
    plt.show()
    plt.close(fig)
    
def generate_caption(model, image, vocab, device, max_length=30):
    model.eval()

    id_to_word = {
        token_id: word
        for word, token_id in vocab.items()
    }

    generated_ids = []

    with torch.no_grad():
        image = image.unsqueeze(0).to(device)

        features = model.encoder(image)

        hidden = model.feature_to_hidden(features).unsqueeze(0)
        cell = model.feature_to_cell(features).unsqueeze(0)

        current_token = torch.tensor([[vocab["<BOS>"]]], dtype=torch.long, device=device)

        for _ in range(max_length):
            embedding = model.embedding(current_token)

            output, (hidden, cell) = model.lstm(embedding, (hidden, cell))

            logits = model.output_layer(output[:, -1, :])

            logits[:, vocab["<PAD>"]] = float("-inf")
            logits[:, vocab["<BOS>"]] = float("-inf")

            next_id = logits.argmax(dim=-1).item()

            if next_id == vocab["<EOS>"]:
                break

            generated_ids.append(next_id)

            current_token = torch.tensor([[next_id]], dtype=torch.long, device=device)

    words = [id_to_word[token_id] for token_id in generated_ids]

    return " ".join(words)

def evaluate_bleu(model, df, image_dir, vocab, transform, device):
    image_dir = Path(image_dir)

    all_references = []
    all_predictions = []
    results = []

    groups = df.groupby("image", sort=False)

    for index, (image_name, group) in enumerate(groups):
        image_path = image_dir / image_name

        with Image.open(image_path) as img:
            image = transform(img.convert("RGB"))

        prediction = generate_caption(model, image, vocab, device)

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
            "references": reference_captions
        })

        if (index + 1) % 100 == 0:
            print(f"已完成 {index + 1}/{len(groups)} 張圖片")

    weights = {
        "BLEU-1": (1.0,),
        "BLEU-2": (0.5, 0.5),
        "BLEU-3": (1 / 3, 1 / 3, 1 / 3),
        "BLEU-4": (0.25, 0.25, 0.25, 0.25)
    }

    scores = {}

    for name, weight in weights.items():
        scores[name] = corpus_bleu(all_references, all_predictions, weights=weight)

    return scores, results