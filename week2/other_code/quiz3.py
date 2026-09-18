import torch
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from sklearn.metrics import roc_curve, roc_auc_score
from xgboost import XGBClassifier

def save_roc_curve(model, test_loader, device, save_path):
    model.eval()
    targets = []
    probabilities = []
    
    with torch.no_grad():
        for X_batch, y_batch in test_loader:
            X_batch = X_batch.to(device)
            output = model(X_batch)
            prob = torch.sigmoid(output)
            
            targets.extend(y_batch.cpu().view(-1).tolist())
            probabilities.extend(prob.cpu().view(-1).tolist())
            
    fpr, tpr, threshold = roc_curve(targets, probabilities)
    auc_curve = roc_auc_score(targets, probabilities)
    
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    
    fig, ax = plt.subplots(figsize=(6, 6))
    
    ax.plot(fpr, tpr, label=f"MLP version 2 (AUC = {auc_curve:.4f})")
    ax.plot([0, 1], [0, 1], "--", color="gray", label="random guess")
    ax.set(xlabel="false positive rate (FPR)", ylabel="true positive rate (TPR)", title="test dataset ROC curve",
           xlim=(0, 1.02), ylim=(0, 1.02))
    ax.legend(loc="lower right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=300, bbox_inches="tight")
    plt.show()
    plt.close(fig)
    
    return auc_curve

def train_xgboost(X_train, y_train, learning_rate):
    model = XGBClassifier(n_estimators=300, max_depth=3, learning_rate=learning_rate, subsample=0.8, colsample_bytree=0.8,
                          reg_lambda=1.0, objective="binary:logistic", eval_metric="logloss", tree_method="hist", random_state=42)
    
    model.fit(X_train, np.asarray(y_train).ravel())
    return model

def save_roc_xgboost(mlp, xgb, test_loader, device, save_path):
    mlp.eval()
    targets = []
    mlp_probabilities = []
    xgb_probabilities = []
    
    positive_index = np.flatnonzero(xgb.classes_ == 1).item()
    
    with torch.no_grad():
        for X_batch, y_batch in test_loader:
            X_batch = X_batch.to(device)
            
            xgb_prob = xgb.predict_proba(X_batch.cpu().numpy())[:, positive_index]
            
            output = mlp(X_batch)
            mlp_prob = torch.sigmoid(output)
            
            targets.extend(y_batch.cpu().view(-1).tolist())
            xgb_probabilities.extend(xgb_prob.tolist())
            mlp_probabilities.extend(mlp_prob.cpu().view(-1).tolist())
            
    xgb_fpr, xgb_tpr, _ = roc_curve(targets, xgb_probabilities)
    mlp_fpr, mlp_tpr, _ = roc_curve(targets, mlp_probabilities)
    
    xgb_auc_curve = roc_auc_score(targets, xgb_probabilities)
    mlp_auc_curve = roc_auc_score(targets, mlp_probabilities)
    
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    
    fig, ax = plt.subplots(figsize=(6, 6))
    
    ax.plot(xgb_fpr, xgb_tpr, label=f"XGBoost (AUC = {xgb_auc_curve:.4f})")
    ax.plot(mlp_fpr, mlp_tpr, label=f"MLP version 2 (AUC = {mlp_auc_curve:.4f})")
    ax.plot([0, 1], [0, 1], "--", color="gray", label="random guess")
    ax.set(xlabel="false positive rate (FPR)", ylabel="true positive rate (TPR)", title="test dataset ROC curve",
            xlim=(0, 1.02), ylim=(0, 1.02))
    ax.legend(loc="lower right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=300, bbox_inches="tight")
    plt.show()
    plt.close(fig)
    
    return {"MLP v2": mlp_auc_curve, "XGBoost": xgb_auc_curve}