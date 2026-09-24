import torch
import torch.nn as nn
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from statistics import mean, stdev
from torch.utils.data import DataLoader
from PIL import Image
from torch.utils.data import Dataset
from sklearn.metrics import precision_recall_fscore_support, roc_curve, auc, f1_score
from torchvision.models import resnet18, ResNet18_Weights

class PlainCNN(nn.Module):
    def __init__(self, num_classes):
        super().__init__()
        self.feature = nn.Sequential(
            # 224 * 224 * 3
            nn.Conv2d(3, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d(2),
            # 112 * 112 * 32
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.MaxPool2d(2),
            # 56 * 56 * 64
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(),
            nn.MaxPool2d(2),
            # 28 * 28 * 128
            nn.Conv2d(128, 256, kernel_size=3, padding=1),
            nn.BatchNorm2d(256),
            nn.ReLU(),
            nn.MaxPool2d(2)
            # 14 * 14 * 256
        )
        self.classifier = nn.Sequential(
            nn.AdaptiveAvgPool2d(1),
            nn.Flatten(),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(128, num_classes)
        )
    def forward(self, x):
        x = self.feature(x)
        return self.classifier(x)
    
class VegetableDataset(Dataset):
    def __init__(self, records, transform):
        self.records = records
        self.transform = transform

    def __len__(self):
        return len(self.records)

    def __getitem__(self, index):
        image_path, label = self.records[index]

        with Image.open(image_path) as image:
            image = image.convert("RGB")
            image = self.transform(image)

        return image, label
    
def run_epoch(model, loader, criterion, device, optimizer=None):
    is_train = optimizer is not None
    if is_train:
        model.train()
    else:
        model.eval()

    total_loss = 0.0
    total_correct = 0
    total_samples = 0

    for images, labels in loader:
        images = images.to(device)
        labels = labels.to(device)

        if is_train:
            optimizer.zero_grad()

        with torch.set_grad_enabled(is_train):
            logits = model(images)
            loss = criterion(logits, labels)

            if is_train:
                loss.backward()
                optimizer.step()

        batch_size = labels.size(0)
        total_loss += loss.item() * batch_size
        total_correct += (logits.argmax(dim=1) == labels).sum().item()
        total_samples += batch_size

    return {
        "loss": total_loss / total_samples,
        "acc": total_correct / total_samples,
    }

def train_five_folds(model_class, train_records, folds, categories, transform, device,
                     num_epochs, batch_size, learning_rate, checkpoint_dir):
    checkpoint_dir = Path(checkpoint_dir)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    fold_results = []

    for fold_no, (train_idx, val_idx) in enumerate(folds, start=1):
        print(f"\n========== Fold {fold_no} ==========")

        fold_train_records = [train_records[i] for i in train_idx]
        fold_val_records = [train_records[i] for i in val_idx]

        train_loader = DataLoader(VegetableDataset(fold_train_records, transform), batch_size=batch_size, shuffle=True, num_workers=2)
        val_loader = DataLoader(VegetableDataset(fold_val_records, transform), batch_size=batch_size, shuffle=False, num_workers=2)

        model = model_class(num_classes=len(categories)).to(device)
        criterion = nn.CrossEntropyLoss()
        optimizer = torch.optim.Adam((p for p in model.parameters() if p.requires_grad), lr=learning_rate)

        history = {
            "train_loss": [],
            "val_loss": [],
            "train_acc": [],
            "val_acc": [],
        }
        best_result = None

        for epoch in range(1, num_epochs + 1):
            train_metrics = run_epoch(model, train_loader, criterion, device, optimizer)
            val_metrics = run_epoch(model, val_loader, criterion, device)

            history["train_loss"].append(train_metrics["loss"])
            history["val_loss"].append(val_metrics["loss"])
            history["train_acc"].append(train_metrics["acc"])
            history["val_acc"].append(val_metrics["acc"])

            print(
                f"Epoch {epoch:02d} | "
                f"Train loss {train_metrics['loss']:.4f}, "
                f"acc {train_metrics['acc']:.4f} | "
                f"Val loss {val_metrics['loss']:.4f}, "
                f"acc {val_metrics['acc']:.4f}"
            )

            if best_result is None or val_metrics["loss"] < best_result["val_loss"]:
                checkpoint_path = checkpoint_dir / f"fold_{fold_no}_best.pt"
                best_result = {
                    "fold": fold_no,
                    "epoch": epoch,
                    "val_loss": val_metrics["loss"],
                    "val_acc": val_metrics["acc"],
                    "checkpoint": str(checkpoint_path),
                }
                torch.save(model.state_dict(), checkpoint_path)

        plot_history(history, fold_no)
        fold_results.append(best_result)

        print(
            f"Fold {fold_no} 最佳：Epoch {best_result['epoch']}, "
            f"Val loss {best_result['val_loss']:.4f}, "
            f"Val acc {best_result['val_acc']:.4f}"
        )

    print("\n========== 五折最佳驗證結果 ==========")
    print(f"{'Fold':<6}{'Epoch':<7}{'Val loss':<10}{'Val acc'}")

    for result in fold_results:
        print(
            f"{result['fold']:<6}"
            f"{result['epoch']:<7}"
            f"{result['val_loss']:<10.4f}"
            f"{result['val_acc']:.4f}"
        )

    losses = [result["val_loss"] for result in fold_results]
    accuracies = [result["val_acc"] for result in fold_results]

    print(f"\nVal loss：{mean(losses):.4f} ± {stdev(losses):.4f}")
    print(f"Val acc： {mean(accuracies):.4f} ± {stdev(accuracies):.4f}")

    return fold_results

def plot_history(history, fold_no):
    epochs = range(1, len(history["train_loss"]) + 1)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))

    ax1.plot(epochs, history["train_loss"], label="Train")
    ax1.plot(epochs, history["val_loss"], label="Validation")
    ax1.set_title(f"Fold {fold_no} - Loss")
    ax1.set_xlabel("Epoch")
    ax1.set_ylabel("Loss")
    ax1.legend()

    ax2.plot(epochs, history["train_acc"], label="Train")
    ax2.plot(epochs, history["val_acc"], label="Validation")
    ax2.set_title(f"Fold {fold_no} - Top-1 Accuracy")
    ax2.set_xlabel("Epoch")
    ax2.set_ylabel("Accuracy")
    ax2.legend()

    plt.tight_layout()
    plt.show()
    plt.close(fig)
    
def test(model, checkpoint_path, test_records, transform, device, batch_size):
    state_dict = torch.load(checkpoint_path, map_location=device, weights_only=True)
    model.load_state_dict(state_dict)
    model = model.to(device)
    model.eval()

    test_loader = DataLoader(VegetableDataset(test_records, transform), batch_size=batch_size, shuffle=False, num_workers=2)

    criterion = nn.CrossEntropyLoss()
    total_loss = 0.0
    top1_correct = 0
    top5_correct = 0
    total_samples = 0
    all_labels = []
    all_probs = []

    with torch.no_grad():
        for images, labels in test_loader:
            images = images.to(device)
            labels = labels.to(device)

            logits = model(images)
            probs = torch.softmax(logits, dim=1)
            loss = criterion(logits, labels)

            n = labels.size(0)
            total_loss += loss.item() * n
            total_samples += n

            top1_correct += (logits.argmax(dim=1) == labels).sum().item()
            top5_indices = logits.topk(k=5, dim=1).indices
            top5_correct += ((top5_indices == labels.unsqueeze(1)).any(dim=1).sum().item())

            all_labels.extend(labels.cpu().tolist())
            all_probs.extend(probs.cpu().tolist())
        
    all_preds = np.argmax(all_probs, axis=1)

    results = {
        "loss": total_loss / total_samples,
        "top1_acc": top1_correct / total_samples,
        "top5_acc": top5_correct / total_samples,
        "f1": f1_score(all_labels, all_preds, average="macro", zero_division=0),
        "parameters": sum(p.numel() for p in model.parameters()),
    }

    print(f"Test loss:      {results['loss']:.4f}")
    print(f"Top-1 Accuracy: {results['top1_acc']:.4f}")
    print(f"Top-5 Accuracy: {results['top5_acc']:.4f}")
    print(f"F1-score:       {results['f1']:.4f}")
    print(f"參數量:         {results['parameters']:,}")

    return results, all_labels, all_probs

def plot_roc_auc(labels, probs, categories, model_name, result_path):
    y_true = np.asarray(labels)
    y_prob = np.asarray(probs)

    per_class_auc = {}
    fig, axes = plt.subplots(3, 5, figsize=(20, 11), sharex=True, sharey=True)
    axes = axes.ravel()

    for class_idx, class_name in enumerate(categories):
        binary_labels = (y_true == class_idx).astype(int)

        if np.unique(binary_labels).size < 2:
            raise ValueError(f"{class_name} 缺少正例或負例，無法計算 ROC")

        fpr, tpr, _ = roc_curve(binary_labels, y_prob[:, class_idx])
        class_auc = auc(fpr, tpr)
        per_class_auc[class_name] = class_auc

        ax = axes[class_idx]
        ax.plot(fpr, tpr)
        ax.plot([0, 1], [0, 1], "k--", alpha=0.5)
        ax.set_title(f"{class_name} | AUC={class_auc:.3f}")
        ax.set_xlabel("FPR")
        ax.set_ylabel("TPR")

    macro_auc = sum(per_class_auc.values()) / len(per_class_auc)

    fig.suptitle(f"{model_name} ROC Curves | Macro-AUC={macro_auc:.4f}", fontsize=16)
    fig.tight_layout()
    result_path = Path(result_path)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(result_path, dpi=300, bbox_inches="tight")
    plt.show()
    plt.close(fig)

    print(f"\n{model_name} 各類別 AUC：")
    for class_name, class_auc in per_class_auc.items():
        print(f"{class_name:<18} {class_auc:.4f}")
    print(f"Macro-AUC: {macro_auc:.4f}")

    return {"per_class_auc": per_class_auc, "macro_auc": macro_auc}

class ResNet18Transfer(nn.Module):
    def __init__(self, num_classes):
        super().__init__()

        self.backbone = resnet18(weights=ResNet18_Weights.DEFAULT)

        for param in self.backbone.parameters():
            param.requires_grad = False

        in_features = self.backbone.fc.in_features
        self.backbone.fc = nn.Linear(in_features, num_classes)

    def forward(self, x):
        return self.backbone(x)

    def train(self, mode=True):
        super().train(mode)

        self.backbone.eval()
        self.backbone.fc.train(mode)
        return self
    
