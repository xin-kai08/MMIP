"""Shared EfficientNet-B0 backbone and two small classification heads."""
from pathlib import Path
import random
import torch
from torch import nn
from torchvision.models import efficientnet_b0, EfficientNet_B0_Weights
from torchvision import transforms
from PIL import Image, ImageOps

WEIGHTS_ID = 'EfficientNet_B0_Weights.IMAGENET1K_V1'

class WasteModel(nn.Module):
    def __init__(self, dropout=.2, pretrained=False, allow_download=False):
        super().__init__()
        weights = EfficientNet_B0_Weights.IMAGENET1K_V1
        if pretrained and not allow_download:
            cached = Path(torch.hub.get_dir())/'checkpoints'/weights.url.rsplit('/',1)[-1]
            if not cached.is_file():
                raise RuntimeError('ImageNet weights not cached; explicitly enable --allow-weight-download to fetch the 20.5 MB official weights')
        base = efficientnet_b0(weights=weights if pretrained else None)
        self.features = base.features
        self.pool = nn.AdaptiveAvgPool2d(1)
        features = base.classifier[1].in_features
        self.waste_head = nn.Sequential(nn.Dropout(dropout), nn.Linear(features,4))
        self.residual_head = nn.Sequential(nn.Dropout(dropout), nn.Linear(features,4))
        # base.classifier is discarded, never registered on this model.

    def forward(self, x):
        x = self.pool(self.features(x)).flatten(1)
        return self.waste_head(x), self.residual_head(x)

    def stage(self, stage):
        if stage not in ('stage1','stage2'): raise ValueError('Invalid stage')
        self.requires_grad_(True)
        frozen = self.residual_head if stage=='stage1' else self.waste_head
        frozen.requires_grad_(False)
        self.train();frozen.eval()

class Letterbox:
    def __init__(self, size): self.size = size
    def __call__(self, im):
        im = ImageOps.exif_transpose(im).convert('RGBA')
        white = Image.new('RGBA', im.size, 'white');white.alpha_composite(im)
        im = ImageOps.contain(white.convert('RGB'),(self.size,self.size),Image.Resampling.BICUBIC)
        out = Image.new('RGB',(self.size,self.size),'white')
        out.paste(im,((self.size-im.width)//2,(self.size-im.height)//2))
        return out

def preprocessing(config, train=False):
    operations = [Letterbox(config['input_size'])]
    if train:
        operations += [transforms.RandomHorizontalFlip(config['horizontal_flip']),
                       transforms.ColorJitter(brightness=config['brightness_contrast'],contrast=config['brightness_contrast'])]
    operations += [transforms.ToTensor(),transforms.Normalize([.485,.456,.406],[.229,.224,.225])]
    return transforms.Compose(operations)

def seed_all(seed):
    random.seed(seed);torch.manual_seed(seed)
    if torch.cuda.is_available():torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark=False
    torch.backends.cudnn.deterministic=True

def masked_loss(logits, target):
    valid = target >= 0
    if not valid.any():return None
    return nn.functional.cross_entropy(logits[valid], target[valid])
