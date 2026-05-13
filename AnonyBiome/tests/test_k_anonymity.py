import pandas as pd
from AnonyBiome.anonymization.k_anonymity import k_anonymity_for_sensitive_attr


def test_group_key_format():
    """Group keys must be 'col: val, col: val' — not 'val: col'."""
    df = pd.DataFrame({
        "age": [25, 25, 30, 30],
        "sex": ["M", "M", "F", "F"],
        "disease": ["flu", "cold", "flu", "cold"],
    })
    result = k_anonymity_for_sensitive_attr(df, ["age", "sex"])
    keys = list(result.index)
    assert any(k.startswith("age:") for k in keys), f"Bad keys: {keys}"


def test_k_value_is_group_size():
    """k-anonymity value must equal the size of each equivalence class."""
    df = pd.DataFrame({
        "age": [25, 25, 30, 30, 30],
        "disease": ["flu", "cold", "flu", "cold", "flu"],
    })
    result = k_anonymity_for_sensitive_attr(df, ["age"])
    assert result.loc["age: 25", "k-anonymity"] == 2
    assert result.loc["age: 30", "k-anonymity"] == 3


def test_enforce_privacy_merge_uses_consistent_keys():
    """enforce_privacy must not return 0 rows for a compliant dataset."""
    from AnonyBiome.anonymization.enforce_privacy import enforce_privacy
    df = pd.DataFrame({
        "age":     [25, 25, 25, 30, 30, 30],
        "sex":     ["M", "M", "M", "F", "F", "F"],
        "disease": ["flu", "cold", "flu", "cold", "flu", "cold"],
    })
    filtered = enforce_privacy(df, ["age", "sex"], ["disease"])
    assert len(filtered) == 6, f"Expected 6 rows, got {len(filtered)}"
