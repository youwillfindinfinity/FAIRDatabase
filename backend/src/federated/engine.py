"""
engine.py — Federated Learning engine.

Implements:
- TabularMLP: configurable PyTorch model for tabular data
- get_flat_weights / set_flat_weights: serialise/deserialise model state
- local_train_fedprox: FedProx local objective with proximal regularisation
- fedprox_aggregate: weighted FedAvg aggregation
- dirichlet_partition: Dirichlet-based non-IID data partitioning for simulation

FedProx reference: Li et al., "Federated Optimization in Heterogeneous Networks" (2020)
Dirichlet non-IID: Yurochkin et al., "Bayesian Nonparametric Federated Learning" (2019)
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
from typing import List, Tuple


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
) -> np.ndarray:
    """
    Run local FedProx training on one client partition.

    Minimises: F_i(w) + (μ/2) ||w - w_global||²

    Setting μ=0 recovers standard FedAvg local training.
    Returns updated flat weights (does not modify model in-place after training).
    """
    set_flat_weights(model, global_weights)

    optimizer = torch.optim.SGD(model.parameters(), lr=lr, momentum=0.9)
    criterion = (
        nn.MSELoss() if task == "regression" else nn.CrossEntropyLoss()
    )

    X = torch.FloatTensor(data_X)
    if task == "regression":
        y = torch.FloatTensor(data_y).unsqueeze(1) if data_y.ndim == 1 else torch.FloatTensor(data_y)
    else:
        y = torch.LongTensor(data_y.astype(int))

    # Snapshot of global weights for the proximal term
    global_tensors = [
        torch.FloatTensor(p.detach().numpy().copy())
        for p in model.parameters()
    ]

    model.train()
    for _ in range(epochs):
        optimizer.zero_grad()
        output = model(X)
        loss = criterion(output, y)

        # FedProx proximal term: (μ/2) * Σ ||w_i - w_global||²
        if mu > 0.0:
            prox = sum(
                ((p - g) ** 2).sum()
                for p, g in zip(model.parameters(), global_tensors)
            )
            loss = loss + (mu / 2.0) * prox

        loss.backward()
        optimizer.step()

    return get_flat_weights(model)


# ── Aggregation ───────────────────────────────────────────────────────────────

def fedprox_aggregate(
    client_weights: List[np.ndarray],
    client_sizes: List[int],
) -> np.ndarray:
    """
    Weighted FedAvg aggregation.

    FedProx uses the same server-side aggregation as FedAvg;
    the proximal term acts only during local training.
    """
    total = sum(client_sizes)
    result = np.zeros_like(client_weights[0], dtype=np.float64)
    for w, n in zip(client_weights, client_sizes):
        result += w.astype(np.float64) * (n / total)
    return result.astype(np.float32)


# ── Simulation ────────────────────────────────────────────────────────────────

def dirichlet_partition(
    data_X: np.ndarray,
    data_y: np.ndarray,
    n_clients: int,
    alpha: float,
    seed: int = 42,
) -> List[Tuple[np.ndarray, np.ndarray]]:
    """
    Partition (data_X, data_y) into n_clients subsets using a Dirichlet
    distribution over class labels.

    Low α (e.g. 0.1) → highly non-IID (each client sees few classes).
    High α (e.g. 100) → near-IID distribution.

    Reference: Yurochkin et al., ICML 2019 (§3.2).
    """
    rng = np.random.default_rng(seed)
    classes = np.unique(data_y)
    client_indices: List[List[int]] = [[] for _ in range(n_clients)]

    for cls in classes:
        cls_idx = np.where(data_y == cls)[0]
        rng.shuffle(cls_idx)
        proportions = rng.dirichlet([alpha] * n_clients)
        counts = (proportions * len(cls_idx)).astype(int)
        # Fix rounding so total == len(cls_idx)
        counts[-1] = len(cls_idx) - counts[:-1].sum()
        ptr = 0
        for client_id, count in enumerate(counts):
            client_indices[client_id].extend(cls_idx[ptr: ptr + count].tolist())
            ptr += count

    return [
        (data_X[idxs], data_y[idxs])
        for idxs in client_indices
    ]
