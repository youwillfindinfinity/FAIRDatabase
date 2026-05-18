import pandas as pd
import numpy as np
from AnonyBiome.anonymization.utils.helpers import (
    compute_numeric_t_closeness,
    compute_categorical_t_closeness,
)


def test_numeric_t_closeness_uses_emd_not_tvd():
    """
    EMD and TVD give different values for numeric data with ordering effects.

    Setup: two groups, global distribution over {10, 20, 30, 40}.
    age=25 group: only salary=10 (all mass at the lowest value)
    age=30 group: only salary=40 (all mass at the highest value)
    Global: salary in {10,20,30,40} each with prob 0.25

    TVD for age=25: 0.5*(|1-0.25|+|0-0.25|+|0-0.25|+|0-0.25|) = 0.5*1.25 = 0.625
    EMD for age=25: (1/3)*(|CDF_group - CDF_global| summed over 4 points)
      CDF_global = [0.25, 0.50, 0.75, 1.00]
      CDF_group  = [1.00, 1.00, 1.00, 1.00]
      |diffs|    = [0.75, 0.50, 0.25, 0.00]
      EMD = (0.75+0.50+0.25+0.00) / 3 = 1.5/3 = 0.5

    EMD (0.5) != TVD (0.625) — they differ, so we can distinguish them.
    """
    df = pd.DataFrame({
        "age":    [25, 25, 30, 30, 35, 35, 40, 40],
        "salary": [10, 10, 40, 40, 20, 20, 30, 30],
    })
    scores = compute_numeric_t_closeness(df, ["age"], "salary")
    t_age25 = scores["age: 25"]
    # Expected EMD for age=25 (only value 10, global uniform over {10,20,30,40})
    # CDF_global=[0.25,0.50,0.75,1.0], CDF_group=[1,1,1,1]
    # EMD = (0.75+0.50+0.25+0.0)/3 = 0.5
    expected_emd = 0.5
    expected_tvd = 0.625
    assert abs(t_age25 - expected_emd) < 1e-9, (
        f"Expected EMD={expected_emd}, got {t_age25:.6f}. "
        f"(TVD would be {expected_tvd})"
    )


def test_numeric_t_closeness_zero_when_group_matches_global():
    """When a group's distribution matches global, t must be 0."""
    df = pd.DataFrame({
        "age":    [25, 25, 25, 25],
        "salary": [10, 20, 30, 40],
    })
    scores = compute_numeric_t_closeness(df, ["age"], "salary")
    assert abs(scores["age: 25"]) < 1e-9


def test_categorical_t_closeness_unchanged():
    """Categorical t-closeness must still use TVD."""
    df = pd.DataFrame({
        "age":     [25, 25, 30, 30],
        "disease": ["flu", "flu", "cold", "cold"],
    })
    scores = compute_categorical_t_closeness(df, ["age"], "disease")
    # age=25: flu=1.0, cold=0.0 vs global flu=0.5, cold=0.5
    # TVD = 0.5*(|1-0.5|+|0-0.5|) = 0.5
    assert abs(scores["age: 25"] - 0.5) < 1e-9
