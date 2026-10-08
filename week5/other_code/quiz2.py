import torch
import timm
import torch.nn as nn
from torchvision.models import resnet18, ResNet18_Weights
from pathlib import Path
from PIL import Image
from torch.utils.data import Dataset
from torchvision import transforms
from transformers import AutoModel
from tqdm.auto import tqdm

class FashionDataset(Dataset):
    def __init__(self, dataframe, image_root, image_col, text_col, label_col, class_to_idx, tokenizer, transform=None, max_length=64):
        self.dataframe = dataframe.reset_index(drop=True).copy()
        self.image_root = Path(image_root)
        self.image_col = image_col
        self.text_col = text_col
        self.label_col = label_col
        self.class_to_idx = class_to_idx
        self.tokenizer = tokenizer
        self.transform = transform
        self.max_length = max_length

    def __len__(self):
        return len(self.dataframe)

    def __getitem__(self, index):
        row = self.dataframe.iloc[index]
        image_path = self.image_root / str(row[self.image_col])

        with Image.open(image_path) as img:
            image = img.convert("RGB")
        if self.transform is not None:
            image = self.transform(image)

        encoded = self.tokenizer(str(row[self.text_col]), max_length=self.max_length, padding="max_length",
                                 truncation=True, return_tensors="pt")

        input_ids = encoded["input_ids"].squeeze(0)
        attention_mask = encoded["attention_mask"].squeeze(0)

        label = self.class_to_idx[row[self.label_col]]

        return image, input_ids, attention_mask, label

def build_transforms(image_size=224, mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]):
    normalize = transforms.Normalize(mean=mean, std=std)

    train_transform = transforms.Compose([
        transforms.Resize((image_size, image_size)),
        transforms.RandomHorizontalFlip(p=0.5),
        transforms.ToTensor(),
        normalize,
    ])

    eval_transform = transforms.Compose([
        transforms.Resize((image_size, image_size)),
        transforms.ToTensor(),
        normalize,
    ])

    return train_transform, eval_transform

def build_image_encoder(image_backbone):
    if image_backbone == "resnet18":
        model = resnet18(weights=ResNet18_Weights.DEFAULT)
        image_dim = model.fc.in_features
        model.fc = nn.Identity()
        
    elif image_backbone == "vit_tiny":
        model = timm.create_model("vit_tiny_patch16_224", pretrained=True, num_classes=0)
        image_dim = model.num_features
        
    else:
        raise ValueError("不支援的 image_backbone")

    return model, image_dim

class MultimodalClassifier(nn.Module):
    def __init__(self, num_classes, image_backbone, text_model_name="distilbert/distilbert-base-uncased"):
        super().__init__()
        self.image_encoder, input_dim = build_image_encoder(image_backbone)
        self.text_encoder = AutoModel.from_pretrained(text_model_name)
        text_dim = self.text_encoder.config.hidden_size
        self.classifier = nn.Sequential(
            nn.Linear(input_dim + text_dim, 256),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(256, num_classes),
        )

    def forward(self, images, input_ids, attention_mask):
        image_features = self.image_encoder(images)
        text_outputs = self.text_encoder(input_ids=input_ids, attention_mask=attention_mask)
        token_features = text_outputs.last_hidden_state

        mask = attention_mask.unsqueeze(-1).to(token_features.dtype)

        text_features = ((token_features * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1))
        combined_features = torch.cat([image_features, text_features], dim=1)

        return self.classifier(combined_features)
    
def train_one_epoch(model, loader, criterion, optimizer, device):
    model.train()

    total_loss = 0.0
    total_correct = 0
    total_samples = 0

    for images, input_ids, attention_mask, labels in tqdm(loader, desc="Train", leave=False):
        images = images.to(device)
        input_ids = input_ids.to(device)
        attention_mask = attention_mask.to(device)
        labels = labels.to(device)

        optimizer.zero_grad()
        outputs = model(images, input_ids, attention_mask)
        loss = criterion(outputs, labels)

        loss.backward()
        optimizer.step()

        batch_size = labels.size(0)
        total_loss += loss.item() * batch_size
        total_correct += (outputs.argmax(dim=1) == labels).sum().item()
        total_samples += batch_size

    return total_loss / total_samples, total_correct / total_samples


@torch.no_grad()
def evaluate(model, loader, criterion, device):
    model.eval()

    total_loss = 0.0
    total_correct = 0
    total_samples = 0

    for images, input_ids, attention_mask, labels in tqdm(loader, desc="Evaluate", leave=False):
        images = images.to(device)
        input_ids = input_ids.to(device)
        attention_mask = attention_mask.to(device)
        labels = labels.to(device)

        outputs = model(images, input_ids, attention_mask)
        loss = criterion(outputs, labels)

        batch_size = labels.size(0)
        total_loss += loss.item() * batch_size
        total_correct += (outputs.argmax(dim=1) == labels).sum().item()
        total_samples += batch_size

    return total_loss / total_samples, total_correct / total_samples