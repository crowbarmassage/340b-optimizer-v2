"""Manual file upload page for 340B Optimizer.

This page contains all manual file upload functionality.
For quick testing, use the main Upload Data page with sample data.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import polars as pl
import streamlit as st

from optimizer_340b.ingest.loaders import load_csv_to_polars, load_excel_to_polars
from optimizer_340b.ingest.normalizers import (
    normalize_catalog,
    normalize_crosswalk,
    normalize_noc_crosswalk,
    normalize_noc_pricing,
    preprocess_cms_csv,
)
from optimizer_340b.ingest.validators import (
    ValidationResult,
    validate_asp_schema,
    validate_catalog_schema,
    validate_crosswalk_schema,
    validate_nadac_schema,
    validate_noc_crosswalk_schema,
    validate_noc_pricing_schema,
)
from optimizer_340b.risk.ira_flags import reload_ira_drugs

logger = logging.getLogger(__name__)


def _load_cms_csv_with_skip(uploaded_file: Any, skip_rows: int = 8) -> pl.DataFrame:
    """Load CMS CSV file, skipping header metadata rows."""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name

    try:
        return preprocess_cms_csv(tmp_path, skip_rows=skip_rows)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def render_manual_upload_page() -> None:
    """Render the manual file upload page."""
    st.title("Manual Data Upload")

    st.warning(
        "**Advanced Feature:** This page is for manually uploading individual data files. "
        "For quick testing, use the **Upload Data** page with the sample data button."
    )

    st.markdown("---")

    # Initialize session state
    if "uploaded_data" not in st.session_state:
        st.session_state.uploaded_data = {}

    # File upload sections
    _render_catalog_upload()
    _render_asp_pricing_upload()
    _render_crosswalk_upload()
    _render_noc_pricing_upload()
    _render_noc_crosswalk_upload()
    _render_nadac_upload()
    _render_biologics_upload()
    _render_ravenswood_upload()
    _render_wholesaler_upload()
    _render_ira_upload()

    # Validation summary
    st.markdown("---")
    _render_validation_summary()


def _render_catalog_upload() -> None:
    """Render product catalog upload section."""
    st.markdown("### Product Catalog *")
    st.caption(
        "Excel file containing NDC, Drug Name, Contract Cost, and AWP. "
        "Expected columns: NDC, Drug Name, Contract Cost, AWP (or Medispan AWP)"
    )

    uploaded_file = st.file_uploader(
        "Upload Product Catalog",
        type=["xlsx", "xls"],
        key="manual_catalog_upload",
        help="Your 340B product catalog with pricing information",
    )

    if uploaded_file is not None:
        with st.spinner("Loading catalog..."):
            try:
                df = load_excel_to_polars(uploaded_file)
                result = validate_catalog_schema(df)

                if result.is_valid:
                    st.session_state.uploaded_data["catalog"] = df
                    st.success(f"Loaded {df.height:,} drugs from catalog")
                    _show_validation_result(result)

                    with st.expander("Preview Data"):
                        st.dataframe(df.head(10).to_pandas(), width="stretch")
                else:
                    st.error("Validation failed")
                    _show_validation_result(result)

            except Exception as e:
                st.error(f"Error loading file: {e}")
                logger.exception("Error loading catalog")


def _render_asp_pricing_upload() -> None:
    """Render ASP pricing file upload section."""
    st.markdown("### ASP Pricing File *")
    st.caption(
        "CMS ASP pricing file (CSV). Note: First 8 rows are typically header metadata. "
        "Expected columns: HCPCS Code, Payment Limit"
    )

    uploaded_file = st.file_uploader(
        "Upload ASP Pricing File",
        type=["csv"],
        key="manual_asp_upload",
        help="CMS Medicare Part B ASP pricing file",
    )

    if uploaded_file is not None:
        with st.spinner("Loading ASP pricing..."):
            try:
                df = _load_cms_csv_with_skip(uploaded_file, skip_rows=8)
                result = validate_asp_schema(df)

                if result.is_valid:
                    st.session_state.uploaded_data["asp_pricing"] = df
                    st.success(f"Loaded {df.height:,} HCPCS pricing records")
                    _show_validation_result(result)

                    with st.expander("Preview Data"):
                        st.dataframe(df.head(10).to_pandas(), width="stretch")
                else:
                    st.error("Validation failed")
                    _show_validation_result(result)

            except Exception as e:
                st.error(f"Error loading file: {e}")
                logger.exception("Error loading ASP pricing")


def _render_crosswalk_upload() -> None:
    """Render NDC-HCPCS crosswalk upload section."""
    st.markdown("### ASP NDC-HCPCS Crosswalk *")
    st.caption(
        "CMS crosswalk mapping NDC to HCPCS codes (CSV). "
        "Note: First 8 rows are typically header metadata. "
        "Expected columns: NDC (or NDC2), HCPCS Code (or _2025_CODE)"
    )

    uploaded_file = st.file_uploader(
        "Upload NDC-HCPCS Crosswalk",
        type=["csv"],
        key="manual_crosswalk_upload",
        help="CMS NDC to HCPCS code mapping file",
    )

    if uploaded_file is not None:
        with st.spinner("Loading crosswalk..."):
            try:
                df = _load_cms_csv_with_skip(uploaded_file, skip_rows=8)
                result = validate_crosswalk_schema(df)

                if result.is_valid:
                    st.session_state.uploaded_data["crosswalk"] = df
                    st.success(f"Loaded {df.height:,} NDC-HCPCS mappings")
                    _show_validation_result(result)

                    with st.expander("Preview Data"):
                        st.dataframe(df.head(10).to_pandas(), width="stretch")
                else:
                    st.error("Validation failed")
                    _show_validation_result(result)

            except Exception as e:
                st.error(f"Error loading file: {e}")
                logger.exception("Error loading crosswalk")


def _render_noc_pricing_upload() -> None:
    """Render NOC pricing file upload section."""
    st.markdown("### NOC Pricing File (Optional)")
    st.caption(
        "CMS NOC pricing file for drugs without permanent J-codes (CSV). "
        "Provides fallback reimbursement rates for new drugs. "
        "Expected columns: Drug Generic Name, Payment Limit"
    )

    uploaded_file = st.file_uploader(
        "Upload NOC Pricing File",
        type=["csv"],
        key="manual_noc_pricing_upload",
        help="CMS NOC (Not Otherwise Classified) drug pricing file",
    )

    if uploaded_file is not None:
        with st.spinner("Loading NOC pricing..."):
            try:
                df = _load_cms_csv_with_skip(uploaded_file, skip_rows=12)
                df = normalize_noc_pricing(df)
                result = validate_noc_pricing_schema(df)

                if result.is_valid:
                    st.session_state.uploaded_data["noc_pricing"] = df
                    st.success(f"Loaded {df.height:,} NOC drug pricing records")
                    _show_validation_result(result)

                    with st.expander("Preview Data"):
                        st.dataframe(df.head(10).to_pandas(), width="stretch")
                else:
                    st.error("Validation failed")
                    _show_validation_result(result)

            except Exception as e:
                st.error(f"Error loading file: {e}")
                logger.exception("Error loading NOC pricing")


def _render_noc_crosswalk_upload() -> None:
    """Render NOC crosswalk file upload section."""
    st.markdown("### NOC NDC-HCPCS Crosswalk (Optional)")
    st.caption(
        "CMS NOC crosswalk for drugs without permanent J-codes (CSV). "
        "Maps NDCs to generic drug names for fallback pricing lookup. "
        "Expected columns: NDC, Drug Generic Name"
    )

    uploaded_file = st.file_uploader(
        "Upload NOC Crosswalk",
        type=["csv"],
        key="manual_noc_crosswalk_upload",
        help="CMS NOC NDC to generic drug name mapping file",
    )

    if uploaded_file is not None:
        with st.spinner("Loading NOC crosswalk..."):
            try:
                df = _load_cms_csv_with_skip(uploaded_file, skip_rows=9)
                df = normalize_noc_crosswalk(df)
                result = validate_noc_crosswalk_schema(df)

                if result.is_valid:
                    st.session_state.uploaded_data["noc_crosswalk"] = df
                    st.success(f"Loaded {df.height:,} NOC NDC mappings")
                    _show_validation_result(result)

                    with st.expander("Preview Data"):
                        st.dataframe(df.head(10).to_pandas(), width="stretch")
                else:
                    st.error("Validation failed")
                    _show_validation_result(result)

            except Exception as e:
                st.error(f"Error loading file: {e}")
                logger.exception("Error loading NOC crosswalk")


def _render_nadac_upload() -> None:
    """Render NADAC statistics upload section."""
    st.markdown("### NADAC Statistics (Optional)")
    st.caption(
        "NADAC pricing statistics for penny pricing detection (CSV). "
        "Expected columns: ndc, total_discount_340b_pct"
    )

    uploaded_file = st.file_uploader(
        "Upload NADAC Statistics",
        type=["csv"],
        key="manual_nadac_upload",
        help="National Average Drug Acquisition Cost statistics",
    )

    if uploaded_file is not None:
        with st.spinner("Loading NADAC data..."):
            try:
                df = load_csv_to_polars(uploaded_file)
                result = validate_nadac_schema(df)

                if result.is_valid:
                    st.session_state.uploaded_data["nadac"] = df
                    st.success(f"Loaded {df.height:,} NADAC records")
                    _show_validation_result(result)

                    with st.expander("Preview Data"):
                        st.dataframe(df.head(10).to_pandas(), width="stretch")
                else:
                    st.warning("Validation warnings")
                    _show_validation_result(result)

            except Exception as e:
                st.error(f"Error loading file: {e}")
                logger.exception("Error loading NADAC")


def _render_biologics_upload() -> None:
    """Render biologics logic grid upload section."""
    st.markdown("### Biologics Logic Grid (Optional)")
    st.caption(
        "Excel file with loading dose patterns for biologics. "
        "Expected columns: Drug Name, Indication, Year 1 Fills, Year 2+ Fills"
    )

    uploaded_file = st.file_uploader(
        "Upload Biologics Logic Grid",
        type=["xlsx", "xls"],
        key="manual_biologics_upload",
        help="Loading dose schedule for biologics",
    )

    if uploaded_file is not None:
        with st.spinner("Loading biologics grid..."):
            try:
                df = load_excel_to_polars(uploaded_file)
                st.session_state.uploaded_data["biologics"] = df
                st.success(f"Loaded {df.height:,} dosing profiles")

                with st.expander("Preview Data"):
                    st.dataframe(df.head(10).to_pandas(), width="stretch")

            except Exception as e:
                st.error(f"Error loading file: {e}")
                logger.exception("Error loading biologics grid")


def _render_ravenswood_upload() -> None:
    """Render Ravenswood AWP Reimbursement Matrix upload section."""
    st.markdown("### AWP Reimbursement Matrix (Optional)")
    st.caption(
        "Excel file with payer-specific AWP multipliers for retail revenue "
        "calculation. Contains drug category classifications "
        "(Generic/Brand/Specialty) and payer mix. "
        "If not provided, a default 85% AWP multiplier will be used."
    )

    uploaded_file = st.file_uploader(
        "Upload AWP Reimbursement Matrix",
        type=["xlsx", "xls"],
        key="manual_ravenswood_upload",
        help="Payer-specific AWP reimbursement multipliers",
    )

    if uploaded_file is not None:
        with st.spinner("Loading AWP matrix..."):
            try:
                df_categories = load_excel_to_polars(
                    uploaded_file, sheet_name="Drug Categories"
                )
                st.session_state.uploaded_data["ravenswood_categories"] = df_categories

                uploaded_file.seek(0)
                pdf_summary = pd.read_excel(uploaded_file, sheet_name="Summary")
                df_summary = pl.from_pandas(pdf_summary.astype(str))
                st.session_state.uploaded_data["ravenswood_summary"] = df_summary

                st.success(
                    f"Loaded AWP matrix: {df_categories.height} drug categories, "
                    f"{df_summary.height} payer entries"
                )

                with st.expander("Preview Drug Categories"):
                    st.dataframe(df_categories.head(10).to_pandas(), width="stretch")

                with st.expander("Preview Payer Summary"):
                    st.dataframe(df_summary.head(10).to_pandas(), width="stretch")

            except Exception as e:
                st.error(f"Error loading file: {e}")
                logger.exception("Error loading Ravenswood matrix")


def _render_wholesaler_upload() -> None:
    """Render Wholesaler Catalog upload section."""
    st.markdown("### Wholesaler Catalog (Optional)")
    st.caption(
        "Excel file with real-world retail pricing for validation. "
        "Used to flag records where calculated retail differs from actual by >20%. "
        "Expected column: Product Catalog Unit Price (Current Retail) Average"
    )

    uploaded_file = st.file_uploader(
        "Upload Wholesaler Catalog",
        type=["xlsx", "xls"],
        key="manual_wholesaler_upload",
        help="Wholesaler pricing data for retail validation",
    )

    if uploaded_file is not None:
        with st.spinner("Loading wholesaler catalog..."):
            try:
                df = load_excel_to_polars(uploaded_file)
                st.session_state.uploaded_data["wholesaler_catalog"] = df
                st.success(f"Loaded {df.height:,} wholesaler catalog entries")

                with st.expander("Preview Data"):
                    st.dataframe(df.head(10).to_pandas(), width="stretch")

            except Exception as e:
                st.error(f"Error loading file: {e}")
                logger.exception("Error loading wholesaler catalog")


def _render_ira_upload() -> None:
    """Render IRA Drug List upload section."""
    st.markdown("### IRA Drug List (Optional)")
    st.caption(
        "CSV file with IRA (Inflation Reduction Act) negotiated drugs. "
        "Updates the IRA risk flagging with the latest drug list. "
        "Expected columns: drug_name, ira_year, description"
    )

    uploaded_file = st.file_uploader(
        "Upload IRA Drug List",
        type=["csv"],
        key="manual_ira_upload",
        help="List of drugs subject to Medicare price negotiation under IRA",
    )

    if uploaded_file is not None:
        with st.spinner("Loading IRA drug list..."):
            try:
                df = load_csv_to_polars(uploaded_file)

                expected_cols = {"drug_name", "ira_year", "description"}
                actual_cols = set(df.columns)
                if not expected_cols.issubset(actual_cols):
                    missing = expected_cols - actual_cols
                    st.error(f"Missing required columns: {', '.join(missing)}")
                    return

                st.session_state.uploaded_data["ira_drugs"] = df
                reload_ira_drugs(df=df)
                st.success(f"Loaded {df.height:,} IRA drugs and updated risk flags")

                year_counts = df.group_by("ira_year").len().sort("ira_year")
                st.caption(
                    "Drugs by year: "
                    + ", ".join(
                        f"{row['ira_year']}: {row['len']}"
                        for row in year_counts.iter_rows(named=True)
                    )
                )

                with st.expander("Preview Data"):
                    st.dataframe(df.head(10).to_pandas(), width="stretch")

            except Exception as e:
                st.error(f"Error loading file: {e}")
                logger.exception("Error loading IRA drug list")


def _show_validation_result(result: ValidationResult) -> None:
    """Display validation result details."""
    if result.warnings:
        for warning in result.warnings:
            st.warning(warning)

    if not result.is_valid:
        st.error(result.message)
        if result.missing_columns:
            st.error(f"Missing columns: {', '.join(result.missing_columns)}")


def _render_validation_summary() -> None:
    """Render summary of uploaded data and readiness status."""
    st.markdown("### Upload Status")

    uploaded = st.session_state.get("uploaded_data", {})

    required = {
        "catalog": "Product Catalog",
        "asp_pricing": "ASP Pricing",
        "crosswalk": "NDC-HCPCS Crosswalk",
    }

    optional = {
        "noc_pricing": "NOC Pricing (fallback)",
        "noc_crosswalk": "NOC Crosswalk (fallback)",
        "nadac": "NADAC Statistics",
        "biologics": "Biologics Logic Grid",
        "ravenswood_categories": "AWP Reimbursement Matrix",
        "wholesaler_catalog": "Wholesaler Catalog (validation)",
        "ira_drugs": "IRA Drug List",
    }

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Required Files**")
        all_required = True
        for key, name in required.items():
            if key in uploaded:
                st.markdown(f"- :white_check_mark: {name}")
            else:
                st.markdown(f"- :x: {name}")
                all_required = False

    with col2:
        st.markdown("**Optional Files**")
        for key, name in optional.items():
            if key in uploaded:
                st.markdown(f"- :white_check_mark: {name}")
            else:
                st.markdown(f"- :heavy_minus_sign: {name}")

    st.markdown("---")

    if all_required:
        st.success(
            "All required files uploaded! "
            "Select **Dashboard** from the sidebar to view optimization opportunities."
        )

        if st.button("Process Data", type="primary", key="manual_process_data"):
            with st.spinner("Processing data..."):
                _process_uploaded_data()
            st.success("Data processed! Use sidebar to navigate to Dashboard.")
    else:
        st.info("Upload all required files to proceed to analysis.")


def _process_uploaded_data() -> None:
    """Process and normalize uploaded data."""
    from optimizer_340b.ingest.normalizers import (
        join_catalog_to_crosswalk,
        normalize_catalog,
        normalize_crosswalk,
    )

    uploaded = st.session_state.uploaded_data

    if "catalog" in uploaded:
        catalog_normalized = normalize_catalog(uploaded["catalog"])
        st.session_state.uploaded_data["catalog_normalized"] = catalog_normalized

    if "crosswalk" in uploaded:
        crosswalk_normalized = normalize_crosswalk(uploaded["crosswalk"])
        st.session_state.uploaded_data["crosswalk_normalized"] = crosswalk_normalized

    catalog_ready = "catalog_normalized" in st.session_state.uploaded_data
    crosswalk_ready = "crosswalk_normalized" in st.session_state.uploaded_data
    if catalog_ready and crosswalk_ready:
        joined_df, orphan_df = join_catalog_to_crosswalk(
            st.session_state.uploaded_data["catalog_normalized"],
            st.session_state.uploaded_data["crosswalk_normalized"],
        )
        st.session_state.uploaded_data["joined_data"] = joined_df
        st.session_state.uploaded_data["orphan_data"] = orphan_df

    st.session_state.data_processed = True
