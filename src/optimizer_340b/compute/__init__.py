"""Computation module for 340B Optimizer (Gold Layer).

This module handles:
- Margin calculations (Retail, Medicare, Commercial)
- Pathway recommendation logic
- Loading dose calculations for biologics
"""

from optimizer_340b.compute.dosing import (
    DEFAULT_COMPLIANCE_RATE,
    apply_loading_dose_logic,
    calculate_lifetime_value,
    calculate_year_1_vs_maintenance_delta,
    find_high_loading_drugs,
    load_biologics_grid,
)
from optimizer_340b.compute.margins import (
    AWP_DISCOUNT_FACTOR,
    COMMERCIAL_ASP_MULTIPLIER,
    DEFAULT_CAPTURE_RATE,
    MEDICARE_ASP_MULTIPLIER,
    analyze_drug_margin,
    analyze_drug_with_payer,
    calculate_commercial_margin,
    calculate_margin_sensitivity,
    calculate_medicare_margin,
    calculate_retail_margin,
    determine_recommendation,
)

__all__ = [
    # Margin calculation
    "calculate_retail_margin",
    "calculate_medicare_margin",
    "calculate_commercial_margin",
    "determine_recommendation",
    "analyze_drug_margin",
    "analyze_drug_with_payer",
    "calculate_margin_sensitivity",
    # Constants
    "AWP_DISCOUNT_FACTOR",
    "MEDICARE_ASP_MULTIPLIER",
    "COMMERCIAL_ASP_MULTIPLIER",
    "DEFAULT_CAPTURE_RATE",
    "DEFAULT_COMPLIANCE_RATE",
    # Dosing
    "apply_loading_dose_logic",
    "calculate_year_1_vs_maintenance_delta",
    "calculate_lifetime_value",
    "find_high_loading_drugs",
    "load_biologics_grid",
]
