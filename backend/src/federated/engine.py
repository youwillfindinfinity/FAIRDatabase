"""
engine.py — Federated Learning engine.

Implements:
- TabularMLP: configurable PyTorch model for tabular data
- get_flat_weights / set_flat_weights: serialise/deserialise model state
- local_train_fedprox: FedProx local objective with proximal regularisation
- fedprox_aggregate: weighted FedAvg aggregation (server-side, same for FedProx and FedAvg)
- dirichlet_partition: Dirichlet(α) non-IID data partitioning — handles both discrete labels
  and continuous regression targets (via quantile binning)

Scientific references:
- FedProx: Li et al., "Federated Optimization in Heterogeneous Networks" (ICLR 2020)
- Dirichlet non-IID: Yurochkin et al., "Bayesian Nonparametric Federated Learning" (ICML 2019)
- DP-FL: McMahan et al., "Learning Differentially Private Recurrent Language Models" (ICLR 2018)
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
from typing import List, Optional, Tuple


# ── Model ─────────────────────────────────────────────────────────────────────

class TabularMLP(nn.Module):
    """Multi-layer perceptron for tabular data. Supports regression and classification."""

    def __init__(self, input_dim: int, hidden_dims: List[int], output_dim: int,
                 task: str = "regression"):
        super().__init__()
        dims = [input_dim] + hidden_dims
        layers: List[nn.Module] = []
        for i in range(len(dims) - 1):
            layers.append(nn.Linear(dims[i], dims[i + 1]))
            layers.append(nn.ReLU())
        layers.append(nn.Linear(dims[-1], output_dim))
        if task == "classification":
            layers.append(nn.Softmax(dim=-1))
        self.net = nn.Sequential(*layers)
        self.task = task

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def get_flat_weights(model: nn.Module) -> np.ndarray:
    """Flatten all model parameters into a 1-D float32 numpy array."""
    return np.concatenate(
        [p.detach().numpy().ravel() for p in model.parameters()]
    )


def set_flat_weights(model: nn.Module, weights: np.ndarray) -> None:
    """Load a flat 1-D numpy array back into model parameters (in-place)."""
    idx = 0
    for p in model.parameters():
        n = p.numel()
        p.data.copy_(
            torch.from_numpy(weights[idx: idx + n].reshape(p.shape).astype(np.float32))
        )
        idx += n


# ── Training ──────────────────────────────────────────────────────────────────

def local_train_fedprox(
    model: nn.Module,
    global_weights: np.ndarray,
    data_X: np.ndarray,
    data_y: np.ndarray,
    epochs: int,
    lr: float,
    mu: float,
    task: str = "regression",
) -> Tuple[np.ndarray, float]:
    """
    Run local FedProx training on one client partition.

    Minimises: F_i(w) + (μ/2) ||w - w_global||²

    Setting μ=0 recovers standard FedAvg local training.

    Returns:
        (updated_flat_weights, final_train_loss)

    Note: the caller is responsible for computing the weight DELTA
    (returned_weights - global_weights), clipping it, and adding DP noise.
    Never clip the full weights — that would invalidate the DP sensitivity bound.
    """
    set_flat_weights(model, global_weights)

    optimizer = torch.optim.SGD(model.parameters(), lr=lr, momentum=0.0)
    criterion = (
        nn.MSELoss() if task == "regression" else nn.CrossEntropyLoss()
    )

    X = torch.FloatTensor(data_X)
    if task == "regression":
        y = torch.FloatTensor(data_y).unsqueeze(1) if data_y.ndim == 1 else torch.FloatTensor(data_y)
    else:
        y = torch.LongTensor(data_y.astype(int))

    # Snapshot of global weights for the proximal term (frozen — not updated)
    global_tensors = [
        torch.FloatTensor(p.detach().numpy().copy())
        for p in model.parameters()
    ]

    final_loss = float("nan")
    model.train()
    for _ in range(epochs):
        optimizer.zero_grad()
        output = model(X)
        task_loss = criterion(output, y)

        # FedProx proximal term: (μ/2) * Σ ||w_i - w_global||²
        # Keeps local model close to global, improving convergence on non-IID data
        if mu > 0.0:
            prox = sum(
                ((p - g) ** 2).sum()
                for p, g in zip(model.parameters(), global_tensors)
            )
            loss = task_loss + (mu / 2.0) * prox
        else:
            loss = task_loss

        loss.backward()
        # Gradient norm clipping (optimizer stability — separate from DP delta-clipping).
        # Prevents weight explosion when training starts from noise-scaled global weights,
        # which occurs in high-noise DP regimes where σ >> typical weight magnitude.
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()
        final_loss = task_loss.item()  # log task loss only, not regularised

    return get_flat_weights(model), final_loss


def eval_loss(
    model: nn.Module,
    weights: np.ndarray,
    data_X: np.ndarray,
    data_y: np.ndarray,
    task: str = "regression",
) -> float:
    """Evaluate model on a held-out set. Returns scalar loss (no grad)."""
    set_flat_weights(model, weights)
    criterion = nn.MSELoss() if task == "regression" else nn.CrossEntropyLoss()
    X = torch.FloatTensor(data_X)
    if task == "regression":
        y = torch.FloatTensor(data_y).unsqueeze(1) if data_y.ndim == 1 else torch.FloatTensor(data_y)
    else:
        y = torch.LongTensor(data_y.astype(int))
    model.eval()
    with torch.no_grad():
        return criterion(model(X), y).item()


# ── Aggregation ───────────────────────────────────────────────────────────────

def fedprox_aggregate(
    client_deltas: List[np.ndarray],
    client_sizes: List[int],
) -> np.ndarray:
    """
    Weighted FedAvg aggregation of weight DELTAS.

    FedProx uses the same server-side aggregation as FedAvg; the proximal
    term only acts during local training.

    The caller adds the returned aggregated delta back to global_weights:
        new_global = old_global + fedprox_aggregate(deltas, sizes)

    This is the correct DP-FL protocol: noise is added to deltas before this
    call, bounding the sensitivity to client_size-weighted mean update norms.
    """
    total = sum(client_sizes)
    result = np.zeros_like(client_deltas[0], dtype=np.float64)
    for delta, n in zip(client_deltas, client_sizes):
        result += delta.astype(np.float64) * (n / total)
    return result.astype(np.float32)


# ── Simulation ────────────────────────────────────────────────────────────────

def dirichlet_partition(
    data_X: np.ndarray,
    data_y: np.ndarray,
    n_clients: int,
    alpha: float,
    seed: int = 42,
    n_bins: int = 10,
) -> List[Tuple[np.ndarray, np.ndarray]]:
    """
    Partition (data_X, data_y) into n_clients subsets using a Dirichlet
    distribution over class labels.

    Handles both discrete classification targets and continuous regression
    targets: continuous values are quantile-binned into n_bins discrete classes
    before applying the Dirichlet draw, preserving the intended non-IID
    heterogeneity (low α → clients see very different target distributions).

    Without this binning, np.unique(continuous_y) ≈ n_samples singleton classes
    and the Dirichlet distribution has no effect — the partition becomes uniform
    random regardless of α. This was a critical bug in the original design.

    α semantics:
      Low  α (e.g. 0.1) → highly non-IID (each client sees few bins)
      High α (e.g. 100) → near-IID distribution

    Reference: Yurochkin et al., ICML 2019 (§3.2).
    """
    rng = np.random.default_rng(seed)

    # Detect continuous targets and bin them
    unique_vals = np.unique(data_y)
    if len(unique_vals) > max(n_clients * 5, 20):
        # Continuous or very high-cardinality — bin into quantiles
        actual_bins = min(n_bins, n_clients * 2)
        quantiles = np.linspace(0, 100, actual_bins + 1)
        bin_edges = np.percentile(data_y, quantiles)
        bin_edges = np.unique(bin_edges)          # drop duplicate edges
        y_discrete = np.digitize(data_y, bin_edges[1:-1]).astype(int)
    else:
        y_discrete = data_y.astype(int)

    classes = np.unique(y_discrete)
    client_indices: List[List[int]] = [[] for _ in range(n_clients)]

    for cls in classes:
        cls_idx = np.where(y_discrete == cls)[0]
        rng.shuffle(cls_idx)
        proportions = rng.dirichlet([alpha] * n_clients)
        counts = (proportions * len(cls_idx)).astype(int)
        # Fix rounding so sum(counts) == len(cls_idx)
        counts[-1] = len(cls_idx) - counts[:-1].sum()
        ptr = 0
        for client_id, count in enumerate(counts):
            client_indices[client_id].extend(cls_idx[ptr: ptr + count].tolist())
            ptr += count

    return [
        (data_X[idxs], data_y[idxs])
        for idxs in client_indices
    ]
