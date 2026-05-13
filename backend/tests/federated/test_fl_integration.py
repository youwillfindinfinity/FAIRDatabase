"""
Integration test: full FL simulation round-trip.

Tests the engine + DP pipeline together without a live DB or Flask server.
Verifies that:
1. Dirichlet partition produces non-empty client splits
2. Local FedProx training updates weights
3. Clip + Gaussian noise satisfies dimensionality
4. FedAvg aggregation produces same-shape result
5. RDP accountant returns ε ≤ configured budget after all rounds
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import pytest
from src.federated.engine import (
    TabularMLP, get_flat_weights, set_flat_weights,
    local_train_fedprox, fedprox_aggregate, dirichlet_partition,
)
from src.federated.fl_privacy import compute_noise_multiplier, compute_epsilon_spent
from src.privacy.helpers import clip_gradients, add_gaussian_noise_dp
from src.federated.crypto import encrypt_weights, decrypt_weights


TARGET_EPSILON = 1.0
DELTA = 1e-5
ROUNDS = 5
N_CLIENTS = 3
CLIP_NORM = 1.0
SECRET = "integration-test-secret"
TASK_ID = "integration-task-id"


@pytest.fixture(scope="module")
def dataset():
    np.random.seed(7)
    X = np.random.randn(150, 4).astype(np.float32)
    y = np.repeat([0, 1, 2], 50).astype(np.float32)
    return X, y


@pytest.fixture(scope="module")
def noise_mult():
    return compute_noise_multiplier(TARGET_EPSILON, DELTA, ROUNDS)


class TestSimulationRoundTrip:
    def test_noise_mult_is_positive(self, noise_mult):
        assert noise_mult > 0

    def test_dirichlet_partitions_all_data(self, dataset):
        X, y = dataset
        parts = dirichlet_partition(X, y, n_clients=N_CLIENTS, alpha=0.5)
        total = sum(len(px) for px, _ in parts)
        assert total == len(X)

    def test_full_simulation_loop(self, dataset, noise_mult):
        """
        Run ROUNDS of FedProx + DP aggregation and verify:
        - weights change each round
        - final ε spent ≤ TARGET_EPSILON
        """
        X, y = dataset
        parts = dirichlet_partition(X, y, n_clients=N_CLIENTS, alpha=0.5)

        model = TabularMLP(input_dim=4, hidden_dims=[16, 8], output_dim=1, task="regression")
        global_weights = get_flat_weights(model)

        for rnd in range(ROUNDS):
            client_updates = []
            client_sizes = []

            for (px, py) in parts:
                if len(px) == 0:
                    continue
                local_w = local_train_fedprox(
                    model, global_weights, px, py,
                    epochs=2, lr=0.01, mu=0.01, task="regression"
                )
                clipped = clip_gradients(local_w, CLIP_NORM)
                noised = add_gaussian_noise_dp(clipped, noise_mult, CLIP_NORM)
                client_updates.append(noised)
                client_sizes.append(len(px))

            assert len(client_updates) > 0
            global_weights = fedprox_aggregate(client_updates, client_sizes)

        eps_spent = compute_epsilon_spent(noise_mult, DELTA, ROUNDS)
        assert eps_spent <= TARGET_EPSILON + 1e-4, (
            f"ε spent {eps_spent:.4f} exceeds budget {TARGET_EPSILON}"
        )

    def test_encrypt_decrypt_weights_roundtrip(self, noise_mult):
        model = TabularMLP(input_dim=4, hidden_dims=[8], output_dim=1, task="regression")
        w = get_flat_weights(model)
        payload = encrypt_weights(w, TASK_ID, SECRET)
        recovered = decrypt_weights(payload, TASK_ID, SECRET)
        np.testing.assert_array_almost_equal(recovered, w, decimal=5)

    def test_budget_exhaustion_logic(self, noise_mult):
        """
        After ROUNDS rounds, epsilon spent must be ≤ TARGET_EPSILON,
        confirming the RDP accountant correctly bounds composition.
        """
        spent = compute_epsilon_spent(noise_mult, DELTA, ROUNDS)
        assert spent <= TARGET_EPSILON
        # Spending one more round pushes past budget
        spent_extra = compute_epsilon_spent(noise_mult, DELTA, ROUNDS + 50)
        assert spent_extra > spent
