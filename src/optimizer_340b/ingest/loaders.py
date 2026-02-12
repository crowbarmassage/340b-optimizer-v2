"""File loading utilities for 340B data sources."""

import logging
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import pandas as pd
import polars as pl

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


def load_excel_to_polars(
    file: BinaryIO | Path | str,
    sheet_name: str | int = 0,
) -> pl.DataFrame:
    """Load Excel file into Polars DataFrame.

    Uses pandas as intermediate step for Excel parsing (openpyxl backend),
    then converts to Polars for downstream processing efficiency.

    NDC columns are automatically read as strings to preserve leading zeros.

    Args:
        file: File path, path string, or file-like object.
        sheet_name: Sheet name or index to load. Defaults to first sheet.

    Returns:
        Polars DataFrame with loaded data.

    Raises:
        ValueError: If file cannot be parsed as Excel.
    """
    logger.info(f"Loading Excel file, sheet: {sheet_name}")

    try:
        # Handle different input types
        if isinstance(file, str):
            file = Path(file)

        # First pass: read headers to detect NDC columns
        # Use pandas for Excel parsing (openpyxl backend)
        pdf_headers = pd.read_excel(
            file, sheet_name=sheet_name, engine="openpyxl", nrows=0
        )

        # Build dtype dict for NDC columns to preserve leading zeros
        dtype_overrides: dict[str, type] = {}
        for col in pdf_headers.columns:
            if col in NDC_COLUMN_NAMES:
                dtype_overrides[col] = str
                logger.info(f"Reading '{col}' as string to preserve leading zeros")

        # Reset file position if it's a file-like object
        if hasattr(file, "seek"):
            file.seek(0)

        # Read with dtype overrides
        pdf = pd.read_excel(
            file,
            sheet_name=sheet_name,
            engine="openpyxl",
            dtype=dtype_overrides if dtype_overrides else None,
        )

        # Convert to Polars
        df = pl.from_pandas(pdf)

        logger.info(f"Loaded {df.height} rows, {df.width} columns")
        return df

    except Exception as e:
        logger.error(f"Failed to load Excel file: {e}")
        raise ValueError(f"Cannot parse Excel file: {e}") from e


def load_csv_to_polars(
    file: BinaryIO | Path | str,
    encoding: str = "latin-1",
    infer_schema_length: int = 10000,
) -> pl.DataFrame:
    """Load CSV file into Polars DataFrame.

    NDC columns are automatically read as strings to preserve leading zeros.

    Args:
        file: File path, path string, or file-like object.
        encoding: Character encoding. CMS files use latin-1 (not UTF-8).
        infer_schema_length: Number of rows to scan for schema inference.

    Returns:
        Polars DataFrame with loaded data.

    Raises:
        ValueError: If file cannot be parsed as CSV.
    """
    logger.info(f"Loading CSV file with encoding: {encoding}")

    try:
        # Handle different input types
        if isinstance(file, str):
            file = Path(file)

        # First pass: read headers to detect NDC columns
        if isinstance(file, Path):
            df_headers = pl.read_csv(
                file,
                encoding=encoding,
                n_rows=0,
                truncate_ragged_lines=True,
            )
        else:
            # File-like object - read bytes
            content = file.read()
            if isinstance(content, str):
                content = content.encode(encoding)
            df_headers = pl.read_csv(
                BytesIO(content),
                encoding=encoding,
                n_rows=0,
                truncate_ragged_lines=True,
            )

        # Build schema overrides for NDC columns (to preserve leading zeros)
        schema_overrides = {
            col: pl.String for col in df_headers.columns if col in NDC_COLUMN_NAMES
        }
        for col in schema_overrides:
            logger.info(f"Reading '{col}' as string to preserve leading zeros")

        # Reset file position if it's a file-like object
        if hasattr(file, "seek"):
            file.seek(0)
        elif not isinstance(file, Path):
            # Recreate BytesIO from content
            file = BytesIO(content)

        if isinstance(file, Path):
            df = pl.read_csv(
                file,
                encoding=encoding,
                infer_schema_length=infer_schema_length,
                truncate_ragged_lines=True,
                schema_overrides=schema_overrides if schema_overrides else None,
            )
        else:
            # File-like object - read bytes and parse
            if hasattr(file, "read"):
                content = file.read()
                if isinstance(content, str):
                    content = content.encode(encoding)
                file = BytesIO(content)
            df = pl.read_csv(
                file,
                encoding=encoding,
                infer_schema_length=infer_schema_length,
                truncate_ragged_lines=True,
                schema_overrides=schema_overrides if schema_overrides else None,
            )

        # Drop completely empty columns (common in CMS crosswalk files)
        non_empty_cols = [col for col in df.columns if df[col].null_count() < df.height]
        if len(non_empty_cols) < len(df.columns):
            dropped_count = len(df.columns) - len(non_empty_cols)
            logger.info(f"Dropped {dropped_count} empty columns")
            df = df.select(non_empty_cols)

        logger.info(f"Loaded {df.height} rows, {df.width} columns")
        return df

    except Exception as e:
        logger.error(f"Failed to load CSV file: {e}")
        raise ValueError(f"Cannot parse CSV file: {e}") from e


def detect_file_type(filename: str) -> str:
    """Detect file type from filename extension.

    Args:
        filename: Name of the file (with extension).

    Returns:
        File type string: "excel" or "csv".

    Raises:
        ValueError: If file type is not supported.
    """
    lower_name = filename.lower()

    if lower_name.endswith((".xlsx", ".xls")):
        return "excel"
    elif lower_name.endswith(".csv"):
        return "csv"
    else:
        raise ValueError(
            f"Unsupported file type: {filename}. Supported types: .xlsx, .xls, .csv"
        )


def load_file_auto(
    file: BinaryIO | Path | str,
    filename: str | None = None,
    sheet_name: str | int = 0,
    encoding: str = "latin-1",
) -> pl.DataFrame:
    """Auto-detect file type and load appropriately.

    Args:
        file: File path, path string, or file-like object.
        filename: Filename for type detection (required if file is BinaryIO).
        sheet_name: Sheet name for Excel files.
        encoding: Encoding for CSV files.

    Returns:
        Polars DataFrame with loaded data.

    Raises:
        ValueError: If file type cannot be determined or file cannot be loaded.
    """
    # Determine filename for type detection
    if filename is None:
        if isinstance(file, Path):
            filename = file.name
        elif isinstance(file, str):
            filename = Path(file).name
        else:
            raise ValueError("filename must be provided for file-like objects")

    file_type = detect_file_type(filename)

    if file_type == "excel":
        return load_excel_to_polars(file, sheet_name=sheet_name)
    else:
        return load_csv_to_polars(file, encoding=encoding)
