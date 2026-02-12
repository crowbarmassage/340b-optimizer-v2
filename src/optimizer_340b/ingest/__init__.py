"""Data ingestion module for 340B Optimizer.

This module handles:
- Loading raw data files (Bronze Layer)
- Validating schemas and data quality
- Normalizing and joining data (Silver Layer)
"""

from optimizer_340b.ingest.loaders import (
    detect_file_type,
    load_csv_to_polars,
    load_excel_to_polars,
    load_file_auto,
)
from optimizer_340b.ingest.normalizers import (
    build_silver_dataset,
    fuzzy_match_drug_name,
    fuzzy_match_drug_partial,
    join_asp_pricing,
    join_catalog_to_crosswalk,
    normalize_asp_pricing,
    normalize_catalog,
    normalize_crosswalk,
    normalize_ndc,
    normalize_ndc_column,
    preprocess_cms_csv,
)
from optimizer_340b.ingest.validators import (
    ValidationResult,
    validate_asp_quarter,
    validate_asp_schema,
    validate_catalog_row_volume,
    validate_catalog_schema,
    validate_crosswalk_integrity,
    validate_crosswalk_schema,
    validate_top_drugs_pricing,
)

__all__ = [
    # Loaders
    "load_excel_to_polars",
    "load_csv_to_polars",
    "load_file_auto",
    "detect_file_type",
    # Validators
    "ValidationResult",
    "validate_catalog_schema",
    "validate_catalog_row_volume",
    "validate_asp_schema",
    "validate_asp_quarter",
    "validate_crosswalk_schema",
    "validate_crosswalk_integrity",
    "validate_top_drugs_pricing",
    # Normalizers (Silver Layer)
    "normalize_ndc",
    "normalize_ndc_column",
    "normalize_catalog",
    "normalize_crosswalk",
    "normalize_asp_pricing",
    "preprocess_cms_csv",
    "fuzzy_match_drug_name",
    "fuzzy_match_drug_partial",
    "join_catalog_to_crosswalk",
    "join_asp_pricing",
    "build_silver_dataset",
]
