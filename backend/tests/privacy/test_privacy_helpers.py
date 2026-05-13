import math
import numpy as np
import pandas as pd
import pytest
import sys
sys.path.insert(0, '/home/rbumbuc/codes/FAIRDatabase/.worktrees/demo-backend/backend')
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
