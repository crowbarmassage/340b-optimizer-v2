"""Schema validation for 340B data sources (Bronze Layer Gatekeeper Tests)."""

import logging
from dataclasses import dataclass, field

import polars as pl

logger = logging.getLogger(__name__)


# Required columns for each data source
# Note: Acquisition cost can be "Unit Price (Current Catalog)" OR "Contract Cost"
CATALOG_REQUIRED_COLUMNS = {"NDC", "AWP"}
CATALOG_COST_COLUMNS = {"Unit Price (Current Catalog)", "Contract Cost"}  # At least one required
CATALOG_OPTIONAL_COLUMNS = {"Drug Name", "Manufacturer", "Gross Margin %"}

ASP_PRICING_REQUIRED_COLUMNS = {"HCPCS Code", "Payment Limit"}
ASP_PRICING_OPTIONAL_COLUMNS = {"Short Description", "Dosage", "Drug Name"}

CROSSWALK_REQUIRED_COLUMNS = {"NDC", "HCPCS Code"}
CROSSWALK_OPTIONAL_COLUMNS = {"Labeler Name", "NDC Trade Name", "Pkg Size", "Pkg Qty"}

NADAC_REQUIRED_COLUMNS = {"ndc", "total_discount_340b_pct"}
NADAC_OPTIONAL_COLUMNS = {"nadac_per_unit", "penny_pricing", "as_of_date"}

# NOC (Not Otherwise Classified) files - fallback for drugs without permanent J-codes
NOC_PRICING_REQUIRED_COLUMNS = {"Drug Generic Name", "Payment Limit"}
NOC_PRICING_OPTIONAL_COLUMNS = {"Dosage", "Notes"}

NOC_CROSSWALK_REQUIRED_COLUMNS = {"NDC", "Drug Generic Name"}
NOC_CROSSWALK_OPTIONAL_COLUMNS = {"LABELER NAME", "Drug Name", "PKG SIZE", "BILLUNITSPKG"}

# Top 50 high-value drugs that should have complete pricing data
# These are commonly used in 340B optimization and must not be silently dropped
TOP_50_DRUG_NAMES = [
    "HUMIRA",
    "ENBREL",
    "STELARA",
    "REMICADE",
    "RITUXAN",
    "KEYTRUDA",
    "OPDIVO",
    "AVASTIN",
    "HERCEPTIN",
    "COSENTYX",
    "SKYRIZI",
    "TREMFYA",
    "DUPIXENT",
    "OCREVUS",
    "ENTYVIO",
    "XELJANZ",
    "ORENCIA",
    "CIMZIA",
    "SIMPONI",
    "ACTEMRA",
    "TALTZ",
    "OTEZLA",
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
    "PROLIA",
    "XGEVA",
    "NEULASTA",
    "EPOGEN",
    "ARANESP",
    "PROCRIT",
    "ZARXIO",
    "NEUPOGEN",
    "ELIQUIS",
    "XARELTO",
    "JARDIANCE",
    "OZEMPIC",
    "TRULICITY",
]


@dataclass
class ValidationResult:
    """Result of a schema validation check.

    Attributes:
        is_valid: Whether the validation passed.
        message: Human-readable description of the result.
        missing_columns: List of required columns that are missing.
        row_count: Number of rows in the validated DataFrame.
        warnings: List of non-fatal issues detected.
    """

    is_valid: bool
    message: str
    missing_columns: list[str] = field(default_factory=list)
    row_count: int = 0
    warnings: list[str] = field(default_factory=list)


def validate_catalog_schema(df: pl.DataFrame) -> ValidationResult:
    """Validate product catalog schema.

    Gatekeeper Test: Schema Integrity
    - Must contain NDC, AWP columns
    - Must contain at least one cost column: Unit Price (Current Catalog) OR Contract Cost

    Args:
        df: DataFrame to validate.

    Returns:
        ValidationResult with status and details.
    """
    columns = set(df.columns)
    missing = CATALOG_REQUIRED_COLUMNS - columns

    if missing:
        return ValidationResult(
            is_valid=False,
            message=f"Catalog missing required columns: {sorted(missing)}",
            missing_columns=sorted(missing),
            row_count=df.height,
        )

    # Check for at least one cost column
    has_cost_column = bool(CATALOG_COST_COLUMNS & columns)
    if not has_cost_column:
        return ValidationResult(
            is_valid=False,
            message=(
                f"Catalog missing cost column. "
                f"Need one of: {sorted(CATALOG_COST_COLUMNS)}"
            ),
            missing_columns=sorted(CATALOG_COST_COLUMNS),
            row_count=df.height,
        )

    # Check for recommended columns
    warnings = []
    missing_optional = CATALOG_OPTIONAL_COLUMNS - columns
    if missing_optional:
        warnings.append(
            f"Catalog missing recommended columns: {sorted(missing_optional)}"
        )

    # Note which cost column is being used
    cost_col_used = "Unit Price (Current Catalog)" if "Unit Price (Current Catalog)" in columns else "Contract Cost"
    warnings.append(f"Using '{cost_col_used}' for 340B acquisition cost")

    return ValidationResult(
        is_valid=True,
        message=f"Catalog schema valid with {df.height} rows",
        missing_columns=[],
        row_count=df.height,
        warnings=warnings,
    )


def validate_catalog_row_volume(
    df: pl.DataFrame,
    min_rows: int = 30000,
) -> ValidationResult:
    """Validate catalog has sufficient row volume.

    Gatekeeper Test: Row Volume Audit
    - Full market catalog should have >40k rows
    - 340B catalog subset should have >30k rows

    Args:
        df: DataFrame to validate.
        min_rows: Minimum expected rows (default 30,000 for 340B catalog).

    Returns:
        ValidationResult with status and details.
    """
    if df.height < min_rows:
        return ValidationResult(
            is_valid=False,
            message=(
                f"Catalog has {df.height:,} rows, expected >{min_rows:,}. "
                "This may indicate a partial file or wrong data source."
            ),
            missing_columns=[],
            row_count=df.height,
        )

    return ValidationResult(
        is_valid=True,
        message=f"Catalog row volume OK: {df.height:,} rows",
        missing_columns=[],
        row_count=df.height,
    )


def validate_asp_schema(df: pl.DataFrame) -> ValidationResult:
    """Validate ASP pricing file schema.

    Args:
        df: DataFrame to validate.

    Returns:
        ValidationResult with status and details.
    """
    columns = set(df.columns)
    missing = ASP_PRICING_REQUIRED_COLUMNS - columns

    if missing:
        return ValidationResult(
            is_valid=False,
            message=f"ASP file missing required columns: {sorted(missing)}",
            missing_columns=sorted(missing),
            row_count=df.height,
        )

    return ValidationResult(
        is_valid=True,
        message=f"ASP schema valid with {df.height} HCPCS codes",
        missing_columns=[],
        row_count=df.height,
    )


def validate_crosswalk_schema(df: pl.DataFrame) -> ValidationResult:
    """Validate NDC-HCPCS crosswalk schema.

    Args:
        df: DataFrame to validate.

    Returns:
        ValidationResult with status and details.
    """
    columns = set(df.columns)
    missing = CROSSWALK_REQUIRED_COLUMNS - columns

    if missing:
        return ValidationResult(
            is_valid=False,
            message=f"Crosswalk missing required columns: {sorted(missing)}",
            missing_columns=sorted(missing),
            row_count=df.height,
        )

    return ValidationResult(
        is_valid=True,
        message=f"Crosswalk schema valid with {df.height:,} mappings",
        missing_columns=[],
        row_count=df.height,
    )


def validate_asp_quarter(
    df: pl.DataFrame,
    expected_quarter: str,
    quarter_column: str = "Quarter",
) -> ValidationResult:
    """Validate ASP file is for the expected quarter.

    Gatekeeper Test: Currency Check
    - ASP file should be for current quarter.

    Args:
        df: DataFrame to validate.
        expected_quarter: Expected quarter string (e.g., "Q4 2025").
        quarter_column: Column containing quarter info.

    Returns:
        ValidationResult with status and details.
    """
    if quarter_column not in df.columns:
        # Some files don't have explicit quarter column - pass with warning
        return ValidationResult(
            is_valid=True,
            message="No quarter column found - verify ASP file currency manually",
            missing_columns=[],
            row_count=df.height,
            warnings=["ASP file does not contain quarter column for validation"],
        )

    quarters = df.select(quarter_column).unique().to_series().to_list()

    if expected_quarter not in quarters:
        return ValidationResult(
            is_valid=False,
            message=(
                f"ASP file is for {quarters}, expected {expected_quarter}. "
                "Using outdated ASP data will produce incorrect Medicare margins."
            ),
            missing_columns=[],
            row_count=df.height,
        )

    return ValidationResult(
        is_valid=True,
        message=f"ASP file is current: {expected_quarter}",
        missing_columns=[],
        row_count=df.height,
    )


def validate_crosswalk_integrity(
    catalog_df: pl.DataFrame,
    crosswalk_df: pl.DataFrame,
    catalog_ndc_col: str = "NDC",
    crosswalk_ndc_col: str = "NDC",
    min_match_rate: float = 0.95,
) -> ValidationResult:
    """Validate crosswalk has sufficient NDC coverage.

    Gatekeeper Test: Crosswalk Integrity
    - >95% of infusible NDCs in the Catalog should join to an HCPCS code.

    Args:
        catalog_df: Product catalog DataFrame.
        crosswalk_df: NDC-HCPCS crosswalk DataFrame.
        catalog_ndc_col: NDC column name in catalog.
        crosswalk_ndc_col: NDC column name in crosswalk.
        min_match_rate: Minimum acceptable match rate (default 95%).

    Returns:
        ValidationResult with match statistics.
    """
    # Get unique NDCs from each source
    catalog_ndcs = set(catalog_df[catalog_ndc_col].unique().to_list())
    crosswalk_ndcs = set(crosswalk_df[crosswalk_ndc_col].unique().to_list())

    # Calculate match statistics
    matched = catalog_ndcs & crosswalk_ndcs
    unmatched = catalog_ndcs - crosswalk_ndcs

    total = len(catalog_ndcs)
    match_count = len(matched)
    match_rate = match_count / total if total > 0 else 0

    logger.info(
        f"Crosswalk integrity: {match_count:,}/{total:,} "
        f"NDCs matched ({match_rate:.1%})"
    )

    warnings = []
    if match_rate < min_match_rate:
        # Log some example orphans for debugging
        orphan_sample = list(unmatched)[:10]
        warnings.append(f"Sample unmatched NDCs: {orphan_sample}")

        return ValidationResult(
            is_valid=False,
            message=(
                f"Crosswalk match rate {match_rate:.1%} below "
                f"threshold {min_match_rate:.0%}. "
                f"{len(unmatched):,} NDCs have no HCPCS mapping."
            ),
            missing_columns=[],
            row_count=total,
            warnings=warnings,
        )

    return ValidationResult(
        is_valid=True,
        message=(
            f"Crosswalk integrity OK: {match_rate:.1%} match rate "
            f"({match_count:,}/{total:,} NDCs)"
        ),
        missing_columns=[],
        row_count=total,
    )


def validate_top_drugs_pricing(
    catalog_df: pl.DataFrame,
    drug_name_col: str = "Drug Name",
    contract_cost_col: str = "Contract Cost",
    awp_col: str = "AWP",
    max_missing_pct: float = 0.05,
) -> ValidationResult:
    """Validate Top 50 high-value drugs have complete pricing data.

    Risk Mitigation: Warn if >5% of Top 50 drugs have missing pricing.
    We do NOT want to silently drop high-value orphans.

    Args:
        catalog_df: Product catalog DataFrame.
        drug_name_col: Column containing drug names.
        contract_cost_col: Column containing contract cost.
        awp_col: Column containing AWP.
        max_missing_pct: Maximum acceptable missing rate (default 5%).

    Returns:
        ValidationResult with details on missing drugs.
    """
    if drug_name_col not in catalog_df.columns:
        return ValidationResult(
            is_valid=True,
            message="Drug Name column not found - skipping Top 50 validation",
            missing_columns=[],
            row_count=catalog_df.height,
            warnings=["Cannot validate Top 50 drugs without Drug Name column"],
        )

    # Normalize drug names for matching
    catalog_names = (
        catalog_df.select(pl.col(drug_name_col).str.to_uppercase().alias("name_upper"))
        .unique()
        .to_series()
        .to_list()
    )
    catalog_names_set = set(catalog_names)

    # Find Top 50 drugs present in catalog
    found_drugs = []
    missing_drugs = []

    for drug in TOP_50_DRUG_NAMES:
        # Check if drug name appears in any catalog entry
        if any(drug.upper() in name for name in catalog_names_set if name):
            found_drugs.append(drug)
        else:
            missing_drugs.append(drug)

    # Check pricing completeness for found drugs
    drugs_with_missing_pricing = []
    for drug in found_drugs:
        drug_rows = catalog_df.filter(
            pl.col(drug_name_col).str.to_uppercase().str.contains(drug.upper())
        )

        # Check for null or zero pricing
        if contract_cost_col in catalog_df.columns:
            null_cost = drug_rows.filter(
                pl.col(contract_cost_col).is_null() | (pl.col(contract_cost_col) == 0)
            )
            if null_cost.height > 0:
                drugs_with_missing_pricing.append(f"{drug} (missing contract cost)")

        if awp_col in catalog_df.columns:
            null_awp = drug_rows.filter(
                pl.col(awp_col).is_null() | (pl.col(awp_col) == 0)
            )
            if null_awp.height > 0 and drug not in [
                d.split(" ")[0] for d in drugs_with_missing_pricing
            ]:
                drugs_with_missing_pricing.append(f"{drug} (missing AWP)")

    # Calculate missing rate
    total_top_drugs = len(TOP_50_DRUG_NAMES)
    missing_count = len(missing_drugs) + len(drugs_with_missing_pricing)
    missing_rate = missing_count / total_top_drugs

    warnings = []
    if missing_drugs:
        warnings.append(f"Top 50 drugs not found in catalog: {missing_drugs[:10]}")
    if drugs_with_missing_pricing:
        warnings.append(
            f"Top 50 drugs with incomplete pricing: {drugs_with_missing_pricing[:10]}"
        )

    if missing_rate > max_missing_pct:
        return ValidationResult(
            is_valid=False,
            message=(
                f"WARNING: {missing_rate:.0%} of Top 50 drugs have missing data "
                f"(threshold: {max_missing_pct:.0%}). "
                f"Found {len(found_drugs)}/50, "
                f"{len(drugs_with_missing_pricing)} with incomplete pricing. "
                "High-value drugs may be silently dropped from analysis."
            ),
            missing_columns=[],
            row_count=catalog_df.height,
            warnings=warnings,
        )

    return ValidationResult(
        is_valid=True,
        message=(
            f"Top 50 drug coverage OK: {len(found_drugs)}/50 found, "
            f"{missing_rate:.0%} missing (threshold: {max_missing_pct:.0%})"
        ),
        missing_columns=[],
        row_count=catalog_df.height,
        warnings=warnings,
    )


def validate_nadac_schema(df: pl.DataFrame) -> ValidationResult:
    """Validate NADAC statistics file schema.

    Args:
        df: DataFrame to validate.

    Returns:
        ValidationResult with status and details.
    """
    columns = set(df.columns)
    missing = NADAC_REQUIRED_COLUMNS - columns

    if missing:
        return ValidationResult(
            is_valid=False,
            message=f"NADAC file missing required columns: {sorted(missing)}",
            missing_columns=sorted(missing),
            row_count=df.height,
        )

    return ValidationResult(
        is_valid=True,
        message=f"NADAC schema valid with {df.height:,} NDCs",
        missing_columns=[],
        row_count=df.height,
    )


def validate_noc_pricing_schema(df: pl.DataFrame) -> ValidationResult:
    """Validate NOC (Not Otherwise Classified) pricing file schema.

    NOC pricing provides fallback reimbursement rates for new drugs
    that don't yet have a permanent J-code.

    Args:
        df: DataFrame to validate.

    Returns:
        ValidationResult with status and details.
    """
    columns = set(df.columns)
    missing = NOC_PRICING_REQUIRED_COLUMNS - columns

    if missing:
        return ValidationResult(
            is_valid=False,
            message=f"NOC Pricing file missing required columns: {sorted(missing)}",
            missing_columns=sorted(missing),
            row_count=df.height,
        )

    return ValidationResult(
        is_valid=True,
        message=f"NOC Pricing schema valid with {df.height:,} drug entries",
        missing_columns=[],
        row_count=df.height,
    )


def validate_noc_crosswalk_schema(df: pl.DataFrame) -> ValidationResult:
    """Validate NOC NDC-HCPCS crosswalk schema.

    NOC crosswalk maps NDCs to generic drug names for drugs
    without permanent J-codes, enabling fallback pricing lookup.

    Args:
        df: DataFrame to validate.

    Returns:
        ValidationResult with status and details.
    """
    columns = set(df.columns)
    missing = NOC_CROSSWALK_REQUIRED_COLUMNS - columns

    if missing:
        return ValidationResult(
            is_valid=False,
            message=f"NOC Crosswalk missing required columns: {sorted(missing)}",
            missing_columns=sorted(missing),
            row_count=df.height,
        )

    return ValidationResult(
        is_valid=True,
        message=f"NOC Crosswalk schema valid with {df.height:,} mappings",
        missing_columns=[],
        row_count=df.height,
    )
