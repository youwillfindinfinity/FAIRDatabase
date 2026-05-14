import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest
from src.federated.fl_privacy import compute_noise_multiplier, compute_epsilon_spent


class TestComputeNoiseMult:
    def test_returns_positive_float(self):
        nm = compute_noise_multiplier(epsilon=1.0, delta=1e-5, rounds=10)
        assert isinstance(nm, float)
        assert nm > 0

    def test_larger_epsilon_gives_smaller_noise_mult(self):
        """More permissive budget → less noise needed."""
        nm_tight = compute_noise_multiplier(epsilon=0.5, delta=1e-5, rounds=10)
        nm_loose = compute_noise_multiplier(epsilon=5.0, delta=1e-5, rounds=10)
        assert nm_loose < nm_tight

    def test_more_rounds_require_more_noise(self):
        """Same budget spread over more rounds → each round needs more noise."""
        nm_few = compute_noise_multiplier(epsilon=1.0, delta=1e-5, rounds=5)
        nm_many = compute_noise_multiplier(epsilon=1.0, delta=1e-5, rounds=50)
        assert nm_many > nm_few


class TestComputeEpsilonSpent:
    def test_zero_rounds_spends_zero(self):
        eps = compute_epsilon_spent(noise_multiplier=1.0, delta=1e-5, rounds_done=0)
        assert eps == 0.0

    def test_spent_increases_with_rounds(self):
        eps_5 = compute_epsilon_spent(noise_multiplier=1.0, delta=1e-5, rounds_done=5)
        eps_10 = compute_epsilon_spent(noise_multiplier=1.0, delta=1e-5, rounds_done=10)
        assert eps_10 > eps_5

    def test_roundtrip_consistency(self):
        """
        If we compute noise_mult to satisfy ε=1.0 over 10 rounds,
        spending 10 rounds must return ε ≤ 1.0.
        """
        nm = compute_noise_multiplier(epsilon=1.0, delta=1e-5, rounds=10)
        spent = compute_epsilon_spent(noise_multiplier=nm, delta=1e-5, rounds_done=10)
        assert spent <= 1.0 + 1e-4  # small tolerance for float search
