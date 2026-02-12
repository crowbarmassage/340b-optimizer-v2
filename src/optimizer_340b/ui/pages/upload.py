"""Sample data upload page for 340B Optimizer.

This is the home page for loading sample data and getting started quickly.
For manual file uploads, see the Manual Upload page.
"""

from __future__ import annotations

import logging
from pathlib import Path

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
    validate_catalog_schema,
)
from optimizer_340b.risk.ira_flags import reload_ira_drugs

# Sample data directory
SAMPLE_DATA_DIR = Path(__file__).parent.parent.parent.parent.parent / "data" / "sample"

logger = logging.getLogger(__name__)


def _check_sample_data_available() -> bool:
    """Check if sample data files are available."""
    required_files = [
        "product_catalog.xlsx",
        "asp_pricing.csv",
        "asp_crosswalk.csv",
    ]
    return all((SAMPLE_DATA_DIR / f).exists() for f in required_files)


def _load_sample_data() -> None:
    """Load sample data files into session state."""
    if "uploaded_data" not in st.session_state:
        st.session_state.uploaded_data = {}

    # Load product catalog (normalize first to map column names)
    catalog_path = SAMPLE_DATA_DIR / "product_catalog.xlsx"
    if catalog_path.exists():
        df = load_excel_to_polars(str(catalog_path))
        df = normalize_catalog(df)  # Maps Medispan AWP -> AWP, etc.
        result = validate_catalog_schema(df)
        if result.is_valid:
            st.session_state.uploaded_data["catalog"] = df
            logger.info(f"Loaded sample catalog: {df.height} rows")
        else:
            logger.warning(f"Catalog validation failed: {result.message}")

    # Load ASP pricing (CMS file with header rows)
    asp_path = SAMPLE_DATA_DIR / "asp_pricing.csv"
    if asp_path.exists():
        df = preprocess_cms_csv(str(asp_path), skip_rows=8)
        st.session_state.uploaded_data["asp_pricing"] = df
        logger.info(f"Loaded sample ASP pricing: {df.height} rows")

    # Load crosswalk (CMS file with header rows, normalize column names)
    crosswalk_path = SAMPLE_DATA_DIR / "asp_crosswalk.csv"
    if crosswalk_path.exists():
        df = preprocess_cms_csv(str(crosswalk_path), skip_rows=8)
        df = normalize_crosswalk(df)  # Maps _2025_CODE -> HCPCS Code, NDC2 -> NDC
        st.session_state.uploaded_data["crosswalk"] = df
        logger.info(f"Loaded sample crosswalk: {df.height} rows")

    # Load NADAC statistics
    nadac_path = SAMPLE_DATA_DIR / "ndc_nadac_master_statistics.csv"
    if nadac_path.exists():
        df = load_csv_to_polars(str(nadac_path))
        st.session_state.uploaded_data["nadac"] = df
        logger.info(f"Loaded sample NADAC: {df.height} rows")

    # Load biologics logic grid
    biologics_path = SAMPLE_DATA_DIR / "biologics_logic_grid.xlsx"
    if biologics_path.exists():
        df = load_excel_to_polars(str(biologics_path))
        st.session_state.uploaded_data["biologics"] = df
        logger.info(f"Loaded sample biologics grid: {df.height} rows")

    # Load NOC pricing (fallback for drugs without J-codes)
    noc_pricing_path = SAMPLE_DATA_DIR / "noc_pricing.csv"
    if noc_pricing_path.exists():
        df = preprocess_cms_csv(str(noc_pricing_path), skip_rows=12)
        df = normalize_noc_pricing(df)
        st.session_state.uploaded_data["noc_pricing"] = df
        logger.info(f"Loaded sample NOC pricing: {df.height} rows")

    # Load NOC crosswalk
    noc_crosswalk_path = SAMPLE_DATA_DIR / "noc_crosswalk.csv"
    if noc_crosswalk_path.exists():
        df = preprocess_cms_csv(str(noc_crosswalk_path), skip_rows=9)
        df = normalize_noc_crosswalk(df)
        st.session_state.uploaded_data["noc_crosswalk"] = df
        logger.info(f"Loaded sample NOC crosswalk: {df.height} rows")

    # Load Ravenswood AWP matrix
    ravenswood_path = SAMPLE_DATA_DIR / "Ravenswood_AWP_Reimbursement_Matrix.xlsx"
    if ravenswood_path.exists():
        try:
            # Load Drug Categories sheet
            import pandas as pd

            df_categories = load_excel_to_polars(
                str(ravenswood_path), sheet_name="Drug Categories"
            )
            st.session_state.uploaded_data["ravenswood_categories"] = df_categories

            # Load Summary sheet
            pdf_summary = pd.read_excel(ravenswood_path, sheet_name="Summary")
            df_summary = pl.from_pandas(pdf_summary.astype(str))
            st.session_state.uploaded_data["ravenswood_summary"] = df_summary
            logger.info(f"Loaded Ravenswood matrix: {df_categories.height} categories")
        except Exception as e:
            logger.warning(f"Could not load Ravenswood matrix: {e}")

    # Load wholesaler catalog
    wholesaler_path = SAMPLE_DATA_DIR / "wholesaler_catalog.xlsx"
    if wholesaler_path.exists():
        df = load_excel_to_polars(str(wholesaler_path))
        st.session_state.uploaded_data["wholesaler_catalog"] = df
        logger.info(f"Loaded wholesaler catalog: {df.height} rows")

    # Load IRA drug list
    ira_path = SAMPLE_DATA_DIR / "ira_drug_list.csv"
    if ira_path.exists():
        df = load_csv_to_polars(str(ira_path))
        st.session_state.uploaded_data["ira_drugs"] = df
        reload_ira_drugs(df=df)
        logger.info(f"Loaded IRA drug list: {df.height} drugs")


def _process_uploaded_data() -> None:
    """Process and normalize uploaded data."""
    from optimizer_340b.ingest.normalizers import (
        join_catalog_to_crosswalk,
        normalize_catalog,
        normalize_crosswalk,
    )

    uploaded = st.session_state.uploaded_data

    # Normalize catalog
    if "catalog" in uploaded:
        catalog_normalized = normalize_catalog(uploaded["catalog"])
        st.session_state.uploaded_data["catalog_normalized"] = catalog_normalized

    # Normalize crosswalk
    if "crosswalk" in uploaded:
        crosswalk_normalized = normalize_crosswalk(uploaded["crosswalk"])
        st.session_state.uploaded_data["crosswalk_normalized"] = crosswalk_normalized

    # Join catalog to crosswalk
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


def render_upload_page() -> None:
    """Render the sample data upload page."""
    st.title("340B Optimizer")

    st.markdown(
        """
        Welcome to the **340B Site-of-Care Optimization Engine**. This tool helps
        determine the optimal treatment pathway (Retail vs Medical) for 340B-eligible
        drugs by calculating Net Realizable Revenue.
        """
    )

    st.markdown("---")

    # Initialize session state for uploaded data
    if "uploaded_data" not in st.session_state:
        st.session_state.uploaded_data = {}

    # Sample data section
    if _check_sample_data_available():
        st.markdown("### Get Started")

        col1, col2 = st.columns([1, 2])

        with col1:
            if st.button("Load & Process Sample Data", type="primary", use_container_width=True):
                with st.spinner("Loading and processing sample data..."):
                    _load_sample_data()
                    _process_uploaded_data()
                st.success("Sample data loaded! Navigate to Dashboard to explore.")
                st.rerun()

        with col2:
            st.markdown(
                """
                Click to instantly load all sample data files:
                - Product Catalog (34K+ drugs)
                - ASP Pricing & Crosswalk
                - NADAC Statistics
                - Biologics Logic Grid
                - AWP Reimbursement Matrix
                - And more...
                """
            )

        st.markdown("---")

        # Data status
        _render_data_status()

    else:
        st.error(
            "Sample data files not found. Please ensure sample data is available in "
            f"`{SAMPLE_DATA_DIR}`"
        )

    # Footer with link to manual upload
    st.markdown("---")
    st.caption(
        "Need to upload your own data files? Use the **Manual Upload** page "
        "in the sidebar navigation."
    )


def _render_data_status() -> None:
    """Render current data loading status."""
    uploaded = st.session_state.get("uploaded_data", {})

    if not uploaded:
        st.info("No data loaded yet. Click the button above to load sample data.")
        return

    st.markdown("### Data Status")

    files = [
        ("catalog", "Product Catalog"),
        ("asp_pricing", "ASP Pricing"),
        ("crosswalk", "NDC-HCPCS Crosswalk"),
        ("nadac", "NADAC Statistics"),
        ("biologics", "Biologics Logic Grid"),
        ("noc_pricing", "NOC Pricing"),
        ("noc_crosswalk", "NOC Crosswalk"),
        ("ravenswood_categories", "AWP Matrix"),
        ("wholesaler_catalog", "Wholesaler Catalog"),
        ("ira_drugs", "IRA Drug List"),
    ]

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Core Files**")
        for key, name in files[:5]:
            if key in uploaded:
                df = uploaded[key]
                st.markdown(f"\u2705 {name}: {df.height:,} rows")
            else:
                st.markdown(f"\u2b1c {name}")

    with col2:
        st.markdown("**Additional Files**")
        for key, name in files[5:]:
            if key in uploaded:
                df = uploaded[key]
                st.markdown(f"\u2705 {name}: {df.height:,} rows")
            else:
                st.markdown(f"\u2b1c {name}")

    # Ready message
    if "catalog" in uploaded and "asp_pricing" in uploaded and "crosswalk" in uploaded:
        st.success(
            "Data loaded! Select **Dashboard** from the sidebar to view "
            "optimization opportunities."
        )
