import torch
import timm
import copy
import torch.nn as nn
import torch.nn.functional as F
import matplotlib.pyplot as plt
from PIL import Image
from torch.utils.data import Dataset
from torchvision import transforms
from torchvision.models import resnet50, ResNet50_Weights
from tqdm.auto import tqdm
from pathlib import Path

CLASS_NAMES = ["buildings", "forest", "glacier", "mountain", "sea", "street"]
CLASS_TO_IDX = {name: index for index, name in enumerate(CLASS_NAMES)}

class IntelDataset(Dataset):
    def __init__(self, dataframe, transform=None):
        self.dataframe = dataframe.reset_index(drop=True).copy()
        self.transform = transform

    def __len__(self):
        return len(self.dataframe)

    def __getitem__(self, index):
        row = self.dataframe.iloc[index]
        path = row["path"]
        label = CLASS_TO_IDX[row["label"]]

        with Image.open(path) as img:
            image = img.convert("RGB")

        if self.transform is not None:
            image = self.transform(image)

        return image, label, path

def build_resnet_transforms(image_size=224):
    normalize = transforms.Normalize(
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225],
    )

    train_transform = transforms.Compose([
        transforms.RandomResizedCrop(image_size, scale=(0.7, 1.0), ratio=(0.9, 1.1)),
        transforms.RandomHorizontalFlip(p=0.5),
        transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2),
        transforms.ToTensor(),
        normalize,
    ])

    eval_transform = transforms.Compose([
        transforms.Resize((image_size, image_size)),
        transforms.ToTensor(),
        normalize,
    ])

    return train_transform, eval_transform

def build_resnet50(num_classes=6, pretrained=True):
    if pretrained:
        weights = ResNet50_Weights.DEFAULT
    else:
        weights = None
        
    model = resnet50(weights=weights)
    model.fc = nn.Sequential(
        nn.Dropout(p=0.3),
        nn.Linear(model.fc.in_features, num_classes),
    )

    return model

def train_one_epoch(model, loader, criterion, optimizer, device):
    model.train()

    total_loss = 0.0
    total_correct = 0
    total_samples = 0

    for images, labels, paths in tqdm(loader, desc="Train", leave=False):
        images = images.to(device)
        labels = labels.to(device)

        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, labels)

        loss.backward()
        optimizer.step()

        batch_size = labels.size(0)
        total_loss += loss.item() * batch_size
        total_correct += (outputs.argmax(dim=1) == labels).sum().item()
        total_samples += batch_size

    return (total_loss / total_samples, total_correct / total_samples)

@torch.no_grad()
def evaluate(model, loader, criterion, device):
    model.eval()

    total_loss = 0.0
    total_correct = 0
    total_samples = 0

    for images, labels, paths in tqdm(loader, desc="Evaluate", leave=False):
        images = images.to(device)
        labels = labels.to(device)

        outputs = model(images)
        loss = criterion(outputs, labels)

        batch_size = labels.size(0)
        total_loss += loss.item() * batch_size
        total_correct += (outputs.argmax(dim=1) == labels).sum().item()
        total_samples += batch_size

    return (total_loss / total_samples, total_correct / total_samples)

def build_vit_small(num_classes=6, pretrained=True):
    return timm.create_model("vit_small_patch16_224", pretrained=pretrained, num_classes=num_classes)

def build_vit_transforms(image_size, mean, std):
    normalize = transforms.Normalize(mean=mean, std=std)
    
    train_transform = transforms.Compose([
        transforms.RandomResizedCrop(image_size, scale=(0.7, 1.0), ratio=(0.9, 1.1)),
        transforms.RandomHorizontalFlip(p=0.5),
        transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2),
        transforms.ToTensor(),
        normalize,
    ])

    eval_transform = transforms.Compose([
        transforms.Resize((image_size, image_size)),
        transforms.ToTensor(),
        normalize,
    ])

    return train_transform, eval_transform

def build_feature_model(model, model_type):
    feature_model = copy.deepcopy(model)

    if model_type == "resnet":
        feature_model.fc = nn.Identity()
    elif model_type == "vit":
        feature_model.head = nn.Identity()
    else:
        raise ValueError("model_type 請用 resnet 或 vit")

    feature_model.eval()
    return feature_model


@torch.no_grad()
def extract_features(feature_model, loader, device):
    features_all = []
    paths_all = []

    for images, labels, paths in tqdm(loader, desc="Extract features", leave=False):
        features = feature_model(images.to(device))
        features = F.normalize(features, dim=1)

        features_all.append(features.cpu())
        paths_all.extend(paths)

    return torch.cat(features_all, dim=0), paths_all


@torch.no_grad()
def show_retrieval(query_path, feature_model, eval_transform, gallery_features, gallery_paths, device, save_path, top_k=5):
    with Image.open(query_path) as img:
        query_image = img.convert("RGB")

    query_tensor = eval_transform(query_image).unsqueeze(0).to(device)

    feature_model.eval()
    query_feature = feature_model(query_tensor)
    query_feature = F.normalize(query_feature, dim=1).cpu()

    similarities = (query_feature @ gallery_features.T).squeeze(0)

    k = min(top_k, len(gallery_paths))
    scores, indices = similarities.topk(k)

    fig, axes = plt.subplots(1, k + 1, figsize=(3 * (k + 1), 3), squeeze=False)
    axes = axes[0]

    axes[0].imshow(query_image)
    axes[0].set_title("Query")
    axes[0].axis("off")

    for rank, (score, index) in enumerate(zip(scores.tolist(), indices.tolist()), start=1):
        path = gallery_paths[index]

        with Image.open(path) as img:
            result_image = img.convert("RGB")

        axes[rank].imshow(result_image)
        axes[rank].set_title(
            f"Top {rank}\n"
            f"{Path(path).parent.name}\n"
            f"Similarity: {score:.3f}"
        )
        axes[rank].axis("off")

    plt.tight_layout()
    fig.savefig(save_path, dpi=300, bbox_inches="tight")
    plt.show()
    plt.close(fig)