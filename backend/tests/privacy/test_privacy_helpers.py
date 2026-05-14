import math
import numpy as np
import pandas as pd
import pytest
import sys
sys.path.insert(0, '/home/rbumbuc/codes/FAIRDatabase/.worktrees/fl-internal/backend')
from src.privacy.helpers import add_randomized_response, add_laplace_noise, add_noise_to_df


def test_randomized_response_uses_epsilon():
    """Empirical retention rate must match p = e^ε / (e^ε + k - 1)."""
    categories = ["A", "B", "C"]  # k=3
    epsilon = 1.0
    expected_p = math.exp(epsilon) / (math.exp(epsilon) + len(categories) - 1)
    np.random.seed(42)
    n = 10_000
    unchanged = sum(
        add_randomized_response("A", categories, epsilon=epsilon) == "A"
        for _ in range(n)
    )
    empirical_p = unchanged / n
    assert abs(empirical_p - expected_p) < 0.03, (
        f"Expected p≈{expected_p:.3f}, got {empirical_p:.3f} — "
        "p is likely still hardcoded"
    )


def test_laplace_noise_rejects_non_positive_epsilon():
    """epsilon <= 0 must raise ValueError."""
    col = pd.Series([1.0, 2.0, 3.0])
    with pytest.raises(ValueError, match="epsilon"):
        add_laplace_noise(col, sensitivity=1.0, epsilon=0)
    with pytest.raises(ValueError, match="epsilon"):
        add_laplace_noise(col, sensitivity=1.0, epsilon=-1.0)


def test_add_noise_to_df_shape_preserved():
    """Noisy DataFrame must have same shape and columns as input."""
    df = pd.DataFrame({"age": [25.0, 30.0], "sex": ["M", "F"]})
    noisy = add_noise_to_df(df, ["sex"], ["age"], epsilon=1.0)
    assert noisy.shape == df.shape
    assert list(noisy.columns) == list(df.columns)


from src.privacy.helpers import clip_gradients, add_gaussian_noise_dp


def test_clip_gradients_scales_down_large_vector():
    """Vectors with L2 norm > clip_norm must be scaled to exactly clip_norm."""
    w = np.array([3.0, 4.0])  # L2 norm = 5.0
    clipped = clip_gradients(w, clip_norm=1.0)
    assert abs(np.linalg.norm(clipped) - 1.0) < 1e-6


def test_clip_gradients_leaves_small_vector_unchanged():
    """Vectors already within clip_norm must be unchanged."""
    w = np.array([0.3, 0.4])  # L2 norm = 0.5
    clipped = clip_gradients(w, clip_norm=1.0)
    np.testing.assert_array_almost_equal(clipped, w)


def test_clip_gradients_handles_zero_vector():
    """Zero vector must be returned unchanged without division by zero."""
    w = np.zeros(5)
    clipped = clip_gradients(w, clip_norm=1.0)
    np.testing.assert_array_equal(clipped, w)


def test_add_gaussian_noise_dp_changes_values():
    """Noised weights must differ from original."""
    np.random.seed(0)
    w = np.ones(100)
    noised = add_gaussian_noise_dp(w, noise_mult=1.0, clip_norm=1.0)
    assert not np.allclose(noised, w)


def test_add_gaussian_noise_dp_scales_with_noise_mult():
    """Higher noise_mult must produce larger perturbations on average."""
    np.random.seed(42)
    w = np.zeros(10_000)
    low = add_gaussian_noise_dp(w, noise_mult=0.1, clip_norm=1.0)
    high = add_gaussian_noise_dp(w, noise_mult=10.0, clip_norm=1.0)
    assert np.std(high) > np.std(low)
