"""Main Streamlit application for 340B Site-of-Care Optimization Engine.

Run with: streamlit run src/optimizer_340b/ui/app.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import streamlit as st

# Add src to path for imports when running directly
src_path = Path(__file__).parent.parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Main entry point for Streamlit application."""
    # Import pages here to avoid E402 at module level
    from optimizer_340b.ui.pages.dashboard import render_dashboard_page
    from optimizer_340b.ui.pages.drug_detail import render_drug_detail_page
    from optimizer_340b.ui.pages.manual_upload import render_manual_upload_page
    from optimizer_340b.ui.pages.ndc_lookup import render_ndc_lookup_page
    from optimizer_340b.ui.pages.upload import render_upload_page

    # Page configuration - must be first Streamlit command
    st.set_page_config(
        page_title="340B Optimizer",
        page_icon="\U0001f48a",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Define pages for navigation
    pages = {
        "Upload Data": render_upload_page,
        "Dashboard": render_dashboard_page,
        "Drug Detail": render_drug_detail_page,
        "NDC Lookup": render_ndc_lookup_page,
        "Manual Upload": render_manual_upload_page,
    }

    # Custom CSS
    _apply_custom_styles()

    # Sidebar header
    st.sidebar.title("\U0001f48a 340B Optimizer")
    st.sidebar.caption("Site-of-Care Optimization Engine")
    st.sidebar.markdown("---")

    # Navigation using radio buttons for clear selection
    st.sidebar.markdown("### Navigation")
    selected_page = st.sidebar.radio(
        label="Select Page",
        options=list(pages.keys()),
        index=0,
        label_visibility="collapsed",
    )

    st.sidebar.markdown("---")

    # Data status
    st.sidebar.markdown("### Data Status")
    _render_data_status()

    st.sidebar.markdown("---")

    # About section
    with st.sidebar.expander("About"):
        st.markdown(
            """
            **340B Optimizer** determines the optimal treatment pathway
            (Retail vs Medical) for 340B-eligible drugs by calculating
            Net Realizable Revenue.

            **Key Features:**
            - Dual-channel margin comparison
            - Payer-adjusted revenue modeling
            - Capture rate stress testing
            - Loading dose impact analysis
            - IRA & Penny Pricing risk flags

            **Version:** 0.1.0
            """
        )

    # Render selected page
    pages[selected_page]()


def _apply_custom_styles() -> None:
    """Apply custom CSS styles that work with light and dark themes."""
    st.markdown(
        """
        <style>
        /* Main container */
        .main {
            padding: 1rem;
        }

        /* Metric cards */
        [data-testid="stMetricValue"] {
            font-size: 1.5rem;
        }

        /* Recommended badge styling */
        .recommended {
            border: 2px solid #28a745;
            border-radius: 8px;
            padding: 1rem;
        }

        /* Margin card styling */
        .margin-card {
            padding: 0.5rem;
            border-radius: 4px;
        }

        .margin-card h4 {
            margin: 0;
            font-size: 1.1rem;
        }

        /* Risk badge inline */
        .risk-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
        }

        .risk-badge.ira {
            background-color: #ff4b4b;
            color: white;
        }

        .risk-badge.penny {
            background-color: #ffa726;
            color: white;
        }

        /* Button styling */
        .stButton > button {
            border-radius: 4px;
        }

        /* Expander styling */
        .streamlit-expanderHeader {
            font-weight: bold;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_data_status() -> None:
    """Render data loading status in sidebar."""
    uploaded = st.session_state.get("uploaded_data", {})

    files = [
        ("catalog", "Product Catalog"),
        ("asp_pricing", "ASP Pricing"),
        ("crosswalk", "Crosswalk"),
        ("noc_pricing", "NOC Pricing (optional)"),
        ("noc_crosswalk", "NOC Crosswalk (optional)"),
        ("nadac", "NADAC (optional)"),
        ("biologics", "Biologics (optional)"),
        ("ravenswood_categories", "AWP Matrix (optional)"),
        ("wholesaler_catalog", "Wholesaler (optional)"),
        ("ira_drugs", "IRA Drugs (optional)"),
    ]

    for key, name in files:
        if key in uploaded:
            df = uploaded[key]
            st.sidebar.markdown(f"\u2705 {name}: {df.height:,} rows")
        else:
            if "optional" in name:
                st.sidebar.markdown(f"\u2b1c {name}")
            else:
                st.sidebar.markdown(f"\u274c {name}")


if __name__ == "__main__":
    main()
