import torch
import matplotlib.pyplot as plt
from torch import nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.model_selection import train_test_split
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.metrics import f1_score, accuracy_score, precision_score, recall_score, confusion_matrix, ConfusionMatrixDisplay
from pathlib import Path
from copy import deepcopy

def data_segment(data):
    target = "default.payment.next.month"
    
    X = data.drop(columns=["ID", target]).copy()
    y = data[target].copy()
    
    if y.isna().any() or not y.isin([0, 1]).all():
        raise ValueError("目標欄位只能存在0或1，且不能有缺失值")
    
    X_train, X_temp, y_train, y_temp = train_test_split(X, y, test_size=0.3, train_size=0.7, random_state=42, stratify=y)
    X_val, X_test, y_val, y_test = train_test_split(X_temp, y_temp, test_size=1/3, train_size=2/3, random_state=42, stratify=y_temp)
    
    return X_train, X_val, X_test, y_train, y_val, y_test

def feature_preprocess(X_train, X_val, X_test):
    X_train = X_train.copy()
    X_val = X_val.copy()
    X_test = X_test.copy()
    
    for X in [X_train, X_val, X_test]:
        X["SEX"] = X["SEX"].map({1: 0, 2: 1})
        
        if X["SEX"].isna().any():
            raise ValueError("SEX含有缺失值或不為1或2的內容")
        
    categorical_col = ["EDUCATION", "MARRIAGE", "PAY_0", "PAY_2", "PAY_3", "PAY_4", "PAY_5", "PAY_6"]
    numerical_col = ["LIMIT_BAL", "AGE", "BILL_AMT1", "BILL_AMT2", "BILL_AMT3", "BILL_AMT4", "BILL_AMT5", "BILL_AMT6", "PAY_AMT1", "PAY_AMT2", "PAY_AMT3", "PAY_AMT4", "PAY_AMT5", "PAY_AMT6"]
    
    processor = ColumnTransformer(transformers=[("numeric", StandardScaler(), numerical_col),
                                                ("category", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical_col),
                                                ("binary", "passthrough", ["SEX"])], remainder="drop")
    
    X_train_preprocessd = processor.fit_transform(X_train)
    X_val_preprocessed = processor.transform(X_val)
    X_test_preprocessed = processor.transform(X_test)
    
    return X_train_preprocessd, X_val_preprocessed, X_test_preprocessed, processor

def create_dataloader(X, y, batch_size=64, shuffle=False):
    X_tensor = torch.tensor(X, dtype=torch.float32)
    y_tensor = torch.tensor(y.to_numpy(), dtype=torch.float32).reshape(-1, 1)
    
    dataset = TensorDataset(X_tensor, y_tensor)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=shuffle)
    
    return loader

class MLP(nn.Module):
    def __init__(self, input_dim):
        super().__init__()
        self.mlp = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1)
        )
    def forward(self, x):
        x = self.mlp(x)
        return x
    
def train_model(model, train_loader, val_loader, device, epochs, learning_rate, threshold):
    criterion = torch.nn.BCEWithLogitsLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    
    history = {"train_loss": [], "train_f1": [], "val_loss": [], "val_f1": []}
    
    for epoch in range(epochs):
        model.train()
        train_loss_sum = 0
        train_count = 0
        train_targets = []
        train_predictions = []
        
        for X_batch, y_batch in train_loader:
            X_batch = X_batch.to(device)
            y_batch = y_batch.to(device)
            
            optimizer.zero_grad()
            output = model(X_batch)
            loss = criterion(output, y_batch)
            loss.backward()
            optimizer.step()
            
            train_loss_sum += loss.item() * X_batch.size(0)
            train_count += X_batch.size(0)
            
            prob = torch.sigmoid(output.detach())
            prediction = (prob >= threshold).int()
            
            train_targets.extend(y_batch.detach().cpu().view(-1).tolist())
            train_predictions.extend(prediction.cpu().view(-1).tolist())
        
        train_loss = train_loss_sum / train_count
        train_f1 = f1_score(train_targets, train_predictions, zero_division=0)
        
        model.eval()
        val_loss_sum = 0
        val_count = 0
        val_targets = []
        val_predictions = []
        
        with torch.no_grad():
            for X_batch, y_batch in val_loader:
                X_batch = X_batch.to(device)
                y_batch = y_batch.to(device)
                
                output = model(X_batch)
                loss = criterion(output, y_batch)
                
                val_loss_sum += loss.item() * X_batch.size(0)
                val_count += X_batch.size(0)
                
                prob = torch.sigmoid(output.detach())
                prediction = (prob >= threshold).int()
                
                val_targets.extend(y_batch.detach().cpu().view(-1).tolist())
                val_predictions.extend(prediction.cpu().view(-1).tolist())
            
        val_loss = val_loss_sum / val_count
        val_f1 = f1_score(val_targets, val_predictions, zero_division=0)
            
        history["train_loss"].append(train_loss)
        history["train_f1"].append(train_f1)
        history["val_loss"].append(val_loss)
        history["val_f1"].append(val_f1)
        
        print(f"epoch {epoch + 1}/{epochs} | train loss: {train_loss:.4f}, F1: {train_f1:.4f} | val loss: {val_loss:.4f}, val f1: {val_f1:.4f}")
        
    return model, history

def evaluate_model(model, test_loader, device, threshold):
    model.eval()
    criterion = torch.nn.BCEWithLogitsLoss()
    
    targets = []
    predictions = []
    loss_sum = 0
    count = 0
    
    with torch.no_grad():
        for X_batch, y_batch in test_loader:
            X_batch = X_batch.to(device)
            y_batch = y_batch.to(device)
            
            output = model(X_batch)
            loss = criterion(output, y_batch)
            
            loss_sum += loss.item() * X_batch.size(0)
            count += X_batch.size(0)
            
            prob = torch.sigmoid(output)
            prediction = (prob >= threshold).int()
            
            targets.extend(y_batch.cpu().view(-1).tolist())
            predictions.extend(prediction.cpu().view(-1).tolist())
            
    scores = {
        "loss": loss_sum / count,
        "accuracy": accuracy_score(targets, predictions),
        "precision": precision_score(targets, predictions, zero_division=0),
        "recall": recall_score(targets, predictions, zero_division=0),
        "f1": f1_score(targets, predictions, zero_division=0)
    }
    cm = confusion_matrix(targets, predictions, labels=[0, 1])
    
    return scores, cm

def save_result_plots(history, test_scores, test_cm, save_dir, prefix, threshold):
    save_dir=Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    
    epochs = range(1, len(history["train_loss"]) + 1)
    fig, ax = plt.subplots(figsize=(8, 5))
    
    ax.plot(epochs, history["train_loss"], label="train loss")
    ax.plot(epochs, history["val_loss"], label="val loss")
    ax.set_xlabel("epoch")
    ax.set_ylabel("loss")
    ax.set_title("training and validation loss")
    ax.legend()
    ax.grid(alpha=0.3)
    
    fig.tight_layout()
    fig.savefig(save_dir / f"{prefix}_loss.png", dpi=300, bbox_inches="tight")
    plt.show()
    plt.close(fig)
    
    fig, ax = plt.subplots(figsize=(8, 5))
    
    ax.plot(epochs, history["train_f1"], label="train f1")
    ax.plot(epochs, history["val_f1"], label="val f1")
    ax.set_xlabel("epoch")
    ax.set_ylabel("loss")
    ax.set_title("training and validation f1")
    ax.legend()
    ax.grid(alpha=0.3)
    
    fig.tight_layout()
    fig.savefig(save_dir / f"{prefix}_f1.png", dpi=300, bbox_inches="tight")
    plt.show()
    plt.close(fig)
    
    fig, ax = plt.subplots(figsize=(7, 6))
    
    display = ConfusionMatrixDisplay(confusion_matrix=test_cm, display_labels=["non-default(0)", "default(1)"])
    display.plot(ax=ax, cmap="Blues", colorbar=False)
    ax.xaxis.tick_top()
    ax.xaxis.set_label_position("top")
    ax.set_xlabel("predicted label", labelpad=10)
    ax.set_ylabel("true label")
    ax.set_title(f"test confusion matrix(threshold = {threshold})", pad=20)
    metric_test = (
        f"test loss: {test_scores['loss']:.4f}  "
        f"accuracy: {test_scores['accuracy']:.4f}\n"
        f"precision: {test_scores['precision']:.4f} "
        f"recall: {test_scores['recall']:.4f}\n"
        f"f1 score: {test_scores['f1']:.4f}"
    )
    fig.text(0.5, 0.03, metric_test, ha="center", va="bottom", fontsize=11)
    fig.tight_layout(rect=[0, 0.18, 1, 1])
    fig.savefig(save_dir / f"{prefix}_test_cm.png", dpi=300, bbox_inches="tight")
    plt.show()
    plt.close(fig)
    
class MLP_v2(nn.Module):
    def __init__(self, input_dim, dropout=0.0):
        super().__init__()
        self.mlp = nn.Sequential(
            nn.Linear(input_dim, 128),
            nn.ReLU(),
            nn.Dropout(p=dropout),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Dropout(p=dropout),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Dropout(p=dropout),
            nn.Linear(32, 1)
        )
    def forward(self, x):
        x = self.mlp(x)
        return x
    
def train_model_v2(model, train_loader, val_loader, device, epochs, learning_rate,
                   threshold, patience=5, min_delta=0.0001, weight_decay=0.0001):
    criterion = torch.nn.BCEWithLogitsLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    
    history = {"train_loss": [], "train_f1": [], "val_loss": [], "val_f1": []}
    
    best_val_loss = float("inf")
    best_weight = None
    best_epoch = 0
    
    stopping_reference = float("inf")
    wait = 0
    
    for epoch in range(epochs):
        model.train()
        train_loss_sum = 0
        train_count = 0
        train_targets = []
        train_predictions = []
        
        for X_batch, y_batch in train_loader:
            X_batch = X_batch.to(device)
            y_batch = y_batch.to(device)
            
            optimizer.zero_grad()
            output = model(X_batch)
            loss = criterion(output, y_batch)
            loss.backward()
            optimizer.step()
            
            train_loss_sum += loss.item() * X_batch.size(0)
            train_count += X_batch.size(0)
            
            prob = torch.sigmoid(output.detach())
            prediction = (prob >= threshold).int()
            
            train_targets.extend(y_batch.detach().cpu().view(-1).tolist())
            train_predictions.extend(prediction.cpu().view(-1).tolist())
        
        train_loss = train_loss_sum / train_count
        train_f1 = f1_score(train_targets, train_predictions, zero_division=0)
        
        model.eval()
        val_loss_sum = 0
        val_count = 0
        val_targets = []
        val_predictions = []
        
        with torch.no_grad():
            for X_batch, y_batch in val_loader:
                X_batch = X_batch.to(device)
                y_batch = y_batch.to(device)
                
                output = model(X_batch)
                loss = criterion(output, y_batch)
                
                val_loss_sum += loss.item() * X_batch.size(0)
                val_count += X_batch.size(0)
                
                prob = torch.sigmoid(output.detach())
                prediction = (prob >= threshold).int()
                
                val_targets.extend(y_batch.detach().cpu().view(-1).tolist())
                val_predictions.extend(prediction.cpu().view(-1).tolist())
            
        val_loss = val_loss_sum / val_count
        val_f1 = f1_score(val_targets, val_predictions, zero_division=0)
            
        history["train_loss"].append(train_loss)
        history["train_f1"].append(train_f1)
        history["val_loss"].append(val_loss)
        history["val_f1"].append(val_f1)
        
        print(f"epoch {epoch + 1}/{epochs} | train loss: {train_loss:.4f}, F1: {train_f1:.4f} | val loss: {val_loss:.4f}, val f1: {val_f1:.4f}")
        
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_epoch = epoch + 1
            best_weight = deepcopy(model.state_dict())
            
        if val_loss < stopping_reference - min_delta:
            stopping_reference = val_loss
            wait = 0
            
        else:
            wait += 1
            
        if wait >= patience:
            print(f"early stopping：連續{patience}輪無足夠改善")
            break
        
    if best_weight is None:
        raise ValueError("未取得有效模型權重")
    
    model.load_state_dict(best_weight)
    history["best_epoch"] = best_epoch
    print(f"還原epoch {best_epoch}的模型，val loss = {best_val_loss:.4f}")
            
    return model, history