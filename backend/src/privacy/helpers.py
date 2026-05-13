"""Functions for applying local differential privacy noise to data columns."""

import math
import numpy as np


def add_randomized_response(value, categories, epsilon):
    """
    Apply randomized response satisfying ε-Local Differential Privacy.

    Retention probability: p = e^ε / (e^ε + k - 1), where k = len(categories).
    When randomising, the replacement is drawn uniformly from the remaining
    k-1 categories (excluding the original value) so that the empirical
    retention rate equals p exactly.
    """
    k = len(categories)
    p = math.exp(epsilon) / (math.exp(epsilon) + k - 1)
    if np.random.random() < p:
        return value
    others = [c for c in categories if c != value]
    return np.random.choice(others) if others else value


def add_laplace_noise(column, sensitivity, epsilon):
    """
    Add Laplace noise to a numerical column (ε-differential privacy).

    :raises ValueError: if epsilon <= 0.
    """
    if epsilon <= 0:
        raise ValueError(f"epsilon must be positive, got {epsilon}")
    scale = sensitivity / epsilon
    noise = np.random.laplace(loc=0, scale=scale, size=column.shape)
    return column + noise


def add_noise_to_df(df, categorical_columns, numerical_columns, epsilon):
    """
    Add noise to a DataFrame based on local differential privacy.

    Numerical columns receive Laplace noise; categorical columns receive
    randomized response. Both mechanisms use the provided epsilon value.
    """
    noisy_df = df.copy()

    for column in numerical_columns:
        sensitivity = df[column].max() - df[column].min()
        noisy_df[column] = add_laplace_noise(df[column], sensitivity, epsilon)

    for column in categorical_columns:
        categories = df[column].unique().tolist()
        noisy_df[column] = df[column].apply(
            lambda x: add_randomized_response(x, categories, epsilon)
        )

    return noisy_df


def validate_column_selection(columns, categorical_cols, numerical_cols):
    """
    Validate that the selected categorical and numerical columns are correct.

    Returns True if selection is valid: all selected columns exist in the
    dataset and no column appears in both lists.
    """
    selected_cols = categorical_cols + numerical_cols
    return set(selected_cols).issubset(set(columns)) and (
        len(set(categorical_cols).intersection(numerical_cols)) == 0
    )
