"""Margin comparison card component for 340B Optimizer."""


import streamlit as st

from optimizer_340b.models import MarginAnalysis, RecommendedPath


def render_margin_card(analysis: MarginAnalysis) -> None:
    """Render a margin comparison card for a drug.

    Displays side-by-side comparison of Retail vs Medical margins
    with the recommended path highlighted.

    Args:
        analysis: MarginAnalysis object with calculated margins.
    """
    drug = analysis.drug

    # Header with drug info
    st.subheader(f"{drug.drug_name}")
    st.caption(f"NDC: {drug.ndc_formatted} | Manufacturer: {drug.manufacturer}")

    # Create three columns for margin comparison
    col1, col2, col3 = st.columns(3)

    with col1:
        _render_retail_margin(analysis)

    with col2:
        _render_medicare_margin(analysis)

    with col3:
        _render_commercial_margin(analysis)

    # Recommendation banner
    _render_recommendation(analysis)


def _render_retail_margin(analysis: MarginAnalysis) -> None:
    """Render retail margin section."""
    is_recommended = analysis.recommended_path == RecommendedPath.RETAIL

    container_class = "recommended" if is_recommended else ""

    st.markdown(
        f"""
        <div class="margin-card {container_class}">
            <h4>Retail Pharmacy</h4>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.metric(
        label="Net Margin",
        value=f"${analysis.retail_net_margin:,.2f}",
        delta="RECOMMENDED" if is_recommended else None,
    )

    st.caption(f"Gross: ${analysis.retail_gross_margin:,.2f}")
    st.caption(f"Capture Rate: {analysis.retail_capture_rate:.0%}")

    # Provenance
    with st.expander("Calculation Details"):
        st.markdown(f"""
        **Formula:** AWP x 85% x Capture Rate - 340B Purchase Price

        - AWP: ${analysis.drug.awp:,.2f}
        - 340B Purchase Price: ${analysis.drug.contract_cost:,.2f}
        - Capture Rate: {analysis.retail_capture_rate:.0%}
        - Gross Margin: ${analysis.retail_gross_margin:,.2f}
        - Net Margin: ${analysis.retail_net_margin:,.2f}
        """)


def _render_medicare_margin(analysis: MarginAnalysis) -> None:
    """Render Medicare margin section."""
    is_recommended = analysis.recommended_path == RecommendedPath.MEDICARE_MEDICAL

    st.markdown(
        f"""
        <div class="margin-card {'recommended' if is_recommended else ''}">
            <h4>Medicare Medical</h4>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if analysis.medicare_margin is not None:
        st.metric(
            label="Margin",
            value=f"${analysis.medicare_margin:,.2f}",
            delta="RECOMMENDED" if is_recommended else None,
        )

        st.caption("ASP + 6% Reimbursement")
        st.caption(f"HCPCS: {analysis.drug.hcpcs_code}")

        # Provenance
        with st.expander("Calculation Details"):
            st.markdown(f"""
            **Formula:** ASP x 1.06 x Bill Units - 340B Purchase Price

            - ASP: ${analysis.drug.asp:,.2f}
            - Bill Units: {analysis.drug.bill_units_per_package}
            - 340B Purchase Price: ${analysis.drug.contract_cost:,.2f}
            - Margin: ${analysis.medicare_margin:,.2f}
            """)
    else:
        st.info("No HCPCS mapping available")
        st.caption("This drug cannot be billed through Medicare Part B")


def _render_commercial_margin(analysis: MarginAnalysis) -> None:
    """Render Commercial margin section."""
    is_recommended = analysis.recommended_path == RecommendedPath.COMMERCIAL_MEDICAL

    st.markdown(
        f"""
        <div class="margin-card {'recommended' if is_recommended else ''}">
            <h4>Commercial Medical</h4>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if analysis.commercial_margin is not None:
        st.metric(
            label="Margin",
            value=f"${analysis.commercial_margin:,.2f}",
            delta="RECOMMENDED" if is_recommended else None,
        )

        st.caption("ASP + 15% Reimbursement")
        st.caption(f"HCPCS: {analysis.drug.hcpcs_code}")

        # Provenance
        with st.expander("Calculation Details"):
            st.markdown(f"""
            **Formula:** ASP x 1.15 x Bill Units - 340B Purchase Price

            - ASP: ${analysis.drug.asp:,.2f}
            - Bill Units: {analysis.drug.bill_units_per_package}
            - 340B Purchase Price: ${analysis.drug.contract_cost:,.2f}
            - Margin: ${analysis.commercial_margin:,.2f}
            """)
    else:
        st.info("No HCPCS mapping available")
        st.caption("This drug cannot be billed through Commercial medical")


def _render_recommendation(analysis: MarginAnalysis) -> None:
    """Render the recommendation banner."""
    path_names = {
        RecommendedPath.RETAIL: "Retail Pharmacy",
        RecommendedPath.MEDICARE_MEDICAL: "Medicare Medical",
        RecommendedPath.COMMERCIAL_MEDICAL: "Commercial Medical",
    }

    path_name = path_names.get(analysis.recommended_path, "Unknown")

    st.success(
        f"**Recommended Path:** {path_name} "
        f"(+${analysis.margin_delta:,.2f} vs next best option)"
    )


def render_margin_summary_table(analyses: list[MarginAnalysis]) -> None:
    """Render a summary table of multiple drug analyses.

    Args:
        analyses: List of MarginAnalysis objects.
    """
    if not analyses:
        st.info("No drugs to display")
        return

    # Convert to display format
    data = [a.to_display_dict() for a in analyses]

    # Create DataFrame for display
    import polars as pl

    df = pl.DataFrame(data)

    # Select and rename columns for display
    display_df = df.select([
        pl.col("drug_name").alias("Drug"),
        pl.col("ndc").alias("NDC"),
        pl.col("retail_net_margin").alias("Retail Margin"),
        pl.col("medicare_margin").alias("Medicare Margin"),
        pl.col("commercial_margin").alias("Commercial Margin"),
        pl.col("recommendation").alias("Recommended"),
        pl.col("margin_delta").alias("Delta"),
    ])

    st.dataframe(
        display_df.to_pandas(),
        width="stretch",
        hide_index=True,
    )
