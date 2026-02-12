"""Penny Pricing and Inflation Penalty detection for 340B drugs.

Penny Pricing occurs when a drug's NADAC (National Average Drug Acquisition Cost)
is extremely low (often $0.01 or less), indicating the drug is effectively
available at near-zero cost. These drugs should NOT appear in "Top Opportunities"
because the 340B margin is already maximized with minimal room for improvement.

Implementation Logic (from Proprietary Data Manifest):
- Penny Logic: If penny_pricing == 'Yes', override Cost_Basis to $0.01
- Inflation Logic: If inflation_penalty_pct > 20%, add flag: "High Inflation Penalty"

Gatekeeper Tests:
- Drugs with Penny Pricing = Yes should NOT appear in "Top Opportunities"
- Drugs with high inflation penalty should be flagged
"""

import logging
from dataclasses import dataclass
from decimal import Decimal

import polars as pl

logger = logging.getLogger(__name__)

# Threshold below which pricing is considered "penny pricing"
PENNY_THRESHOLD = Decimal("0.10")  # $0.10 per unit

# High discount threshold for NADAC-based penny pricing detection
HIGH_DISCOUNT_THRESHOLD = Decimal("95.0")  # 95% discount indicates penny pricing

# Penny cost override value
PENNY_COST_OVERRIDE = Decimal("0.01")  # $0.01 as per manifest

# Inflation penalty threshold
INFLATION_PENALTY_THRESHOLD = Decimal("20.0")  # 20% threshold


@dataclass
class PennyPricingStatus:
    """Penny pricing assessment for a drug.

    Attributes:
        is_penny_priced: Whether the drug has penny pricing.
        ndc: NDC of the drug.
        nadac_price: NADAC price if available.
        discount_pct: 340B discount percentage from NADAC.
        warning_message: Human-readable warning.
        should_exclude: Whether to exclude from Top Opportunities.
    """

    is_penny_priced: bool
    ndc: str
    nadac_price: Decimal | None
    discount_pct: Decimal | None
    warning_message: str
    should_exclude: bool


def check_penny_pricing(nadac_df: pl.DataFrame) -> list[dict[str, object]]:
    """Check NADAC data for penny-priced drugs.

    Drugs with penny_pricing=True or extremely high discount percentages
    are flagged as having limited 340B opportunity.

    Args:
        nadac_df: NADAC DataFrame with columns:
            - ndc: Drug NDC
            - penny_pricing: Boolean flag (if available)
            - total_discount_340b_pct: Discount percentage (if available)

    Returns:
        List of flagged drugs with their penny pricing status.
    """
    flagged: list[dict[str, object]] = []

    # Check if required columns exist
    has_penny_column = "penny_pricing" in nadac_df.columns
    has_discount_column = "total_discount_340b_pct" in nadac_df.columns

    if not has_penny_column and not has_discount_column:
        logger.warning("NADAC data missing penny_pricing and discount columns")
        return flagged

    for row in nadac_df.iter_rows(named=True):
        ndc = str(row.get("ndc", ""))
        is_penny = False
        reason = ""

        # Check explicit penny_pricing flag
        if has_penny_column and row.get("penny_pricing"):
            is_penny = True
            reason = "Penny pricing flag is set"

        # Check high discount percentage
        if has_discount_column:
            discount = row.get("total_discount_340b_pct")
            if discount is not None:
                discount_decimal = Decimal(str(discount))
                if discount_decimal >= HIGH_DISCOUNT_THRESHOLD:
                    is_penny = True
                    reason = f"340B discount is {discount_decimal:.1f}%"

        if is_penny:
            flagged.append({
                "ndc": ndc,
                "is_penny_priced": True,
                "discount_pct": row.get("total_discount_340b_pct"),
                "warning_message": (
                    f"Penny Pricing Alert: {ndc} - {reason}. "
                    "This drug should NOT appear in Top Opportunities."
                ),
                "should_exclude": True,
            })

            logger.info(f"Penny pricing detected: NDC {ndc} - {reason}")

    logger.info(
        f"Found {len(flagged)} penny-priced drugs out of {nadac_df.height} total"
    )

    return flagged


def check_penny_pricing_for_drug(
    ndc: str,
    nadac_df: pl.DataFrame,
) -> PennyPricingStatus:
    """Check if a specific drug has penny pricing.

    Args:
        ndc: NDC to check.
        nadac_df: NADAC DataFrame with pricing data.

    Returns:
        PennyPricingStatus with assessment.
    """
    # Normalize NDC for matching
    ndc_clean = ndc.replace("-", "").strip()

    # Filter for matching NDC
    if "ndc" not in nadac_df.columns:
        return PennyPricingStatus(
            is_penny_priced=False,
            ndc=ndc,
            nadac_price=None,
            discount_pct=None,
            warning_message="NADAC data not available",
            should_exclude=False,
        )

    # Create normalized NDC column for matching
    matches = nadac_df.filter(
        pl.col("ndc").cast(pl.Utf8).str.replace_all("-", "").str.strip_chars()
        == ndc_clean
    )

    if matches.height == 0:
        return PennyPricingStatus(
            is_penny_priced=False,
            ndc=ndc,
            nadac_price=None,
            discount_pct=None,
            warning_message="NDC not found in NADAC data",
            should_exclude=False,
        )

    row = matches.row(0, named=True)

    # Check penny pricing indicators
    is_penny = False
    nadac_price = None
    discount_pct = None
    reason = ""

    # Check explicit flag
    if "penny_pricing" in matches.columns and row.get("penny_pricing"):
        is_penny = True
        reason = "Penny pricing flag is set"

    # Check NADAC price
    if "nadac_per_unit" in matches.columns:
        price = row.get("nadac_per_unit")
        if price is not None:
            nadac_price = Decimal(str(price))
            if nadac_price <= PENNY_THRESHOLD:
                is_penny = True
                reason = f"NADAC price is ${nadac_price:.4f}"

    # Check discount percentage
    if "total_discount_340b_pct" in matches.columns:
        discount = row.get("total_discount_340b_pct")
        if discount is not None:
            discount_pct = Decimal(str(discount))
            if discount_pct >= HIGH_DISCOUNT_THRESHOLD:
                is_penny = True
                reason = f"340B discount is {discount_pct:.1f}%"

    if is_penny:
        warning = (
            f"Penny Pricing Alert: {ndc} - {reason}. "
            "Exclude from Top Opportunities."
        )
    else:
        warning = "No penny pricing detected"

    return PennyPricingStatus(
        is_penny_priced=is_penny,
        ndc=ndc,
        nadac_price=nadac_price,
        discount_pct=discount_pct,
        warning_message=warning,
        should_exclude=is_penny,
    )


def filter_top_opportunities(
    opportunities: list[dict[str, object]],
    nadac_df: pl.DataFrame | None = None,
    penny_ndcs: set[str] | None = None,
) -> list[dict[str, object]]:
    """Filter out penny-priced drugs from Top Opportunities.

    Gatekeeper Test: Penny Pricing Alert
    - Drugs with Penny Pricing = Yes should NOT appear in "Top Opportunities"

    Args:
        opportunities: List of drug opportunities with 'ndc' and 'margin' keys.
        nadac_df: Optional NADAC DataFrame for penny pricing lookup.
        penny_ndcs: Optional pre-computed set of penny-priced NDCs.

    Returns:
        Filtered list excluding penny-priced drugs.
    """
    if penny_ndcs is None and nadac_df is not None:
        # Build penny NDC set from NADAC data
        flagged = check_penny_pricing(nadac_df)
        penny_ndcs = {str(item["ndc"]) for item in flagged}
    elif penny_ndcs is None:
        penny_ndcs = set()

    filtered = []
    excluded_count = 0

    for opp in opportunities:
        ndc = str(opp.get("ndc", ""))
        is_penny = opp.get("penny_pricing", False)

        # Check against penny_ndcs set or explicit flag
        if ndc in penny_ndcs or is_penny:
            excluded_count += 1
            logger.debug(f"Excluding penny-priced drug from opportunities: {ndc}")
            continue

        filtered.append(opp)

    if excluded_count > 0:
        logger.info(
            f"Excluded {excluded_count} penny-priced drugs from Top Opportunities"
        )

    return filtered


def get_penny_pricing_summary(nadac_df: pl.DataFrame) -> dict[str, object]:
    """Get summary statistics for penny pricing in dataset.

    Args:
        nadac_df: NADAC DataFrame with pricing data.

    Returns:
        Dictionary with penny pricing summary statistics.
    """
    flagged = check_penny_pricing(nadac_df)

    total_drugs = nadac_df.height
    penny_count = len(flagged)
    penny_pct = (penny_count / total_drugs * 100) if total_drugs > 0 else 0

    return {
        "total_drugs": total_drugs,
        "penny_priced_count": penny_count,
        "penny_priced_pct": round(penny_pct, 2),
        "flagged_ndcs": [item["ndc"] for item in flagged],
    }


@dataclass
class NADACEnhancedStatus:
    """Enhanced NADAC status with penny pricing and inflation flags.

    Attributes:
        ndc: NDC of the drug.
        is_penny_priced: Whether the drug has penny pricing.
        override_cost: Cost to use ($0.01 if penny priced, None otherwise).
        has_inflation_penalty: Whether drug has high inflation penalty.
        inflation_penalty_pct: The inflation penalty percentage.
        warnings: List of warning messages.
    """

    ndc: str
    is_penny_priced: bool
    override_cost: Decimal | None
    has_inflation_penalty: bool
    inflation_penalty_pct: Decimal | None
    warnings: list[str]


def build_nadac_lookup(nadac_df: pl.DataFrame) -> dict[str, dict[str, object]]:
    """Build comprehensive NADAC lookup with penny pricing and inflation data.

    Args:
        nadac_df: NADAC DataFrame with pricing data.

    Returns:
        Dictionary mapping NDC to NADAC data including:
        - is_penny_priced: bool
        - override_cost: Decimal or None
        - has_inflation_penalty: bool
        - inflation_penalty_pct: Decimal or None
        - discount_340b_pct: Decimal or None
        - nadac_price: Decimal or None (last_price from NADAC)
    """
    lookup: dict[str, dict[str, object]] = {}

    # Check available columns
    has_penny_col = "penny_pricing" in nadac_df.columns
    has_discount_col = "total_discount_340b_pct" in nadac_df.columns
    has_inflation_col = "inflation_penalty_pct" in nadac_df.columns
    has_last_price_col = "last_price" in nadac_df.columns

    if "ndc" not in nadac_df.columns:
        logger.warning("NADAC data missing 'ndc' column")
        return lookup

    for row in nadac_df.iter_rows(named=True):
        ndc = str(row.get("ndc", "")).replace("-", "").strip()
        if not ndc:
            continue

        # Normalize NDC to 11 digits
        ndc_normalized = ndc.zfill(11)[-11:]

        # Check penny pricing
        is_penny = False
        if has_penny_col:
            penny_val = row.get("penny_pricing")
            if penny_val and str(penny_val).upper() in ("YES", "TRUE", "1", "Y"):
                is_penny = True

        # Check discount percentage as alternative
        discount_pct = None
        if has_discount_col:
            discount_val = row.get("total_discount_340b_pct")
            if discount_val is not None:
                try:
                    discount_pct = Decimal(str(discount_val))
                    if discount_pct >= HIGH_DISCOUNT_THRESHOLD:
                        is_penny = True
                except (ValueError, TypeError):
                    pass

        # Check inflation penalty
        has_inflation = False
        inflation_pct = None
        if has_inflation_col:
            inflation_val = row.get("inflation_penalty_pct")
            if inflation_val is not None:
                try:
                    inflation_pct = Decimal(str(inflation_val))
                    if inflation_pct > INFLATION_PENALTY_THRESHOLD:
                        has_inflation = True
                except (ValueError, TypeError):
                    pass

        # Get NADAC price (last_price is the most recent NADAC)
        nadac_price = None
        if has_last_price_col:
            price_val = row.get("last_price")
            if price_val is not None:
                try:
                    nadac_price = Decimal(str(price_val))
                except (ValueError, TypeError):
                    pass

        # Build lookup entry
        lookup[ndc_normalized] = {
            "is_penny_priced": is_penny,
            "override_cost": PENNY_COST_OVERRIDE if is_penny else None,
            "has_inflation_penalty": has_inflation,
            "inflation_penalty_pct": inflation_pct,
            "discount_340b_pct": discount_pct,
            "nadac_price": nadac_price,
        }

    logger.info(f"Built NADAC lookup with {len(lookup)} NDCs")

    # Log summary
    penny_count = sum(1 for v in lookup.values() if v["is_penny_priced"])
    inflation_count = sum(1 for v in lookup.values() if v["has_inflation_penalty"])
    logger.info(
        f"NADAC summary: {penny_count} penny-priced, "
        f"{inflation_count} with high inflation penalty"
    )

    return lookup


def get_nadac_enhanced_status(
    ndc: str,
    nadac_lookup: dict[str, dict[str, object]],
) -> NADACEnhancedStatus:
    """Get enhanced NADAC status for a specific NDC.

    Args:
        ndc: NDC to look up (will be normalized).
        nadac_lookup: Lookup from build_nadac_lookup().

    Returns:
        NADACEnhancedStatus with all flags and warnings.
    """
    # Normalize NDC
    ndc_clean = ndc.replace("-", "").strip()
    ndc_normalized = ndc_clean.zfill(11)[-11:]

    # Look up in NADAC
    nadac_data = nadac_lookup.get(ndc_normalized)

    if not nadac_data:
        return NADACEnhancedStatus(
            ndc=ndc,
            is_penny_priced=False,
            override_cost=None,
            has_inflation_penalty=False,
            inflation_penalty_pct=None,
            warnings=[],
        )

    # Build warnings
    warnings = []
    if nadac_data["is_penny_priced"]:
        warnings.append(
            f"Penny Pricing: Cost overridden to ${PENNY_COST_OVERRIDE}"
        )

    if nadac_data["has_inflation_penalty"]:
        pct = nadac_data["inflation_penalty_pct"]
        warnings.append(
            f"High Inflation Penalty: {pct:.1f}% (exceeds {INFLATION_PENALTY_THRESHOLD}% threshold)"
        )

    return NADACEnhancedStatus(
        ndc=ndc,
        is_penny_priced=bool(nadac_data["is_penny_priced"]),
        override_cost=nadac_data["override_cost"],
        has_inflation_penalty=bool(nadac_data["has_inflation_penalty"]),
        inflation_penalty_pct=nadac_data["inflation_penalty_pct"],
        warnings=warnings,
    )


def apply_penny_cost_override(
    contract_cost: Decimal,
    ndc: str,
    nadac_lookup: dict[str, dict[str, object]],
) -> tuple[Decimal, bool]:
    """Apply penny pricing cost override if applicable.

    Per the Proprietary Data Manifest:
    "If penny_pricing == 'Yes', override Cost_Basis to $0.01"

    Args:
        contract_cost: Original contract cost.
        ndc: NDC of the drug.
        nadac_lookup: Lookup from build_nadac_lookup().

    Returns:
        Tuple of (effective_cost, was_overridden).
    """
    ndc_clean = ndc.replace("-", "").strip()
    ndc_normalized = ndc_clean.zfill(11)[-11:]

    nadac_data = nadac_lookup.get(ndc_normalized)

    if nadac_data and nadac_data["is_penny_priced"]:
        logger.debug(
            f"Penny pricing override for NDC {ndc}: "
            f"${contract_cost} -> ${PENNY_COST_OVERRIDE}"
        )
        return PENNY_COST_OVERRIDE, True

    return contract_cost, False
