import pandas as pd
from AnonyBiome.anonymization.p_29 import P_29_score


def test_score_decreases_as_t_increases():
    """A dataset with lower t must score higher than one with higher t."""
    # Low-t: each group has the same mix as global → t≈0
    df_low_t = pd.DataFrame({
        "age":     [25, 25, 30, 30],
        "disease": ["flu", "cold", "flu", "cold"],
    })
    # High-t: each group is homogeneous → t=0.5
    df_high_t = pd.DataFrame({
        "age":     [25, 25, 25, 30, 30, 30],
        "disease": ["flu", "flu", "flu", "cold", "cold", "cold"],
    })
    score_low = P_29_score(df_low_t, ["age"], ["disease"]).score
    score_high = P_29_score(df_high_t, ["age"], ["disease"]).score
    assert score_low > score_high, (
        f"Low-t dataset should score higher: low={score_low:.4f} high={score_high:.4f}"
    )


def test_uniform_nonzero_t_does_not_inflate_score():
    """
    When all groups share the same non-zero t-score, the w_t term must
    reflect the actual t value, not degenerate to 0 (which would give
    the full w_t=0.25 weight regardless of how close t is to threshold).

    Dataset: two groups with mirror-image numeric salary distributions.
    Global distribution is uniform over {10, 20, 30, 40}.
    Each group's EMD t-score is exactly 1/6 ≈ 0.167 — identical and non-zero.
    All privacy checks pass (k=2, l>0, t<0.5), so score > 0.

    Correct score uses mean_t=0.167: w_t*(1-0.167) ≈ 0.208  → total ≈ 0.583
    Buggy score uses mean_t=0.0:    w_t*(1-0.0)   = 0.250  → total ≈ 0.625
    """
    df = pd.DataFrame({
        "age":    [25, 25, 30, 30],
        "salary": [10, 30, 20, 40],
    })
    result = P_29_score(df, ["age"], ["salary"])
    assert result.score > 0, f"Expected non-zero score, got {result.score} (reasons: {result.reasons})"
    # Degenerate normalization would give score ≈ 0.625; correct is ≈ 0.583
    # Use 0.61 as a safe threshold that separates the two.
    assert result.score < 0.61, (
        f"Score={result.score:.4f} appears inflated by degenerate t normalization "
        f"(expected < 0.61 with mean_t≈0.167)"
    )
