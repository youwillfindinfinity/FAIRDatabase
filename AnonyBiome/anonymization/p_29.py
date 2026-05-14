import pandas as pd

from AnonyBiome.anonymization.checks.validators import validate_privacy, PrivEval
from AnonyBiome.anonymization.k_anonymity import k_anonymity_for_sensitive_attr
from AnonyBiome.anonymization.t_closeness import t_closeness_for_sensitive_attr
from AnonyBiome.anonymization.normalized_entropy import (
    normalized_entropy_for_sensitive_attr,
)


def P_29_score(
    data: pd.DataFrame,
    quasi_idents: list[str],
    sens_attr: list[str],
    w_k=0.5,
    w_l=0.25,
    w_t=0.25,
) -> PrivEval:
    """
    Compute P(29) privacy score using weighted k-anonymity, l-diversity, and
    t-closeness.
    ---
    tags:
      - privacy
    parameters:
      - name: k_df
        required: true
        description: DataFrame with k-anonymity values.
      - name: l_df
        required: true
        description: DataFrame with l-diversity (entropy) values.
      - name: t_df
        required: true
        description: DataFrame with t-closeness values.
      - name: w_k
        type: number
        default: 0.5
        description: Weight for k-anonymity.
      - name: w_l
        type: number
        default: 0.25
        description: Weight for l-diversity.
      - name: w_t
        type: number
        default: 0.25
        description: Weight for t-closeness.
    returns:
      - type: object
        description: Named tuple with score, reasons, and privacy metrics.
    """
    # --- Retrieve each module ---
    k_df = k_anonymity_for_sensitive_attr(data, quasi_idents)
    l_df = normalized_entropy_for_sensitive_attr(data, quasi_idents, sens_attr)
    t_df = t_closeness_for_sensitive_attr(data, quasi_idents, sens_attr)

    # Guard: if k_df is empty (e.g. empty input data) the score is 0.
    if k_df.empty:
        return PrivEval(
            score=0.0,
            problematic_info=[],
            reasons=["dataset produced no equivalence classes"],
            min_k=0,
            min_l=0.0,
            max_t=1.0,
            t_numeric=pd.DataFrame(),
        )

    # Guard: a sensitive attribute with only one unique value globally
    # causes entropy helpers to return {} → empty l_df / t_df rows.
    # Treat those columns as zero-entropy (worst case for privacy).
    if l_df.empty or l_df.shape[0] == 0:
        l_df = pd.DataFrame(
            {col: [0.0] for col in sens_attr},
            index=k_df.index[:1] if not k_df.empty else ["all"],
        )
    if t_df.empty or t_df.shape[0] == 0:
        t_df = pd.DataFrame(
            {col: [0.0] for col in sens_attr},
            index=k_df.index[:1] if not k_df.empty else ["all"],
        )

    # --- Retrieve Privacy Evaluation information ---
    privEval: PrivEval = validate_privacy(k_df, l_df, t_df)

    t_numeric = privEval.t_numeric
    min_k = privEval.min_k

    if privEval.reasons:
        return privEval._replace(score=0.0)

    # --- Normalize remaining values ---
    numeric_l = l_df.select_dtypes(include="number")
    normalized_l = float(numeric_l.mean().mean()) if not numeric_l.empty else 0.0

    # --- Compute final score ---
    # Use raw mean t directly (already in [0,1]); per-column min-max collapses
    # to 0 when all groups share the same t-score, inflating the w_t contribution.
    mean_t = float(t_numeric.mean().mean()) if not t_numeric.empty else 0.0
    score = w_k * (1 - (1 / min_k)) + w_l * normalized_l + w_t * (1 - mean_t)

    privEval = privEval._replace(score=score)

    return privEval
