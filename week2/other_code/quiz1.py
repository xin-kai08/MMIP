from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay, accuracy_score, precision_score, recall_score, f1_score
from sklearn.ensemble import RandomForestClassifier
from pathlib import Path
import matplotlib.pyplot as plt

def data_segment(data, val_ratio):
    X = data.drop(columns=["id", "diagnosis", "Unnamed: 32"])
    y = data["diagnosis"].map({"M": 1, "B": 0})
    
    if y.isna().any():
        raise ValueError("diagnosis有不是M/B的值")
    
    return train_test_split(X, y, test_size=val_ratio, random_state=42, stratify=y)

def feature_scale(X_train, X_val):
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_val_scaled = scaler.transform(X_val)
    
    return X_train_scaled, X_val_scaled

def train_model(X_train_scacled, y_train):
    model = LogisticRegression(max_iter=1000)
    model.fit(X_train_scacled, y_train)
    
    return model

def evaluate_model(model, X_val_scaled, y_val, threshold):
    y_prob = model.predict_proba(X_val_scaled)[:, 1]
    y_prob = (y_prob >= threshold).astype(int)
    
    cm = confusion_matrix(y_val, y_prob, labels=[0, 1])
    scores = {
        "accuracy": accuracy_score(y_val, y_prob),
        "precision": precision_score(y_val, y_prob, zero_division=0),
        "recall": recall_score(y_val, y_prob, zero_division=0),
        "f1_score": f1_score(y_val, y_prob, zero_division=0)
    }
    
    return cm, scores

def save_confusion_matrix(cm, scores, save_path, threshold):
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    
    fig, ax = plt.subplots(figsize=(6, 5))
    display = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=["Benign(0)", "Maligant(1)"])
    
    display.plot(ax=ax, cmap="Blues", colorbar=False)
    ax.set_title(f"confusion matrix (threshold = {threshold})", pad=20)
    
    ax.xaxis.tick_top()
    ax.xaxis.set_label_position("top")
    ax.set_xlabel("prediction label", labelpad=10)
    
    metrics_text = (
        f"accuracy: {scores['accuracy']:.4f}    "
        f"precision: {scores['precision']:.4f}\n"
        f"recall: {scores['recall']:.4f}    "
        f"f1_score: {scores['f1_score']:.4f}"
    )
    fig.text(0.5, 0.04, metrics_text, ha="center", va="bottom", fontsize=11)
    
    fig.tight_layout(rect=[0, 0.15, 1, 1])
    fig.savefig(save_path, dpi=300, bbox_inches="tight")
    plt.show()
    plt.close(fig)
    
def train_random_forset(X_train_scaled, y_train):
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train_scaled, y_train)
    
    return model