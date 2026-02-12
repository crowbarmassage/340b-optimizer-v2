"""Retail pricing engine with payer and drug category-specific multipliers.

This module implements the Ravenswood AWP Reimbursement Matrix logic:
- Drug categories: Generic, Brand, Specialty
- Payer-specific multipliers based on category
- Default fallback for unknown combinations

Key Multipliers (from Ravenswood matrix):
| Payer Category    | Generic | Brand | Specialty |
|-------------------|---------|-------|-----------|
| Medicare Part D   | 0.20    | 0.85  | 0.85      |
| Commercial        | 0.15    | 0.84  | 0.86      |
| IL Medicaid MCO   | 0.15    | 0.78  | 0.80      |
| Self Pay          | 1.00    | 1.00  | 1.00      |
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

import polars as pl

logger = logging.getLogger(__name__)


class DrugCategory(str, Enum):
    """Drug category classification."""

    GENERIC = "Generic"
    BRAND = "Brand"
    SPECIALTY = "Specialty"
    UNKNOWN = "Unknown"


class PayerCategory(str, Enum):
    """Payer category classification."""

    MEDICARE_PART_D = "Medicare Part D"
    COMMERCIAL = "Commercial"
    MEDICAID_MCO = "Medicaid MCO"
    SELF_PAY = "Self Pay"
    UNKNOWN = "Unknown"


# AWP multipliers by payer and drug category
# Source: Ravenswood_AWP_Reimbursement_Matrix.xlsx
AWP_MULTIPLIERS: dict[PayerCategory, dict[DrugCategory, Decimal]] = {
    PayerCategory.MEDICARE_PART_D: {
        DrugCategory.GENERIC: Decimal("0.20"),
        DrugCategory.BRAND: Decimal("0.85"),
        DrugCategory.SPECIALTY: Decimal("0.85"),
        DrugCategory.UNKNOWN: Decimal("0.85"),
    },
    PayerCategory.COMMERCIAL: {
        DrugCategory.GENERIC: Decimal("0.15"),
        DrugCategory.BRAND: Decimal("0.84"),
        DrugCategory.SPECIALTY: Decimal("0.86"),
        DrugCategory.UNKNOWN: Decimal("0.85"),
    },
    PayerCategory.MEDICAID_MCO: {
        DrugCategory.GENERIC: Decimal("0.15"),
        DrugCategory.BRAND: Decimal("0.78"),
        DrugCategory.SPECIALTY: Decimal("0.80"),
        DrugCategory.UNKNOWN: Decimal("0.78"),
    },
    PayerCategory.SELF_PAY: {
        DrugCategory.GENERIC: Decimal("1.00"),
        DrugCategory.BRAND: Decimal("1.00"),
        DrugCategory.SPECIALTY: Decimal("1.00"),
        DrugCategory.UNKNOWN: Decimal("1.00"),
    },
    PayerCategory.UNKNOWN: {
        DrugCategory.GENERIC: Decimal("0.15"),
        DrugCategory.BRAND: Decimal("0.84"),
        DrugCategory.SPECIALTY: Decimal("0.86"),
        DrugCategory.UNKNOWN: Decimal("0.85"),
    },
}

# Default multiplier when payer/category combination not found
DEFAULT_AWP_MULTIPLIER = Decimal("0.85")

# Specialty drug names (from Ravenswood Drug Categories sheet)
SPECIALTY_DRUGS = {
    "HUMIRA",
    "ENBREL",
    "COSENTYX",
    "TALTZ",
    "STELARA",
    "RINVOQ",
    "XELJANZ",
    "ORENCIA",
    "ACTEMRA",
    "OTEZLA",
    "RASUVO",
    "CIMZIA",
    "BENLYSTA",
    "BIMZELX",
    "TREMFYA",
    "HYRIMOZ",
    "SIMLANDI",
    "SKYRIZI",
    "DUPIXENT",
    "OCREVUS",
    "ENTYVIO",
    "SIMPONI",
    "INFLECTRA",
    "RENFLEXIS",
    "HADLIMA",
    "IMBRUVICA",
    "REVLIMID",
    "IBRANCE",
    "XTANDI",
    "TAGRISSO",
    "LYNPARZA",
    "CALQUENCE",
    "VENCLEXTA",
    "POMALYST",
    "DARZALEX",
    "EYLEA",
    "LUCENTIS",
    "KEYTRUDA",
    "OPDIVO",
    "AVASTIN",
    "HERCEPTIN",
    "RITUXAN",
    "REMICADE",
    "OZEMPIC",
    "WEGOVY",
    "TRULICITY",
    "RYBELSUS",
}

# Brand drug names (from Ravenswood Drug Categories sheet)
BRAND_DRUGS = {
    "PLAQUENIL",
    "ARAVA",
    "MEDROL",
    "JANUVIA",
    "LIPITOR",
    "CELEBREX",
    "ULORIC",
    "MITIGARE",
    "IMURAN",
    "EVOXAC",
    "FOSAMAX",
    "PEPCID",
    "ELIQUIS",
    "XARELTO",
    "JARDIANCE",
    "FARXIGA",
    "ENTRESTO",
    "NOVOLOG",
    "FIASP",
}

# Generic drug keywords (from Ravenswood Drug Categories sheet)
GENERIC_KEYWORDS = {
    "METHOTREXATE",
    "HYDROXYCHLOROQUINE",
    "PREDNISONE",
    "ALLOPURINOL",
    "SULFASALAZINE",
    "LEFLUNOMIDE",
    "FOLIC ACID",
    "MELOXICAM",
    "GABAPENTIN",
    "CYCLOBENZAPRINE",
    "COLCHICINE",
    "AZATHIOPRINE",
    "MYCOPHENOLATE",
}


@dataclass
class RetailPricingResult:
    """Result of retail pricing calculation.

    Attributes:
        awp: Average Wholesale Price
        multiplier: AWP multiplier applied
        revenue: Calculated revenue (AWP × multiplier)
        drug_category: Drug category used
        payer_category: Payer category used
    """

    awp: Decimal
    multiplier: Decimal
    revenue: Decimal
    drug_category: DrugCategory
    payer_category: PayerCategory


def classify_drug_category(
    drug_name: str,
    category_lookup: dict[str, DrugCategory] | None = None,
) -> DrugCategory:
    """Classify a drug into Generic, Brand, or Specialty category.

    Uses a combination of:
    1. Explicit category lookup (from Ravenswood Drug Categories sheet)
    2. Name-based matching against known specialty/brand/generic drugs

    Args:
        drug_name: Name of the drug to classify.
        category_lookup: Optional lookup dict from Ravenswood matrix.

    Returns:
        DrugCategory classification.
    """
    if not drug_name:
        return DrugCategory.UNKNOWN

    name_upper = drug_name.upper().strip()

    # Check explicit lookup first
    if category_lookup:
        for key, category in category_lookup.items():
            if key.upper() in name_upper or name_upper in key.upper():
                return category

    # Check specialty drugs
    for specialty in SPECIALTY_DRUGS:
        if specialty in name_upper or name_upper.startswith(specialty):
            return DrugCategory.SPECIALTY

    # Check brand drugs
    for brand in BRAND_DRUGS:
        if brand in name_upper or name_upper.startswith(brand):
            return DrugCategory.BRAND

    # Check generic keywords
    for generic in GENERIC_KEYWORDS:
        if generic in name_upper:
            return DrugCategory.GENERIC

    # Default to Brand (conservative - higher reimbursement)
    return DrugCategory.BRAND


def get_awp_multiplier(
    drug_category: DrugCategory,
    payer_category: PayerCategory = PayerCategory.COMMERCIAL,
) -> Decimal:
    """Get AWP multiplier for a drug/payer combination.

    Args:
        drug_category: Drug category (Generic, Brand, Specialty).
        payer_category: Payer category (Medicare, Commercial, etc.).

    Returns:
        AWP multiplier as Decimal.
    """
    payer_multipliers = AWP_MULTIPLIERS.get(payer_category, {})
    multiplier = payer_multipliers.get(drug_category, DEFAULT_AWP_MULTIPLIER)

    logger.debug(
        f"AWP multiplier for {drug_category.value}/{payer_category.value}: {multiplier}"
    )

    return multiplier


def calculate_retail_revenue(
    awp: Decimal,
    drug_name: str,
    payer_category: PayerCategory = PayerCategory.COMMERCIAL,
    category_lookup: dict[str, DrugCategory] | None = None,
) -> RetailPricingResult:
    """Calculate retail revenue using payer/category-specific multipliers.

    This implements the Ravenswood AWP Reimbursement Matrix logic.

    Args:
        awp: Average Wholesale Price.
        drug_name: Name of the drug.
        payer_category: Payer category for multiplier lookup.
        category_lookup: Optional drug category lookup dict.

    Returns:
        RetailPricingResult with revenue calculation details.
    """
    # Classify drug
    drug_category = classify_drug_category(drug_name, category_lookup)

    # Get multiplier
    multiplier = get_awp_multiplier(drug_category, payer_category)

    # Calculate revenue
    revenue = awp * multiplier

    logger.debug(
        f"Retail revenue for {drug_name}: "
        f"AWP ${awp} × {multiplier} ({drug_category.value}/{payer_category.value}) "
        f"= ${revenue}"
    )

    return RetailPricingResult(
        awp=awp,
        multiplier=multiplier,
        revenue=revenue,
        drug_category=drug_category,
        payer_category=payer_category,
    )


def load_drug_category_lookup(ravenswood_df: pl.DataFrame) -> dict[str, DrugCategory]:
    """Load drug category lookup from Ravenswood Drug Categories sheet.

    Args:
        ravenswood_df: DataFrame from Drug Categories sheet.

    Returns:
        Dictionary mapping drug names to categories.
    """
    lookup: dict[str, DrugCategory] = {}

    # Expected columns: Category, Common Drugs (or similar)
    category_col = None
    drugs_col = None

    for col in ravenswood_df.columns:
        col_lower = col.lower()
        if "category" in col_lower and category_col is None:
            category_col = col
        if "drug" in col_lower or "common" in col_lower:
            drugs_col = col

    if not category_col or not drugs_col:
        logger.warning("Could not find expected columns in Drug Categories sheet")
        return lookup

    for row in ravenswood_df.iter_rows(named=True):
        category_str = str(row.get(category_col, "")).strip()
        drugs_str = str(row.get(drugs_col, "")).strip()

        if not category_str or not drugs_str:
            continue

        # Map category string to enum
        category_lower = category_str.lower()
        if "generic" in category_lower:
            category = DrugCategory.GENERIC
        elif "specialty" in category_lower:
            category = DrugCategory.SPECIALTY
        elif "brand" in category_lower:
            category = DrugCategory.BRAND
        else:
            continue

        # Parse drug names (comma-separated)
        for drug in drugs_str.split(","):
            drug_name = drug.strip()
            if drug_name:
                lookup[drug_name.upper()] = category

    logger.info(f"Loaded {len(lookup)} drug-to-category mappings from Ravenswood")
    return lookup


def calculate_blended_retail_revenue(
    awp: Decimal,
    drug_name: str,
    payer_mix: dict[PayerCategory, Decimal] | None = None,
    category_lookup: dict[str, DrugCategory] | None = None,
) -> Decimal:
    """Calculate blended retail revenue across payer mix.

    Uses the payer mix percentages from Ravenswood Summary sheet
    to calculate weighted average revenue.

    Args:
        awp: Average Wholesale Price.
        drug_name: Name of the drug.
        payer_mix: Dictionary of payer category to mix percentage.
            Defaults to Ravenswood payer mix if not provided.
        category_lookup: Optional drug category lookup dict.

    Returns:
        Blended revenue as weighted average.
    """
    # Default payer mix from Ravenswood Summary (Est. Claims % Mix)
    if payer_mix is None:
        payer_mix = {
            PayerCategory.MEDICARE_PART_D: Decimal("0.40"),  # 23% + 17% combined
            PayerCategory.COMMERCIAL: Decimal("0.51"),
            PayerCategory.MEDICAID_MCO: Decimal("0.03"),
            PayerCategory.SELF_PAY: Decimal("0.05"),
        }

    total_revenue = Decimal("0")
    total_weight = Decimal("0")

    for payer, weight in payer_mix.items():
        result = calculate_retail_revenue(
            awp, drug_name, payer, category_lookup
        )
        total_revenue += result.revenue * weight
        total_weight += weight

    # Normalize if weights don't sum to 1
    if total_weight > 0 and total_weight != Decimal("1"):
        total_revenue = total_revenue / total_weight

    return total_revenue
