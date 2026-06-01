import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import pytest
import torch
from plugins.horizontal_fl.engine import (
    TabularMLP,
    get_flat_weights,
    set_flat_weights,
    local_train_fedprox,
    fedprox_aggregate,
    dirichlet_partition,
)


class TestTabularMLP:
    def test_forward_shape_regression(self):
        model = TabularMLP(input_dim=4, hidden_dims=[16, 8], output_dim=1, task="regression")
        x = torch.randn(10, 4)
        out = model(x)
        assert out.shape == (10, 1)

    def test_forward_shape_classification(self):
        model = TabularMLP(input_dim=4, hidden_dims=[16], output_dim=3, task="classification")
        x = torch.randn(5, 4)
        out = model(x)
        assert out.shape == (5, 3)
        # Softmax output must sum to 1 per row
        assert torch.allclose(out.sum(dim=1), torch.ones(5), atol=1e-5)


class TestFlatWeights:
    def test_roundtrip(self):
        model = TabularMLP(input_dim=3, hidden_dims=[8], output_dim=1, task="regression")
        original = get_flat_weights(model)
        # Perturb
        set_flat_weights(model, original * 2)
        recovered_base = get_flat_weights(model)
        np.testing.assert_array_almost_equal(recovered_base, original * 2)

    def test_flat_weights_length_matches_param_count(self):
        model = TabularMLP(input_dim=2, hidden_dims=[4], output_dim=1, task="regression")
        n_params = sum(p.numel() for p in model.parameters())
        assert len(get_flat_weights(model)) == n_params


class TestFedProxLocalTrain:
    def test_weights_change_after_training(self):
        model = TabularMLP(input_dim=2, hidden_dims=[8], output_dim=1, task="regression")
        global_w = get_flat_weights(model)
        X = np.random.randn(20, 2).astype(np.float32)
        y = np.random.randn(20).astype(np.float32)
        updated_w, _ = local_train_fedprox(model, global_w, X, y,
                                           epochs=5, lr=0.01, mu=0.01, task="regression")
        assert not np.allclose(updated_w, global_w)

    def test_output_shape_matches_input(self):
        model = TabularMLP(input_dim=3, hidden_dims=[4], output_dim=1, task="regression")
        global_w = get_flat_weights(model)
        X = np.random.randn(10, 3).astype(np.float32)
        y = np.random.randn(10).astype(np.float32)
        out, _ = local_train_fedprox(model, global_w, X, y,
                                     epochs=2, lr=0.01, mu=0.0, task="regression")
        assert len(out) == len(global_w)


class TestFedProxAggregate:
    def test_uniform_weights_averages_correctly(self):
        w1 = np.array([1.0, 2.0])
        w2 = np.array([3.0, 4.0])
        agg = fedprox_aggregate([w1, w2], client_sizes=[10, 10])
        np.testing.assert_array_almost_equal(agg, [2.0, 3.0])

    def test_weighted_by_client_size(self):
        w1 = np.array([0.0])
        w2 = np.array([10.0])
        agg = fedprox_aggregate([w1, w2], client_sizes=[9, 1])
        assert agg[0] == pytest.approx(1.0)


class TestDirichletPartition:
    def test_returns_n_clients_partitions(self):
        X = np.random.randn(100, 4)
        y = np.repeat([0, 1, 2, 3], 25)
        parts = dirichlet_partition(X, y, n_clients=4, alpha=0.5)
        assert len(parts) == 4

    def test_all_data_is_distributed(self):
        X = np.random.randn(200, 3)
        y = np.repeat([0, 1], 100)
        parts = dirichlet_partition(X, y, n_clients=5, alpha=1.0)
        total = sum(len(px) for px, _ in parts)
        assert total == 200

    def test_low_alpha_is_more_non_iid_than_high_alpha(self):
        """
        With low α, some clients should have nearly 0 samples of some classes.
        Measure heterogeneity by the variance of class proportions across clients.
        """
        np.random.seed(0)
        X = np.random.randn(500, 2)
        y = np.repeat([0, 1, 2, 3, 4], 100)

        def class_variance(parts, n_classes=5):
            props = []
            for px, py in parts:
                if len(py) == 0:
                    props.append([0.0] * n_classes)
                    continue
                counts = np.bincount(py.astype(int), minlength=n_classes)
                props.append(counts / len(py))
            return np.array(props).var(axis=0).mean()

        low_var = class_variance(dirichlet_partition(X, y, n_clients=5, alpha=0.1))
        high_var = class_variance(dirichlet_partition(X, y, n_clients=5, alpha=100.0))
        assert low_var > high_var
