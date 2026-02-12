"""Risk badge components for IRA and Penny Pricing alerts."""

import streamlit as st

from optimizer_340b.models import Drug
from optimizer_340b.risk import check_ira_status


def render_risk_badges(drug: Drug) -> None:
    """Render risk badges for a drug.

    Displays IRA and Penny Pricing warning badges when applicable.

    Args:
        drug: Drug object to check for risk flags.
    """
    badges_rendered = False

    # Check IRA status
    ira_status = check_ira_status(drug.drug_name)

    if ira_status["is_ira_drug"]:
        _render_ira_badge(ira_status)
        badges_rendered = True

    # Check Penny Pricing flag
    if drug.penny_pricing_flag:
        _render_penny_badge()
        badges_rendered = True

    if not badges_rendered:
        st.caption("No risk flags detected")


def _render_ira_badge(ira_status: dict[str, object]) -> None:
    """Render IRA warning badge.

    Gatekeeper Test: Enbrel Simulation
    - Force-feed Enbrel into the pipeline
    - System should flag it with "High Risk / IRA 2026" warning
    """
    year = ira_status.get("ira_year", "Unknown")
    risk_level = ira_status.get("risk_level", "Unknown")
    description = ira_status.get("description", "")

    # Use error styling for high risk
    st.error(
        f"**{risk_level} / IRA {year}**\n\n"
        f"This drug is subject to Medicare price negotiation under the "
        f"Inflation Reduction Act. 340B margins may be significantly reduced "
        f"starting {year}."
    )

    if description:
        st.caption(f"Drug class: {description}")


def _render_penny_badge() -> None:
    """Render Penny Pricing warning badge.

    Gatekeeper Test: Penny Pricing Alert
    - Drugs with Penny Pricing = Yes should NOT appear in "Top Opportunities"
    """
    st.warning(
        "**Penny Pricing Alert**\n\n"
        "This drug has reached the 340B penny pricing floor. "
        "The 340B discount is already maximized, limiting margin optimization "
        "opportunities."
    )


def render_ira_badge_inline(drug_name: str) -> str:
    """Return HTML for an inline IRA badge.

    Args:
        drug_name: Name of the drug to check.

    Returns:
        HTML string for the badge, or empty string if not applicable.
    """
    ira_status = check_ira_status(drug_name)

    if ira_status["is_ira_drug"]:
        year = ira_status.get("ira_year", "Unknown")
        return (
            f'<span style="background-color: #ff4b4b; color: white; '
            f'padding: 2px 8px; border-radius: 4px; font-size: 12px;">'
            f'IRA {year}</span>'
        )

    return ""


def render_penny_badge_inline(is_penny_priced: bool) -> str:
    """Return HTML for an inline Penny Pricing badge.

    Args:
        is_penny_priced: Whether the drug has penny pricing.

    Returns:
        HTML string for the badge, or empty string if not applicable.
    """
    if is_penny_priced:
        return (
            '<span style="background-color: #ffa726; color: white; '
            'padding: 2px 8px; border-radius: 4px; font-size: 12px;">'
            'Penny Pricing</span>'
        )

    return ""


def render_risk_summary(drugs: list[Drug]) -> None:
    """Render a summary of risk flags across a drug portfolio.

    Args:
        drugs: List of Drug objects to analyze.
    """
    if not drugs:
        return

    ira_count = 0
    penny_count = 0
    ira_2026 = []
    ira_2027 = []

    for drug in drugs:
        ira_status = check_ira_status(drug.drug_name)
        if ira_status["is_ira_drug"]:
            ira_count += 1
            year = ira_status.get("ira_year")
            if year == 2026:
                ira_2026.append(drug.drug_name)
            elif year == 2027:
                ira_2027.append(drug.drug_name)

        if drug.penny_pricing_flag:
            penny_count += 1

    st.markdown("### Risk Summary")

    col1, col2 = st.columns(2)

    with col1:
        st.metric(
            label="IRA-Affected Drugs",
            value=ira_count,
            help="Drugs subject to Medicare price negotiation",
        )

        if ira_2026:
            st.caption(f"2026: {', '.join(ira_2026[:5])}")
            if len(ira_2026) > 5:
                st.caption(f"...and {len(ira_2026) - 5} more")

        if ira_2027:
            st.caption(f"2027: {', '.join(ira_2027[:5])}")
            if len(ira_2027) > 5:
                st.caption(f"...and {len(ira_2027) - 5} more")

    with col2:
        st.metric(
            label="Penny Pricing Drugs",
            value=penny_count,
            help="Drugs at 340B floor pricing",
        )

        if penny_count > 0:
            st.caption("These drugs are excluded from Top Opportunities")
