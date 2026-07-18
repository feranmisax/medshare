"""
Shared seasonal-demand logic (Chapter 3, §3.1.7).

seasonal_index is a real, category- and month-varying multiplier — NOT a global
constant. Both the data generator (when simulating demand) and the feature
builder (when scoring/ training Model 1) import THIS function, so the feature the
model learns from is exactly the driver used to generate demand.

A value > 1.0 means demand for that category is seasonally elevated in that month
(e.g. antimalarials in the rainy season); < 1.0 means seasonally depressed.
"""
import pandas as pd
import config


def seasonal_index(category: str, when) -> float:
    """Return the seasonal demand multiplier for a drug category in a given month.

    Parameters
    ----------
    category : str   drug category (e.g. "Antimalarials")
    when     : date-like  any timestamp/date; only its month is used
    """
    month = pd.Timestamp(when).month
    table = config.SEASONAL_BY_CATEGORY.get(category, {})
    return float(table.get(month, 1.0))
