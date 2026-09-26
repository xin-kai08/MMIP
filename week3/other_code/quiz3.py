import torch
import numpy as np
import torch.nn.functional as F
import matplotlib.pyplot as plt
from torchvision import transforms
from pathlib import Path
from PIL import Image

train_augment = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.RandomHorizontalFlip(p=0.5),
    transforms.RandomRotation(degrees=15),
    transforms.ToTensor(),
])

test_augment = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
])

resnet_train_augment = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.RandomHorizontalFlip(p=0.5),
    transforms.RandomRotation(degrees=15),
    transforms.ToTensor(),
    transforms.Normalize(
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225],
        ),
])

resnet_test_augment = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225],
        ),
])

def plot_kernels(conv_layer, result_path, kernel_indices=(0, 1)):
    weights = conv_layer.weight.detach().cpu().numpy()

    selected = weights[list(kernel_indices)]
    limit = max(float(np.abs(selected).max()), 1e-8)

    fig, axes = plt.subplots(len(kernel_indices), 3, figsize=(9, 3 * len(kernel_indices)), squeeze=False, constrained_layout=True)

    channel_names = ["R", "G", "B"]

    for row, kernel_idx in enumerate(kernel_indices):
        for channel_idx, channel_name in enumerate(channel_names):
            ax = axes[row, channel_idx]

            im = ax.imshow(weights[kernel_idx, channel_idx], cmap="coolwarm", vmin=-limit, vmax=limit, interpolation="nearest")

            ax.set_title(f"Filter {kernel_idx} - {channel_name}")
            ax.set_xticks([])
            ax.set_yticks([])

    fig.colorbar(im, ax=axes.ravel().tolist(), label="Weight")
    fig.suptitle("First Convolution Layer - Learned Filters")

    result_path = Path(result_path)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(result_path, dpi=300, bbox_inches="tight")

    plt.show()
    plt.close(fig)
    
def plot_gradcam(model, target_layer, image_path, transform, categories, device, result_path, true_label=None):
    model = model.to(device)
    model.eval()

    with Image.open(image_path) as image:
        original = image.convert("RGB")

    x = transform(original).unsqueeze(0).to(device)

    x.requires_grad_(True)

    captured = {}

    def save_activation(module, inputs, output):
        captured["features"] = output

    handle = target_layer.register_forward_hook(save_activation)

    try:
        with torch.enable_grad():
            logits = model(x)
            pred_idx = logits.argmax(dim=1).item()
            confidence = logits.softmax(dim=1)[0, pred_idx].item()

            features = captured["features"]

            gradients = torch.autograd.grad(outputs=logits[0, pred_idx], inputs=features)[0]

            channel_weights = gradients.mean(dim=(2, 3), keepdim=True)

            cam = torch.relu((channel_weights * features).sum(dim=1, keepdim=True)).detach()

            cam = F.interpolate(cam, size=x.shape[-2:], mode="bilinear", align_corners=False)

            cam = cam[0, 0].cpu().numpy()

    finally:
        handle.remove()

    cam = cam - cam.min()
    if cam.max() > 0:
        cam = cam / cam.max()
    else:
        print("這張圖的 Grad-CAM 沒有可顯示的正向熱區。")

    height, width = x.shape[-2:]
    display_image = original.resize((width, height), Image.Resampling.BILINEAR)
    rgb = np.asarray(display_image, dtype=np.float32) / 255.0

    heatmap = plt.get_cmap("jet")(cam)[:, :, :3]
    overlay = np.clip(0.6 * rgb + 0.4 * heatmap, 0, 1)

    fig, axes = plt.subplots(1, 3, figsize=(12, 4))

    axes[0].imshow(rgb)
    axes[0].set_title(
        f"True: {categories[true_label]}"
        if true_label is not None else "Input"
    )

    axes[1].imshow(cam, cmap="jet", vmin=0, vmax=1)
    axes[1].set_title("Grad-CAM")

    axes[2].imshow(overlay)
    axes[2].set_title(f"Pred: {categories[pred_idx]} ({confidence:.2%})")

    for ax in axes:
        ax.axis("off")

    fig.tight_layout()

    result_path = Path(result_path)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(result_path, dpi=300, bbox_inches="tight")

    plt.show()
    plt.close(fig)

    return {"predicted_class": categories[pred_idx], "confidence": confidence, "heatmap": cam}