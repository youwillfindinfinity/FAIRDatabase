"""
fl_privacy.py — RDP (Rényi Differential Privacy) accountant for the FL module.

Uses Google's dp-accounting library for tight privacy budget composition
across federated learning rounds. This replaces naive ε/rounds composition,
which is mathematically incorrect.
"""
from dp_accounting import dp_event
from dp_accounting.rdp import rdp_privacy_accountant


def _make_accountant(noise_multiplier: float, rounds: int) -> rdp_privacy_accountant.RdpAccountant:
    accountant = rdp_privacy_accountant.RdpAccountant()
    if rounds > 0:
        accountant.compose(
            dp_event.SelfComposedDpEvent(
                dp_event.GaussianDpEvent(noise_multiplier=noise_multiplier),
                count=rounds,
            )
        )
    return accountant


def compute_noise_multiplier(
    epsilon: float,
    delta: float,
    rounds: int,
) -> float:
    """
    Binary-search for the smallest noise_multiplier σ/C such that running
    `rounds` Gaussian mechanism steps satisfies (ε, δ)-DP.

    Call this once at FL task creation and store the result in fl_tasks.dp_noise_mult.
    Use the stored value every round — no per-round recomputation.
    """
    if rounds == 0:
        return float("inf")

    low, high = 0.01, 1000.0
    for _ in range(64):
        mid = (low + high) / 2.0
        accountant = _make_accountant(mid, rounds)
        eps = accountant.get_epsilon(target_delta=delta)
        if eps <= epsilon:
            high = mid
        else:
            low = mid
    return high


def compute_epsilon_spent(
    noise_multiplier: float,
    delta: float,
    rounds_done: int,
) -> float:
    """
    Return the actual ε consumed after `rounds_done` rounds with the given
    noise_multiplier. Used to update fl_epsilon_budget after each round.
    """
    if rounds_done == 0:
        return 0.0
    accountant = _make_accountant(noise_multiplier, rounds_done)
    return accountant.get_epsilon(target_delta=delta)
