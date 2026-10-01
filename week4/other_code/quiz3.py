import timm
import torch
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from sklearn.model_selection import train_test_split
from timm.data import resolve_model_data_config, create_transform
from PIL import Image
from torch.utils.data import Dataset
from sklearn.metrics import accuracy_score, f1_score, roc_curve, auc, roc_auc_score

def prepare_splits(data_dir, random_state=42):
    data_dir = Path(data_dir)
    class_to_idx = {"rock": 0, "paper": 1, "scissors": 2}
    samples = []

    for class_name, label in class_to_idx.items():
        folder = data_dir / class_name

        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in [".jpg", ".jpeg", ".png"]:
                samples.append((str(path), label))

    labels = [label for path, label in samples]
    train_samples, remaining_samples = train_test_split(samples, test_size=0.2, stratify=labels, random_state=random_state)

    remaining_labels = [label for path, label in remaining_samples]
    val_samples, test_samples = train_test_split(remaining_samples, test_size=0.5, stratify=remaining_labels, random_state=random_state)

    return train_samples, val_samples, test_samples, class_to_idx

def create_vit():
    model = timm.create_model("vit_tiny_patch16_224", pretrained=True, num_classes=3)

    config = resolve_model_data_config(model)

    train_transform = create_transform( **config, is_training=True, scale=(0.8, 1.0), hflip=0.5, color_jitter=0.2)
    eval_transform = create_transform( **config, is_training=False)

    return model, train_transform, eval_transform

class ImageDataset(Dataset):
    def __init__(self, samples, transform):
        self.samples = samples
        self.transform = transform

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, index):
        path, label = self.samples[index]

        with Image.open(path) as img:
            image = self.transform(img.convert("RGB"))

        return image, label
    
def train_one_epoch(model, loader, criterion, optimizer, device):
    model.eval()
    model.get_classifier().train()

    total_loss = 0.0
    total_correct = 0
    total_samples = 0

    for images, labels in loader:
        images = images.to(device)
        labels = labels.to(device)

        optimizer.zero_grad()

        logits = model(images)
        loss = criterion(logits, labels)

        loss.backward()
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
    all_probabilities = []

    with torch.no_grad():
        for images, labels in loader:
            images = images.to(device)
            labels = labels.to(device)

            logits = model(images)
            loss = criterion(logits, labels)
            predictions = logits.argmax(dim=1)
            probabilities = torch.softmax(logits, dim=1)

            batch_size = labels.size(0)
            total_loss += loss.item() * batch_size
            total_samples += batch_size
            
            all_labels.extend(labels.cpu().tolist())
            all_predictions.extend(predictions.cpu().tolist())
            all_probabilities.extend(probabilities.cpu().tolist())

    return (total_loss / total_samples, accuracy_score(all_labels, all_predictions),
            f1_score(all_labels, all_predictions, labels=[0, 1, 2], average="macro", zero_division=0),
            roc_auc_score(all_labels, all_probabilities, labels=[0, 1, 2], multi_class="ovr", average="macro"), all_labels, all_probabilities)
    
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
    
def plot_roc(all_labels, all_probabilities, result_path):
    result_path = Path(result_path)
    result_path.mkdir(parents=True, exist_ok=True)

    labels = np.asarray(all_labels)
    probabilities = np.asarray(all_probabilities)
    class_names = ["Rock", "Paper", "Scissors"]

    fig, ax = plt.subplots(figsize=(6, 5))

    for class_id, name in enumerate(class_names):
        binary_labels = (labels == class_id).astype(int)

        fpr, tpr, _ = roc_curve(binary_labels, probabilities[:, class_id])

        class_auc = auc(fpr, tpr)
        ax.plot(fpr, tpr, label=f"{name}: AUC={class_auc:.4f}")

    macro_auc = roc_auc_score(labels, probabilities,labels=[0, 1, 2], multi_class="ovr", average="macro")

    ax.plot([0, 1.02], [0, 1.02], "--", color="gray")
    ax.set_xlabel("False Positive Rate")
    ax.set_ylabel("True Positive Rate")
    ax.set_title(f"Test ROC curves — Macro-AUC={macro_auc:.4f}")
    ax.legend()

    fig.tight_layout()
    fig.savefig(result_path / "roc_curves.png", dpi=150)
    plt.show()
    plt.close(fig)
    
def create_resnet():
    model = timm.create_model("resnet18", pretrained=True, num_classes=3)

    config = resolve_model_data_config(model)

    train_transform = create_transform(**config, is_training=True, scale=(0.8, 1.0), hflip=0.5, color_jitter=0.2)
    eval_transform = create_transform(**config, is_training=False)

    return model, train_transform, eval_transform

