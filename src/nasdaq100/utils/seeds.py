"""Random seed management for reproducibility."""

from __future__ import annotations

import os
import random

import numpy as np


def set_global_seed(seed: int = 42) -> None:
    """Set global seeds for Python random, environment hash seed, and NumPy.

    Note: LightGBM and scikit-learn estimators receive explicit seed arguments.
    """
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    np.random.seed(seed)
