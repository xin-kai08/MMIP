def scan_images(split, data_root, categories, class_to_idx):
    records = []

    for category in categories:
        category_dir = data_root / split / category

        if not category_dir.is_dir():
            raise FileNotFoundError(f"找不到：{category_dir}")

        for image_path in sorted(category_dir.iterdir()):
            if image_path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                records.append((image_path, class_to_idx[category]))

    return records