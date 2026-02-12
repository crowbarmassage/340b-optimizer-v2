"""Data normalization and cleaning for 340B data sources (Silver Layer).

This module handles:
- NDC normalization to 11-digit format (preserving leading zeros)
- Column mapping/renaming for different data sources
- CMS file preprocessing (skip header rows)
- Fuzzy drug name matching
- NDC-to-HCPCS crosswalk joins
"""

import logging
import re

import polars as pl
from thefuzz import fuzz  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# Columns that should always be read as strings to preserve leading zeros
NDC_COLUMN_NAMES = {
    "NDC",
    "NDC2",
    "ndc",
    "ndc2",
    "Ndc",
    "NDC or ALTERNATE ID",  # NOC crosswalk
    "Product Catalog NDC",  # Wholesaler catalog
}


# Column mapping configurations for different data sources
# Maps raw column names to standardized names
CATALOG_COLUMN_MAP = {
    "Medispan AWP": "AWP",
    "Trade Name": "Drug Name",
    "Generic Name": "Generic Name",
    "Product Description": "Product Description",
}

CROSSWALK_COLUMN_MAP = {
    "_2025_CODE": "HCPCS Code",
    "NDC2": "NDC",
    "Drug Name": "Drug Name",
    "LABELER NAME": "Labeler Name",
    "PKG SIZE": "Pkg Size",
    "PKG QTY": "Pkg Qty",
    "BILLUNITS": "Bill Units",
    "BILLUNITSPKG": "Bill Units Per Pkg",
}

ASP_PRICING_COLUMN_MAP = {
    "HCPCS Code": "HCPCS Code",
    "Payment Limit": "Payment Limit",
    "Short Description": "Short Description",
    "HCPCS Code Dosage": "Dosage",
}

# NOC (Not Otherwise Classified) file column mappings
NOC_PRICING_COLUMN_MAP = {
    "Drug Generic Name (Trade Name)": "Drug Generic Name",
    "Drug Generic Name": "Drug Generic Name",
    "Payment Limit": "Payment Limit",
    "Dosage": "Dosage",
    "Notes": "Notes",
}

NOC_CROSSWALK_COLUMN_MAP = {
    "NDC or ALTERNATE ID": "NDC",
    "Drug Generic Name": "Drug Generic Name",
    "LABELER NAME": "Labeler Name",
    "Drug Name": "Drug Name",
    "Dosage": "Dosage",
    "PKG SIZE": "Pkg Size",
    "PKG QTY": "Pkg Qty",
    "BILLUNITS": "Bill Units",
    "BILLUNITSPKG": "Bill Units Per Pkg",
}


def normalize_ndc(ndc: str) -> str:
    """Normalize NDC to 11-digit format, preserving leading zeros.

    Handles various NDC formats:
    - 11-digit with dashes: 12345-6789-01 -> 12345678901
    - 11-digit without dashes: 12345678901 -> 12345678901
    - 10-digit: 1234567890 -> 01234567890 (padded)
    - Short NDCs: 12345 -> 00000012345 (padded)

    Args:
        ndc: Raw NDC string.

    Returns:
        11-digit normalized NDC string with leading zeros preserved.
    """
    if ndc is None:
        return ""

    # Remove all non-numeric characters
    cleaned = re.sub(r"[^0-9]", "", str(ndc))

    # Pad short NDCs with leading zeros to 11 digits
    return cleaned.zfill(11)[-11:]


def normalize_ndc_column(
    df: pl.DataFrame,
    ndc_column: str = "NDC",
    output_column: str = "ndc_normalized",
) -> pl.DataFrame:
    """Apply NDC normalization to a DataFrame column.

    Args:
        df: DataFrame with NDC column.
        ndc_column: Name of the NDC column.
        output_column: Name for the normalized output column.

    Returns:
        DataFrame with normalized NDC column added.
    """
    if ndc_column not in df.columns:
        logger.warning(f"NDC column '{ndc_column}' not found in DataFrame")
        return df

    return df.with_columns(
        pl.col(ndc_column)
        .map_elements(normalize_ndc, return_dtype=pl.String)
        .alias(output_column)
    )


def apply_column_mapping(
    df: pl.DataFrame,
    column_map: dict[str, str],
) -> pl.DataFrame:
    """Rename columns according to a mapping.

    Only renames columns that exist in the DataFrame.

    Args:
        df: DataFrame to rename columns in.
        column_map: Mapping of old names to new names.

    Returns:
        DataFrame with renamed columns.
    """
    # Build rename dict for columns that exist
    renames = {}
    for old_name, new_name in column_map.items():
        if old_name in df.columns:
            renames[old_name] = new_name
            logger.debug(f"Mapping column: '{old_name}' -> '{new_name}'")

    if renames:
        df = df.rename(renames)
        logger.info(f"Renamed {len(renames)} columns")

    return df


def normalize_catalog(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize product catalog to standard schema.

    Applies column mapping and NDC normalization.

    Args:
        df: Raw catalog DataFrame.

    Returns:
        Normalized catalog DataFrame with standard column names.
    """
    logger.info(f"Normalizing catalog with {df.height} rows")

    # Apply column mapping
    df = apply_column_mapping(df, CATALOG_COLUMN_MAP)

    # Add normalized NDC
    df = normalize_ndc_column(df, ndc_column="NDC")

    # Derive Drug Name from Trade Name or Product Description if needed
    if "Drug Name" not in df.columns:
        if "Trade Name" in df.columns:
            df = df.with_columns(pl.col("Trade Name").alias("Drug Name"))
            logger.info("Using 'Trade Name' as 'Drug Name'")
        elif "Product Description" in df.columns:
            df = df.with_columns(pl.col("Product Description").alias("Drug Name"))
            logger.info("Using 'Product Description' as 'Drug Name'")

    return df


def normalize_crosswalk(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize NDC-HCPCS crosswalk to standard schema.

    Args:
        df: Raw crosswalk DataFrame.

    Returns:
        Normalized crosswalk DataFrame with standard column names.
    """
    logger.info(f"Normalizing crosswalk with {df.height} rows")

    # Apply column mapping
    df = apply_column_mapping(df, CROSSWALK_COLUMN_MAP)

    # Add normalized NDC
    df = normalize_ndc_column(df, ndc_column="NDC")

    return df


def normalize_asp_pricing(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize ASP pricing file to standard schema.

    Args:
        df: Raw ASP pricing DataFrame.

    Returns:
        Normalized ASP pricing DataFrame with standard column names.
    """
    logger.info(f"Normalizing ASP pricing with {df.height} rows")

    # Apply column mapping
    df = apply_column_mapping(df, ASP_PRICING_COLUMN_MAP)

    # Ensure Payment Limit is numeric
    if "Payment Limit" in df.columns:
        df = df.with_columns(
            pl.col("Payment Limit")
            .cast(pl.Float64, strict=False)
            .alias("Payment Limit")
        )

    return df


def normalize_noc_pricing(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize NOC pricing file to standard schema.

    NOC pricing provides fallback reimbursement rates for drugs
    without permanent J-codes.

    Args:
        df: Raw NOC pricing DataFrame.

    Returns:
        Normalized NOC pricing DataFrame with standard column names.
    """
    logger.info(f"Normalizing NOC pricing with {df.height} rows")

    # Apply column mapping
    df = apply_column_mapping(df, NOC_PRICING_COLUMN_MAP)

    # Ensure Payment Limit is numeric (may have $ prefix)
    if "Payment Limit" in df.columns:
        df = df.with_columns(
            pl.col("Payment Limit")
            .str.replace_all(r"[\$,]", "")
            .cast(pl.Float64, strict=False)
            .alias("Payment Limit")
        )

    return df


def normalize_noc_crosswalk(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize NOC crosswalk file to standard schema.

    NOC crosswalk maps NDCs to generic drug names for drugs
    without permanent J-codes.

    Args:
        df: Raw NOC crosswalk DataFrame.

    Returns:
        Normalized NOC crosswalk DataFrame with standard column names.
    """
    logger.info(f"Normalizing NOC crosswalk with {df.height} rows")

    # Apply column mapping
    df = apply_column_mapping(df, NOC_CROSSWALK_COLUMN_MAP)

    # Add normalized NDC
    if "NDC" in df.columns:
        df = normalize_ndc_column(df, ndc_column="NDC")

    return df


def preprocess_cms_csv(
    file_path: str,
    skip_rows: int = 8,
    encoding: str = "latin-1",
) -> pl.DataFrame:
    """Preprocess CMS CSV files that have header metadata rows.

    CMS files (ASP pricing, crosswalk) typically have 8 rows of metadata
    before the actual column headers. NDC columns are read as strings to
    preserve leading zeros.

    Args:
        file_path: Path to the CSV file.
        skip_rows: Number of header rows to skip.
        encoding: File encoding (CMS uses latin-1).

    Returns:
        DataFrame with data starting from actual headers.
    """
    logger.info(f"Preprocessing CMS CSV, skipping {skip_rows} header rows")

    # First pass: read a small sample to detect column names
    df_sample = pl.read_csv(
        file_path,
        encoding=encoding,
        skip_rows=skip_rows,
        n_rows=5,
        truncate_ragged_lines=True,
        infer_schema_length=0,  # Read all as strings for header detection
    )

    # Build schema overrides for NDC columns (to preserve leading zeros)
    schema_overrides = {
        col: pl.String for col in df_sample.columns if col in NDC_COLUMN_NAMES
    }
    for col in schema_overrides:
        logger.info(f"Reading '{col}' as string to preserve leading zeros")

    df = pl.read_csv(
        file_path,
        encoding=encoding,
        skip_rows=skip_rows,
        infer_schema_length=10000,
        truncate_ragged_lines=True,
        schema_overrides=schema_overrides if schema_overrides else None,
    )

    # Drop completely empty columns (CMS files have many empty trailing columns)
    non_empty_cols = [col for col in df.columns if df[col].null_count() < df.height]
    if len(non_empty_cols) < len(df.columns):
        dropped = len(df.columns) - len(non_empty_cols)
        logger.info(f"Dropped {dropped} empty columns")
        df = df.select(non_empty_cols)

    logger.info(f"Loaded {df.height} rows, {df.width} columns after preprocessing")
    return df


def fuzzy_match_drug_name(
    name: str,
    candidates: list[str],
    threshold: int = 80,
) -> str | None:
    """Find best fuzzy match for a drug name.

    Args:
        name: Drug name to match.
        candidates: List of candidate names to match against.
        threshold: Minimum similarity score (0-100).

    Returns:
        Best matching candidate name, or None if no match above threshold.
    """
    if not name or not candidates:
        return None

    best_match = None
    best_score = 0

    name_upper = name.upper()
    for candidate in candidates:
        if candidate is None:
            continue
        score = fuzz.ratio(name_upper, candidate.upper())
        if score > best_score and score >= threshold:
            best_score = score
            best_match = candidate

    if best_match:
        logger.debug(f"Fuzzy match '{name}' -> '{best_match}' (score: {best_score})")

    return best_match


def fuzzy_match_drug_partial(
    name: str,
    candidates: list[str],
    threshold: int = 70,
) -> str | None:
    """Find best partial fuzzy match for a drug name.

    Uses partial ratio which is better for matching drug names
    where one string is a substring of another (e.g., "HUMIRA" in "HUMIRA PEN").

    Args:
        name: Drug name to match.
        candidates: List of candidate names to match against.
        threshold: Minimum similarity score (0-100).

    Returns:
        Best matching candidate name, or None if no match above threshold.
    """
    if not name or not candidates:
        return None

    best_match = None
    best_score = 0

    name_upper = name.upper()
    for candidate in candidates:
        if candidate is None:
            continue
        score = fuzz.partial_ratio(name_upper, candidate.upper())
        if score > best_score and score >= threshold:
            best_score = score
            best_match = candidate

    if best_match:
        logger.debug(f"Partial match '{name}' -> '{best_match}' (score: {best_score})")

    return best_match


def join_catalog_to_crosswalk(
    catalog_df: pl.DataFrame,
    crosswalk_df: pl.DataFrame,
    catalog_ndc_col: str = "ndc_normalized",
    crosswalk_ndc_col: str = "ndc_normalized",
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Join product catalog to NDC-HCPCS crosswalk.

    Gatekeeper Test: Crosswalk Integrity
    - >95% of infusible NDCs should successfully join

    Args:
        catalog_df: Product catalog DataFrame (normalized).
        crosswalk_df: NDC-HCPCS crosswalk DataFrame (normalized).
        catalog_ndc_col: NDC column name in catalog.
        crosswalk_ndc_col: NDC column name in crosswalk.

    Returns:
        Tuple of (joined_df, orphan_df).
        - joined_df: Catalog rows that matched crosswalk
        - orphan_df: Catalog rows that did not match (orphans)
    """
    # Ensure NDC columns exist
    if catalog_ndc_col not in catalog_df.columns:
        catalog_df = normalize_ndc_column(catalog_df, "NDC", catalog_ndc_col)

    if crosswalk_ndc_col not in crosswalk_df.columns:
        crosswalk_df = normalize_ndc_column(crosswalk_df, "NDC", crosswalk_ndc_col)

    # Select only relevant columns from crosswalk to avoid duplication
    crosswalk_cols = [crosswalk_ndc_col, "HCPCS Code"]
    optional_cols = [
        "Drug Name", "Bill Units", "Bill Units Per Pkg", "Pkg Size", "Pkg Qty"
    ]
    for col in optional_cols:
        if col in crosswalk_df.columns:
            crosswalk_cols.append(col)

    crosswalk_subset = crosswalk_df.select(
        [c for c in crosswalk_cols if c in crosswalk_df.columns]
    ).unique(subset=[crosswalk_ndc_col])

    # Perform left join
    joined = catalog_df.join(
        crosswalk_subset,
        left_on=catalog_ndc_col,
        right_on=crosswalk_ndc_col,
        how="left",
        suffix="_crosswalk",
    )

    # Split into matched and orphaned
    matched = joined.filter(pl.col("HCPCS Code").is_not_null())
    orphans = joined.filter(pl.col("HCPCS Code").is_null())

    # Log crosswalk integrity stats
    total = catalog_df.height
    matched_count = matched.height
    orphan_count = orphans.height
    match_rate = (matched_count / total * 100) if total > 0 else 0

    logger.info(
        f"Crosswalk join: {matched_count:,}/{total:,} matched ({match_rate:.1f}%)"
    )
    logger.info(f"Orphaned NDCs: {orphan_count:,}")

    return matched, orphans


def join_asp_pricing(
    joined_df: pl.DataFrame,
    asp_df: pl.DataFrame,
    hcpcs_col: str = "HCPCS Code",
) -> pl.DataFrame:
    """Join crosswalk-enriched data to ASP pricing.

    Args:
        joined_df: DataFrame with HCPCS codes (from crosswalk join).
        asp_df: ASP pricing DataFrame (normalized).
        hcpcs_col: HCPCS code column name.

    Returns:
        DataFrame with ASP pricing joined.
    """
    if hcpcs_col not in joined_df.columns:
        logger.warning(f"HCPCS column '{hcpcs_col}' not found - skipping ASP join")
        return joined_df

    if hcpcs_col not in asp_df.columns:
        logger.warning(f"HCPCS column '{hcpcs_col}' not found in ASP data")
        return joined_df

    # Select relevant ASP columns
    asp_cols = [hcpcs_col, "Payment Limit"]
    if "Short Description" in asp_df.columns:
        asp_cols.append("Short Description")
    if "Dosage" in asp_df.columns:
        asp_cols.append("Dosage")

    asp_subset = asp_df.select(
        [c for c in asp_cols if c in asp_df.columns]
    ).unique(subset=[hcpcs_col])

    # Join on HCPCS code
    result = joined_df.join(
        asp_subset,
        on=hcpcs_col,
        how="left",
        suffix="_asp",
    )

    # Rename Payment Limit to ASP for clarity
    if "Payment Limit" in result.columns:
        result = result.rename({"Payment Limit": "ASP"})

    # Log join stats
    asp_matched = result.filter(pl.col("ASP").is_not_null()).height
    logger.info(f"ASP pricing joined: {asp_matched:,}/{result.height:,} with pricing")

    return result


def build_silver_dataset(
    catalog_df: pl.DataFrame,
    crosswalk_df: pl.DataFrame,
    asp_df: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Build complete Silver Layer dataset.

    Normalizes all inputs and joins them together.

    Args:
        catalog_df: Raw product catalog.
        crosswalk_df: Raw NDC-HCPCS crosswalk.
        asp_df: Raw ASP pricing file.

    Returns:
        Tuple of (silver_df, orphans_df).
        - silver_df: Complete joined dataset with pricing
        - orphans_df: Catalog items that couldn't be joined
    """
    logger.info("Building Silver Layer dataset...")

    # Normalize all inputs
    catalog_norm = normalize_catalog(catalog_df)
    crosswalk_norm = normalize_crosswalk(crosswalk_df)
    asp_norm = normalize_asp_pricing(asp_df)

    # Join catalog to crosswalk
    joined, orphans = join_catalog_to_crosswalk(catalog_norm, crosswalk_norm)

    # Join ASP pricing
    silver = join_asp_pricing(joined, asp_norm)

    logger.info(
        f"Silver Layer complete: {silver.height:,} enriched rows, "
        f"{orphans.height:,} orphans"
    )

    return silver, orphans
