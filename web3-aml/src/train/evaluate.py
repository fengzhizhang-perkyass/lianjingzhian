from pathlib import Path
import numpy as np
from sklearn.metrics import (precision_recall_fscore_support, average_precision_score,
                             roc_auc_score, precision_recall_curve, roc_curve,
                             confusion_matrix, brier_score_loss)
from src.utils.io import ROOT, save_json, read_json


def choose_threshold(labels, probability):
    precision, recall, thresholds = precision_recall_curve(labels, probability)
    f1 = 2*precision[:-1]*recall[:-1]/np.maximum(precision[:-1]+recall[:-1], 1e-12)
    return float(thresholds[int(np.argmax(f1))]) if len(thresholds) else 0.5


def evaluate_predictions(labels, probability, threshold=0.5):
    labels, probability = np.asarray(labels), np.asarray(probability)
    if not np.isfinite(probability).all():
        raise ValueError("Predictions contain non-finite values.")
    predictions = (probability >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(labels, predictions, average="binary", zero_division=0)
    pr_p, pr_r, pr_t = precision_recall_curve(labels, probability)
    fpr, tpr, _ = roc_curve(labels, probability)
    # Infinity in ROC thresholds is intentionally excluded from the JSON.
    return {"precision": float(precision), "recall": float(recall), "f1": float(f1),
            "pr_auc": float(average_precision_score(labels, probability)),
            "roc_auc": float(roc_auc_score(labels, probability)),
            "brier_score": float(brier_score_loss(labels, probability)), "threshold": float(threshold),
            "num_test_nodes": len(labels), "confusion_matrix": confusion_matrix(labels, predictions, labels=[0, 1]).tolist(),
            "pr_curve": {"precision": pr_p.tolist(), "recall": pr_r.tolist()},
            "roc_curve": {"fpr": fpr.tolist(), "tpr": tpr.tolist()}}


def save_evaluation(name, result, root: Path = ROOT):
    folder = root / "artifacts/metrics"
    save_json(folder / f"{name}.json", result)
    summary_path = folder / "comparison.json"
    summary = read_json(summary_path) if summary_path.exists() else {}
    summary[name] = {k: v for k, v in result.items() if k not in {"pr_curve", "roc_curve", "confusion_matrix"}}
    save_json(summary_path, summary)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    for curve, xlabel, ylabel in (("pr_curve", "Recall", "Precision"), ("roc_curve", "FPR", "TPR")):
        fig, ax = plt.subplots(figsize=(5, 4))
        values = result[curve]
        ax.plot(values["recall"] if curve == "pr_curve" else values["fpr"],
                values["precision"] if curve == "pr_curve" else values["tpr"])
        ax.set(xlabel=xlabel, ylabel=ylabel, title=name)
        fig.tight_layout()
        fig.savefig(folder / f"{name}_{curve}.png", dpi=160)
        plt.close(fig)
    fig, ax = plt.subplots(figsize=(4, 4))
    matrix = np.array(result["confusion_matrix"])
    ax.imshow(matrix, cmap="Blues")
    for (i, j), value in np.ndenumerate(matrix):
        ax.text(j, i, str(value), ha="center", va="center", color="white" if value > matrix.max()/2 else "black")
    ax.set(xticks=[0, 1], yticks=[0, 1], xticklabels=["licit", "illicit"], yticklabels=["licit", "illicit"],
           xlabel="Predicted", ylabel="True", title=name)
    fig.tight_layout()
    fig.savefig(folder / f"{name}_confusion_matrix.png", dpi=160)
    plt.close(fig)
