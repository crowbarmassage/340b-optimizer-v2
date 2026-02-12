"""Loading dose calculation logic for biologics (Gold Layer).

This module handles Year 1 vs Maintenance dosing calculations for biologics
that have loading dose regimens. Loading doses significantly increase
Year 1 revenue compared to subsequent maintenance years.

Gatekeeper Test: Loading Dose Logic Test
- Select Cosentyx (Psoriasis): Year 1 = 17 fills, Maintenance = 12 fills
- Year 1 Revenue should reflect the higher fill count

Example: Cosentyx for Psoriasis
- Year 1: 5 loading doses (weeks 0,1,2,3,4) + 12 monthly = 17 fills
- Year 2+: 12 monthly maintenance doses = 12 fills
"""

import logging
from decimal import Decimal

import polars as pl

from optimizer_340b.models import DosingProfile

logger = logging.getLogger(__name__)

# Default compliance rate for fill adjustments
DEFAULT_COMPLIANCE_RATE = Decimal("0.90")


def apply_loading_dose_logic(
    drug_name: str,
    dosing_grid: pl.DataFrame,
    indication: str | None = None,
    compliance_rate: Decimal = DEFAULT_COMPLIANCE_RATE,
) -> DosingProfile | None:
    """Look up loading dose profile for a drug.

    Args:
        drug_name: Name of the drug to look up.
        dosing_grid: Biologics logic grid DataFrame with columns:
            - Drug Name
            - Indication
            - Year 1 Fills
            - Year 2+ Fills
        indication: Specific indication (uses first match if None).
        compliance_rate: Expected patient compliance rate (0.0-1.0).

    Returns:
        DosingProfile if drug found, None otherwise.
    """
    # Validate input
    if dosing_grid.height == 0:
        logger.warning("Empty dosing grid provided")
        return None

    required_cols = {"Drug Name", "Year 1 Fills"}
    if not required_cols.issubset(set(dosing_grid.columns)):
        logger.warning(f"Dosing grid missing required columns: {required_cols}")
        return None

    # Filter to matching drug (case-insensitive)
    matches = dosing_grid.filter(
        pl.col("Drug Name").str.to_uppercase() == drug_name.upper()
    )

    if matches.height == 0:
        logger.debug(f"No dosing profile found for {drug_name}")
        return None

    # Filter by indication if specified
    if indication is not None and "Indication" in matches.columns:
        indication_matches = matches.filter(pl.col("Indication") == indication)
        if indication_matches.height > 0:
            matches = indication_matches
        else:
            logger.debug(
                f"No dosing profile for {drug_name} / {indication}, "
                f"using first available"
            )

    # Take first match
    row = matches.row(0, named=True)

    # Extract fill counts with defaults
    year_1_fills = int(row.get("Year 1 Fills", 12) or 12)
    year_2_fills = int(row.get("Year 2+ Fills", year_1_fills) or year_1_fills)

    # Apply compliance adjustment to Year 1
    adjusted = Decimal(str(year_1_fills)) * compliance_rate

    profile = DosingProfile(
        drug_name=drug_name,
        indication=row.get("Indication", "Unknown") or "Unknown",
        year_1_fills=year_1_fills,
        year_2_plus_fills=year_2_fills,
        adjusted_year_1_fills=adjusted,
    )

    logger.info(
        f"Dosing profile for {drug_name}: "
        f"Year 1 = {year_1_fills} fills, "
        f"Maintenance = {year_2_fills} fills, "
        f"Adjusted = {adjusted} @ {compliance_rate:.0%} compliance"
    )

    return profile


def calculate_year_1_vs_maintenance_delta(
    dosing_profile: DosingProfile,
    margin_per_fill: Decimal,
) -> dict[str, Decimal]:
    """Calculate the revenue delta between Year 1 and Maintenance.

    This quantifies the "patient acquisition opportunity" from loading doses.
    Drugs with significant loading doses (e.g., Cosentyx) generate much more
    revenue in Year 1 than subsequent years.

    Args:
        dosing_profile: Dosing profile with fill counts.
        margin_per_fill: Net margin per fill/administration.

    Returns:
        Dictionary with:
        - year_1_revenue: Total Year 1 revenue (adjusted fills × margin)
        - maintenance_revenue: Annual maintenance revenue
        - loading_dose_delta: Dollar difference (Year 1 - Maintenance)
        - loading_dose_delta_pct: Percentage increase in Year 1
    """
    year_1 = dosing_profile.year_1_revenue(margin_per_fill)
    maintenance = dosing_profile.maintenance_revenue(margin_per_fill)
    delta = year_1 - maintenance

    delta_pct = (delta / maintenance * 100) if maintenance > 0 else Decimal("0")

    result = {
        "year_1_revenue": year_1,
        "maintenance_revenue": maintenance,
        "loading_dose_delta": delta,
        "loading_dose_delta_pct": delta_pct,
    }

    logger.debug(
        f"Loading dose delta for {dosing_profile.drug_name}: "
        f"Year 1 ${year_1:.2f} vs Maintenance ${maintenance:.2f} = "
        f"${delta:.2f} ({delta_pct:.1f}% increase)"
    )

    return result


def calculate_lifetime_value(
    dosing_profile: DosingProfile,
    margin_per_fill: Decimal,
    years: int = 5,
) -> dict[str, Decimal]:
    """Calculate patient lifetime value over multiple years.

    Args:
        dosing_profile: Dosing profile with fill counts.
        margin_per_fill: Net margin per fill/administration.
        years: Number of years to project (default 5).

    Returns:
        Dictionary with year-by-year and cumulative values.
    """
    year_1 = dosing_profile.year_1_revenue(margin_per_fill)
    maintenance = dosing_profile.maintenance_revenue(margin_per_fill)

    # Year 1 + (years-1) maintenance years
    maintenance_years = years - 1
    total = year_1 + (maintenance * maintenance_years)

    return {
        "year_1": year_1,
        "annual_maintenance": maintenance,
        "total_years": Decimal(str(years)),
        "lifetime_value": total,
        "average_annual": total / years,
    }


def find_high_loading_drugs(
    dosing_grid: pl.DataFrame,
    min_delta_pct: float = 20.0,
) -> pl.DataFrame:
    """Find drugs with significant loading dose impact.

    Args:
        dosing_grid: Biologics logic grid DataFrame.
        min_delta_pct: Minimum Year 1 vs Maintenance delta percentage.

    Returns:
        DataFrame of drugs with loading dose delta >= threshold.
    """
    required_cols = {"Drug Name", "Year 1 Fills", "Year 2+ Fills"}
    if not required_cols.issubset(set(dosing_grid.columns)):
        logger.warning("Dosing grid missing columns for loading dose analysis")
        return pl.DataFrame()

    # Calculate delta percentage
    result = dosing_grid.with_columns(
        (
            (pl.col("Year 1 Fills") - pl.col("Year 2+ Fills"))
            / pl.col("Year 2+ Fills")
            * 100
        ).alias("loading_delta_pct")
    ).filter(pl.col("loading_delta_pct") >= min_delta_pct)

    return result.sort("loading_delta_pct", descending=True)


def load_biologics_grid(file_path: str) -> pl.DataFrame:
    """Load biologics logic grid from Excel file.

    Expected columns:
    - Drug Name
    - Indication
    - Year 1 Fills
    - Year 2+ Fills

    Args:
        file_path: Path to biologics_logic_grid.xlsx.

    Returns:
        DataFrame with dosing information.
    """
    import pandas as pd

    logger.info(f"Loading biologics grid from {file_path}")

    pdf = pd.read_excel(file_path, engine="openpyxl")
    df = pl.from_pandas(pdf)

    # Standardize column names
    column_map = {
        "Drug": "Drug Name",
        "drug_name": "Drug Name",
        "Year 1": "Year 1 Fills",
        "Year1": "Year 1 Fills",
        "Year 2": "Year 2+ Fills",
        "Year2": "Year 2+ Fills",
        "Maintenance": "Year 2+ Fills",
    }

    for old_name, new_name in column_map.items():
        if old_name in df.columns and new_name not in df.columns:
            df = df.rename({old_name: new_name})

    logger.info(f"Loaded {df.height} drug dosing profiles")
    return df
