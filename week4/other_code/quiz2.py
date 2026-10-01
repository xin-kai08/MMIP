import torch
import re
import matplotlib.pyplot as plt
from torch import nn
from torch.utils.data import Dataset
from torch.nn.utils.rnn import pad_sequence, pack_padded_sequence
from collections import Counter
from pathlib import Path
from sklearn.metrics import accuracy_score, f1_score, confusion_matrix, ConfusionMatrixDisplay

def tokenize(text):
    text = re.sub(r"<[^>]*>", " ", text)
    text = text.lower()
    tokens = re.findall(r"[a-z]+(?:'[a-z]+)*", text)
    return tokens

def build_vocab(texts, max_vocab_size=20000):
    word_counts = Counter()

    for text in texts:
        tokens = tokenize(text)
        word_counts.update(tokens)

    vocab = {"<PAD>": 0, "<UNK>": 1}

    for word, count in word_counts.most_common(max_vocab_size - 2):
        vocab[word] = len(vocab)

    return vocab

def text_to_ids(text, vocab):
    tokens = tokenize(text)
    ids = [
        vocab.get(token, vocab["<UNK>"])
        for token in tokens
    ]
    return ids

class ReviewDataset(Dataset):
    def __init__(self, dataframe, vocab):
        self.reviews = dataframe["review"].tolist()
        self.labels = dataframe["sentiment"].map({
            "negative": 0,
            "positive": 1
        }).tolist()
        self.vocab = vocab

    def __len__(self):
        return len(self.reviews)

    def __getitem__(self, index):
        ids = text_to_ids(self.reviews[index], self.vocab)

        if not ids:
            ids = [self.vocab["<UNK>"]]

        token_ids = torch.tensor(ids, dtype=torch.long)
        label = torch.tensor(self.labels[index], dtype=torch.long)

        return token_ids, label
    
def collate_reviews(batch):
    sequences, labels = zip(*batch)

    lengths = torch.tensor(
        [len(sequence) for sequence in sequences],
        dtype=torch.long
    )

    padded_ids = pad_sequence(
        sequences,
        batch_first=True,
        padding_value=0
    )

    labels = torch.stack(labels)

    return padded_ids, lengths, labels

class RNNClassifier(nn.Module):
    def __init__(self, vocab_size, embedding_dim=128, hidden_size=128, dropout = 0.3):
        super().__init__()
        self.embedding = nn.Embedding(
            num_embeddings=vocab_size,
            embedding_dim=embedding_dim,
            padding_idx=0
        )

        self.rnn = nn.RNN(
            input_size=embedding_dim,
            hidden_size=hidden_size,
            batch_first=True
        )

        self.dropout = nn.Dropout(dropout)
        self.classifier = nn.Linear(hidden_size, 2)

    def forward(self, token_ids, lengths):
        embedded = self.embedding(token_ids)

        packed = pack_padded_sequence(embedded, lengths.cpu(), batch_first=True, enforce_sorted=False)

        _, hidden = self.rnn(packed)

        final_hidden = hidden[-1]
        final_hidden = self.dropout(final_hidden)
        logits = self.classifier(final_hidden)

        return logits
    
def train_one_epoch(model, loader, criterion, optimizer, device):
    model.train()

    total_loss = 0.0
    total_correct = 0
    total_samples = 0

    for token_ids, lengths, labels in loader:
        token_ids = token_ids.to(device)
        labels = labels.to(device)

        optimizer.zero_grad()

        logits = model(token_ids, lengths)
        loss = criterion(logits, labels)

        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()

        batch_size = labels.size(0)
        total_loss += loss.item() * batch_size
        total_correct += (logits.argmax(dim=1) == labels).sum().item()
        total_samples += batch_size

    return total_loss / total_samples, total_correct / total_samples


def evaluate(model, loader, criterion, device):
    model.eval()

    total_loss = 0.0
    total_samples = 0
    all_labels = []
    all_predictions = []

    with torch.no_grad():
        for token_ids, lengths, labels in loader:
            token_ids = token_ids.to(device)
            labels = labels.to(device)

            logits = model(token_ids, lengths)
            loss = criterion(logits, labels)
            predictions = logits.argmax(dim=1)

            batch_size = labels.size(0)
            total_loss += loss.item() * batch_size
            total_samples += batch_size
            
            all_labels.extend(labels.cpu().tolist())
            all_predictions.extend(predictions.cpu().tolist())

    return (total_loss / total_samples, accuracy_score(all_labels, all_predictions),
            f1_score(all_labels, all_predictions, labels=[0, 1], average="macro", zero_division=0),
            confusion_matrix(all_labels, all_predictions, labels=[0, 1]))

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
    
def plot_confusion_matrix(cm, result_path):
    result_path = Path(result_path)
    result_path.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(5, 4))

    display = ConfusionMatrixDisplay(
        confusion_matrix=cm,
        display_labels=["Negative", "Positive"]
    )

    display.plot(ax=ax, cmap="Blues", values_format="d")
    ax.set_title("Test confusion matrix")

    fig.tight_layout()
    fig.savefig(result_path / "confusion_matrix.png", dpi=150)
    plt.show()
    plt.close(fig)
    
class LSTMClassifier(nn.Module):
    def __init__(self, vocab_size, embedding_dim=128, hidden_size=128, dropout=0.3):
        super().__init__()
        self.embedding = nn.Embedding(
            num_embeddings=vocab_size,
            embedding_dim=embedding_dim,
            padding_idx=0
        )

        self.lstm = nn.LSTM(
            input_size=embedding_dim,
            hidden_size=hidden_size,
            batch_first=True
        )

        self.dropout = nn.Dropout(dropout)
        self.classifier = nn.Linear(hidden_size, 2)

    def forward(self, token_ids, lengths):
        embedded = self.embedding(token_ids)

        packed = pack_padded_sequence(embedded, lengths.cpu(), batch_first=True, enforce_sorted=False)

        _, (hidden, cell) = self.lstm(packed)

        final_hidden = self.dropout(hidden[-1])
        logits = self.classifier(final_hidden)

        return logits