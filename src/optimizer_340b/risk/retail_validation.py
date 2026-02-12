"""Retail price validation using wholesaler catalog data.

This module implements the Market Validator (Archetype H) from the
Proprietary Data Manifest:
- Validates calculated retail revenue against real-world pricing
- Flags records where calculated vs actual differ by >20%
- Adds Retail_Confidence flag (High/Low) to output

Source: wholesaler_catalog.xlsx
Key Column: Product Catalog Unit Price (Current Retail) Average
"""

import logging
from dataclasses import dataclass
from decimal import Decimal

import polars as pl

logger = logging.getLogger(__name__)

# Threshold for flagging retail confidence as "Low"
RETAIL_VARIANCE_THRESHOLD = Decimal("0.20")  # 20%


def _normalize_ndc(ndc: str) -> str:
    """Normalize NDC to 11-digit format, preserving leading zeros.

    Args:
        ndc: Raw NDC string.

    Returns:
        11-digit normalized NDC string.
    """
    if ndc is None:
        return ""
    cleaned = str(ndc).replace("-", "").replace(" ", "").strip()
    return cleaned.zfill(11)[-11:]


@dataclass
class RetailValidationResult:
    """Result of retail price validation.

    Attributes:
        ndc: NDC of the drug.
        calculated_retail: Calculated retail revenue.
        actual_retail: Actual retail from wholesaler catalog.
        variance_pct: Percentage difference (as decimal).
        confidence: "High" if variance <= 20%, "Low" otherwise.
        is_valid: Whether the drug passed validation.
    """

    ndc: str
    calculated_retail: Decimal | None
    actual_retail: Decimal | None
    variance_pct: Decimal | None
    confidence: str
    is_valid: bool


def load_wholesaler_catalog(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize wholesaler catalog for retail validation.

    Args:
        df: Raw wholesaler catalog DataFrame.

    Returns:
        Normalized DataFrame with standard column names.
    """
    logger.info(f"Loading wholesaler catalog with {df.height} rows")

    # Column mapping for wholesaler catalog
    column_map = {
        "Product Catalog NDC": "NDC",
        "Product Catalog Unit Price (Current Retail) Average": "actual_retail",
        "Product Catalog Generic Name": "Generic Name",
        "Product Catalog Trade Name": "Trade Name",
        "Product Catalog Manufacturer": "Manufacturer",
        "Product Catalog Medispan AWP": "AWP",
    }

    # Rename columns that exist
    renames = {}
    for old_name, new_name in column_map.items():
        if old_name in df.columns:
            renames[old_name] = new_name

    if renames:
        df = df.rename(renames)

    # Normalize NDC column
    if "NDC" in df.columns:
        df = df.with_columns(
            pl.col("NDC")
            .map_elements(_normalize_ndc, return_dtype=pl.String)
            .alias("ndc_normalized")
        )

    # Ensure actual_retail is numeric
    if "actual_retail" in df.columns:
        df = df.with_columns(
            pl.col("actual_retail")
            .cast(pl.Float64, strict=False)
            .alias("actual_retail")
        )

    return df


def build_retail_validation_lookup(
    wholesaler_df: pl.DataFrame,
) -> dict[str, Decimal]:
    """Build NDC to actual retail price lookup.

    Args:
        wholesaler_df: Normalized wholesaler catalog DataFrame.

    Returns:
        Dictionary mapping normalized NDC to actual retail price.
    """
    lookup: dict[str, Decimal] = {}

    ndc_col = "ndc_normalized" if "ndc_normalized" in wholesaler_df.columns else "NDC"
    retail_col = "actual_retail"

    if ndc_col not in wholesaler_df.columns or retail_col not in wholesaler_df.columns:
        logger.warning("Required columns not found for retail validation lookup")
        return lookup

    for row in wholesaler_df.iter_rows(named=True):
        ndc = row.get(ndc_col)
        retail = row.get(retail_col)

        if ndc and retail is not None and retail > 0:
            lookup[str(ndc)] = Decimal(str(retail))

    logger.info(f"Built retail validation lookup with {len(lookup)} NDCs")
    return lookup


def validate_retail_price(
    ndc: str,
    calculated_retail: Decimal,
    retail_lookup: dict[str, Decimal],
) -> RetailValidationResult:
    """Validate calculated retail against wholesaler catalog.

    Gatekeeper Test: If calculated differs from actual by >20%,
    flag with Retail_Confidence = Low.

    Args:
        ndc: NDC of the drug (will be normalized).
        calculated_retail: Calculated retail revenue/price.
        retail_lookup: Lookup dict from build_retail_validation_lookup().

    Returns:
        RetailValidationResult with validation details.
    """
    ndc_normalized = _normalize_ndc(ndc)
    actual_retail = retail_lookup.get(ndc_normalized)

    # No actual retail available - cannot validate
    if actual_retail is None:
        return RetailValidationResult(
            ndc=ndc,
            calculated_retail=calculated_retail,
            actual_retail=None,
            variance_pct=None,
            confidence="Unknown",
            is_valid=True,  # Don't fail validation if no benchmark
        )

    # Calculate variance percentage
    if actual_retail == 0:
        variance_pct = Decimal("1.0") if calculated_retail > 0 else Decimal("0")
    else:
        variance_pct = abs(calculated_retail - actual_retail) / actual_retail

    # Determine confidence
    is_low_confidence = variance_pct > RETAIL_VARIANCE_THRESHOLD
    confidence = "Low" if is_low_confidence else "High"

    if is_low_confidence:
        logger.warning(
            f"Low retail confidence for NDC {ndc}: "
            f"calculated=${calculated_retail:.2f} vs actual=${actual_retail:.2f} "
            f"(variance: {variance_pct:.1%})"
        )

    return RetailValidationResult(
        ndc=ndc,
        calculated_retail=calculated_retail,
        actual_retail=actual_retail,
        variance_pct=variance_pct,
        confidence=confidence,
        is_valid=not is_low_confidence,
    )


def validate_batch_retail(
    drugs_df: pl.DataFrame,
    retail_lookup: dict[str, Decimal],
    ndc_col: str = "ndc_normalized",
    calculated_col: str = "retail_revenue",
) -> pl.DataFrame:
    """Validate retail prices for a batch of drugs.

    Adds columns:
    - actual_retail: From wholesaler catalog
    - retail_variance_pct: Percentage difference
    - retail_confidence: "High" or "Low"

    Args:
        drugs_df: DataFrame with drug data.
        retail_lookup: Lookup dict from wholesaler catalog.
        ndc_col: Column containing NDC.
        calculated_col: Column containing calculated retail revenue.

    Returns:
        DataFrame with validation columns added.
    """
    if ndc_col not in drugs_df.columns:
        logger.warning(f"NDC column '{ndc_col}' not found in DataFrame")
        return drugs_df

    if calculated_col not in drugs_df.columns:
        logger.warning(f"Calculated retail column '{calculated_col}' not found")
        return drugs_df

    # Add validation columns
    actual_values = []
    variance_values = []
    confidence_values = []

    for row in drugs_df.iter_rows(named=True):
        ndc = str(row.get(ndc_col, ""))
        calculated = row.get(calculated_col)

        if calculated is None:
            actual_values.append(None)
            variance_values.append(None)
            confidence_values.append("Unknown")
            continue

        result = validate_retail_price(
            ndc, Decimal(str(calculated)), retail_lookup
        )

        actual_values.append(
            float(result.actual_retail) if result.actual_retail else None
        )
        variance_values.append(
            float(result.variance_pct) if result.variance_pct else None
        )
        confidence_values.append(result.confidence)

    # Add new columns
    result_df = drugs_df.with_columns([
        pl.Series("actual_retail", actual_values),
        pl.Series("retail_variance_pct", variance_values),
        pl.Series("retail_confidence", confidence_values),
    ])

    # Log summary statistics
    high_confidence = sum(1 for c in confidence_values if c == "High")
    low_confidence = sum(1 for c in confidence_values if c == "Low")
    unknown = sum(1 for c in confidence_values if c == "Unknown")

    logger.info(
        f"Retail validation: {high_confidence} High, "
        f"{low_confidence} Low, {unknown} Unknown confidence"
    )

    return result_df
