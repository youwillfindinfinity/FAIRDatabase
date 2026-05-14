import pandas as pd
from AnonyBiome.anonymization.checks.validators import validate_privacy


def _make_k_df(val=2):
    return pd.DataFrame({"k-anonymity": [val]}, index=["age: 25"])


def _make_t_df(val=0.0):
    return pd.DataFrame({"disease": [val]}, index=["age: 25"])


def test_min_l_uses_first_column():
    """min_l must reflect the first sensitive attribute, not skip it."""
    l_df = pd.DataFrame({"disease": [0.0]}, index=["age: 25"])
    result = validate_privacy(_make_k_df(), l_df, _make_t_df())
    assert result.min_l == 0.0
    assert any("l-value" in r for r in result.reasons), (
        f"l-diversity violation not detected; reasons={result.reasons}"
    )


def test_min_l_two_columns_first_is_zero():
    """When two sensitive attrs exist and the first is 0, violation is caught."""
    l_df = pd.DataFrame(
        {"disease": [0.0], "salary": [0.8]}, index=["age: 25"]
    )
    result = validate_privacy(_make_k_df(), l_df, _make_t_df())
    assert result.min_l == 0.0
    assert any("l-value" in r for r in result.reasons)
