"""Privacy primitives for plugins. See ``docs/PLUGIN_GUIDE.md`` §2.

Bundles three families behind one namespace:

  * disclosure metrics  — k-anonymity, l-diversity (entropy), t-closeness, P(29)
  * local DP mechanisms — Laplace / randomized-response noise, L2 clipping
  * DP accounting       — RDP-based ε / noise-multiplier composition (FL)
"""
from AnonyBiome.anonymization.enforce_privacy import enforce_privacy
from AnonyBiome.anonymization.k_anonymity import k_anonymity_for_sensitive_attr
from AnonyBiome.anonymization.normalized_entropy import (
    normalized_entropy_for_sensitive_attr,
)
from AnonyBiome.anonymization.p_29 import P_29_score
from AnonyBiome.anonymization.t_closeness import t_closeness_for_sensitive_attr

from src.privacy.helpers import (
    add_gaussian_noise_dp,
    add_laplace_noise,
    add_noise_to_df,
    add_randomized_response,
    clip_gradients,
)

# RDP-based DP accounting — physically relocated into the kernel in Phase 5
# (was src/federated/fl_privacy.py).
from kernel.rdp_accountant import compute_epsilon_spent, compute_noise_multiplier

__all__ = [
    # disclosure metrics
    "k_anonymity_for_sensitive_attr",
    "normalized_entropy_for_sensitive_attr",
    "t_closeness_for_sensitive_attr",
    "P_29_score",
    "enforce_privacy",
    # local DP mechanisms
    "add_randomized_response",
    "add_laplace_noise",
    "add_noise_to_df",
    "clip_gradients",
    "add_gaussian_noise_dp",
    # DP accounting
    "compute_noise_multiplier",
    "compute_epsilon_spent",
]
