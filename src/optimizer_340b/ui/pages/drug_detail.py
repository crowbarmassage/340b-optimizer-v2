"""Drug detail page for 340B Optimizer - Single drug deep-dive."""

import logging
from decimal import Decimal

import plotly.graph_objects as go  # type: ignore[import-untyped]
import streamlit as st

from optimizer_340b.compute.dosing import apply_loading_dose_logic
from optimizer_340b.compute.margins import (
    analyze_drug_margin,
    analyze_drug_margin_5pathway,
    calculate_margin_sensitivity,
)
from optimizer_340b.ingest.normalizers import normalize_ndc
from optimizer_340b.models import Drug, MarginAnalysis
from optimizer_340b.risk import check_ira_status
from optimizer_340b.risk.manufacturer_cp import check_cp_restriction
from optimizer_340b.ui.components.drug_search import render_drug_search
from optimizer_340b.ui.components.risk_badge import render_risk_badges

logger = logging.getLogger(__name__)


def render_drug_detail_page() -> None:
    """Render the drug detail page.

    Shows comprehensive analysis for a single drug including:
    - Margin comparison across pathways
    - Capture rate sensitivity analysis
    - Loading dose impact (for biologics)
    - Risk flags and warnings
    - Calculation provenance
    """
    st.title("Drug Detail Analysis")

    # Get selected drug or show search
    drug = _get_or_search_drug()

    if drug is None:
        return

    # Off-Contract alert
    if drug.off_contract:
        st.warning(
            "**Off-Contract Drug:** The 340B Purchase Price shown is the current "
            "catalog unit price, not a contracted 340B price. Margins may not "
            "reflect actual 340B savings."
        )

    # Main content
    _render_drug_header(drug)

    # Risk warnings at top
    st.markdown("### Risk Assessment")
    render_risk_badges(drug)

    # Manufacturer Risk Assessment (directly below Risk Assessment)
    _render_manufacturer_risk_assessment(drug)

    st.markdown("---")

    # Margin Analysis with 5 pathways
    st.markdown("### Margin Analysis")

    # Configurable inputs in expander
    with st.expander("Adjust Analysis Parameters", expanded=False):
        param_col1, param_col2, param_col3 = st.columns(3)

        with param_col1:
            dispense_fee = st.number_input(
                "Dispense Fee ($)",
                min_value=0.0,
                max_value=100.0,
                value=0.0,
                step=0.50,
                help="Medicaid pharmacy dispense fee",
                key="dispense_fee",
            )
            medicaid_markup = st.number_input(
                "Medicaid Markup (%)",
                min_value=0.0,
                max_value=50.0,
                value=0.0,
                step=1.0,
                help="Additional Medicaid pharmacy markup percentage",
                key="medicaid_markup",
            )

        with param_col2:
            commercial_asp_pct = st.number_input(
                "Commercial ASP Markup (%)",
                min_value=0.0,
                max_value=50.0,
                value=15.0,
                step=1.0,
                help="Commercial medical ASP markup (default 15%)",
                key="commercial_asp_pct",
            )

        with param_col3:
            capture_rate_pct = st.number_input(
                "Capture Rate (%)",
                min_value=0.0,
                max_value=100.0,
                value=100.0,
                step=5.0,
                help="Pharmacy channel capture rate",
                key="capture_rate_pct",
            )

    # Convert inputs to Decimals
    capture_rate = Decimal(str(capture_rate_pct)) / Decimal("100")
    dispense_fee_dec = Decimal(str(dispense_fee))
    medicaid_markup_dec = Decimal(str(medicaid_markup)) / Decimal("100")
    commercial_asp_dec = Decimal(str(commercial_asp_pct)) / Decimal("100")

    # Perform 5-pathway analysis
    analysis = analyze_drug_margin_5pathway(
        drug,
        capture_rate=capture_rate,
        dispense_fee=dispense_fee_dec,
        medicaid_markup_pct=medicaid_markup_dec,
        commercial_asp_pct=commercial_asp_dec,
    )

    # Display 5 margin cards
    _render_5_margin_cards(drug, analysis, capture_rate)

    st.markdown("---")

    # Sensitivity analysis (uses legacy analysis for now)
    st.markdown("### Capture Rate Sensitivity")
    _render_sensitivity_chart(drug)

    st.markdown("---")

    # Loading dose analysis (if biologic)
    if drug.is_biologic or _has_loading_dose(drug):
        st.markdown("### Loading Dose Impact")
        _render_loading_dose_analysis(drug, analysis)
        st.markdown("---")

    # Provenance chain
    st.markdown("### Calculation Provenance")
    _render_provenance_chain(
        drug,
        analysis,
        capture_rate=capture_rate,
        dispense_fee=dispense_fee_dec,
        medicaid_markup_pct=medicaid_markup_dec,
        commercial_asp_pct=commercial_asp_dec,
    )


def _get_or_search_drug() -> Drug | None:
    """Get selected drug from session state or show search."""
    # Check if drug was selected from dashboard or previous search
    selected_ndc = st.session_state.get("selected_drug")

    if selected_ndc:
        drug = _lookup_drug_by_ndc(selected_ndc)
        if drug:
            # Show current drug with option to search new
            col1, col2 = st.columns([3, 1])
            with col1:
                st.info(
                    f"Currently viewing: **{drug.drug_name}** ({drug.ndc_formatted})"
                )
            with col2:
                if st.button("Search New Drug", type="secondary"):
                    st.session_state.selected_drug = None
                    # Clear search component state so it doesn't re-select the old drug
                    for key in ["detail_selected_ndc", "detail_hcpcs_results",
                                "detail_name_results", "detail_query"]:
                        st.session_state.pop(key, None)
                    st.rerun()
            return drug

    # Show enhanced search interface
    st.markdown("### Search for a Drug")
    st.caption("Search by drug name, 11-digit NDC, or HCPCS code (e.g., J0135)")

    # Use enhanced search component (supports Enter key via form)
    # Component handles multiple matches internally and returns selected NDC
    search_result = render_drug_search(key_prefix="detail")

    if search_result:
        # Filter hints (e.g. "name:humira", "hcpcs:J0135") mean the user
        # is still picking from a multi-match list — don't treat as NDC
        if search_result.startswith("name:") or search_result.startswith("hcpcs:"):
            return None
        drug = _lookup_drug_by_ndc(search_result)
        if drug:
            st.session_state.selected_drug = drug.ndc
            st.rerun()
        else:
            st.error(f"No drug found with NDC '{search_result}'.")

    # Demo mode - search for actual drugs in uploaded data
    st.markdown("---")
    st.markdown("**Quick Demo:**")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Demo: HUMIRA", key="demo_humira"):
            drug = _search_drug("HUMIRA")
            if drug:
                st.session_state.selected_drug = drug.ndc
                st.rerun()
            else:
                st.warning("HUMIRA not found in uploaded data.")

    with col2:
        if st.button("Demo: ENBREL (IRA 2026)", key="demo_enbrel"):
            drug = _search_drug("ENBREL")
            if drug:
                st.session_state.selected_drug = drug.ndc
                st.rerun()
            else:
                st.warning("ENBREL not found in uploaded data.")

    return None


def _lookup_drug_by_ndc(ndc: str) -> Drug | None:
    """Look up drug by NDC from uploaded data.

    Supports NDC input in both 11-digit and 5-4-2 dash format.
    """
    uploaded = st.session_state.get("uploaded_data", {})
    catalog = uploaded.get("catalog")

    if catalog is None:
        return _create_demo_drug("HUMIRA")  # Fallback to demo

    # Normalize input NDC for matching
    ndc_normalized = normalize_ndc(ndc)

    for row in catalog.iter_rows(named=True):
        row_ndc = normalize_ndc(str(row.get("NDC", "")))
        if row_ndc == ndc_normalized:
            return _row_to_drug(row)

    return None


def _search_drug(query: str) -> Drug | None:
    """Search for drug by name or NDC.

    Supports NDC input in both 11-digit and 5-4-2 dash format.
    """
    uploaded = st.session_state.get("uploaded_data", {})
    catalog = uploaded.get("catalog")

    if catalog is None:
        # Check if it's a demo drug
        if "HUMIRA" in query.upper():
            return _create_demo_drug("HUMIRA")
        if "ENBREL" in query.upper():
            return _create_demo_drug("ENBREL")
        return None

    query_upper = query.upper()
    query_ndc = normalize_ndc(query)  # Normalize for NDC matching (handles dashes)

    for row in catalog.iter_rows(named=True):
        drug_name = str(row.get("Drug Name") or row.get("Trade Name") or "").upper()
        ndc = str(row.get("NDC", ""))
        ndc_normalized = normalize_ndc(ndc)

        # Match by drug name or normalized NDC
        if query_upper in drug_name or query_ndc == ndc_normalized:
            return _row_to_drug(row)

    return None


def _row_to_drug(row: dict[str, object]) -> Drug:
    """Convert catalog row to Drug object."""
    from optimizer_340b.compute.retail_pricing import DrugCategory, classify_drug_category
    from optimizer_340b.risk.penny_pricing import build_nadac_lookup
    from optimizer_340b.ui.pages.dashboard import _build_hcpcs_lookup

    uploaded = st.session_state.get("uploaded_data", {})
    hcpcs_lookup = _build_hcpcs_lookup(
        uploaded.get("crosswalk"),
        uploaded.get("asp_pricing"),
    )
    nadac_df = uploaded.get("nadac")
    nadac_lookup = build_nadac_lookup(nadac_df) if nadac_df is not None else {}

    ndc = str(row.get("NDC", ""))
    ndc_normalized = ndc.replace("-", "").strip()

    drug_name = (
        row.get("Drug Name")
        or row.get("Trade Name")
        or "Unknown"
    )

    # Get contract cost (340B acquisition cost from Unit Price Current Catalog)
    contract_cost_raw = (
        row.get("Unit Price (Current Catalog)")
        or row.get("Contract Cost")
        or 0
    )
    contract_cost = Decimal(str(contract_cost_raw) if contract_cost_raw else "0")
    awp = Decimal(str(row.get("AWP") or row.get("Medispan AWP") or 0))

    hcpcs_info = hcpcs_lookup.get(ndc_normalized, {})
    nadac_info = nadac_lookup.get(ndc_normalized, {})

    ira_status = check_ira_status(str(drug_name))

    hcpcs_code = hcpcs_info.get("hcpcs_code")
    bill_units = hcpcs_info.get("bill_units", 1)

    # Get NADAC price (most recent)
    nadac_price = nadac_info.get("nadac_price")

    # Classify drug as Brand/Specialty (is_brand=True) or Generic (is_brand=False)
    drug_category = classify_drug_category(str(drug_name))
    is_brand = drug_category != DrugCategory.GENERIC

    # Detect Off-Contract drugs
    contract_name = str(row.get("Contract Name", "")).strip()
    off_contract = contract_name == "Off-Contract"

    return Drug(
        ndc=ndc,
        drug_name=str(drug_name),
        manufacturer=str(row.get("Manufacturer", "Unknown")),
        contract_cost=contract_cost,
        awp=awp,
        asp=Decimal(str(hcpcs_info.get("asp"))) if hcpcs_info.get("asp") else None,
        hcpcs_code=str(hcpcs_code) if hcpcs_code else None,
        bill_units_per_package=int(str(bill_units)) if bill_units else 1,
        is_brand=is_brand,
        ira_flag=bool(ira_status.get("is_ira_drug", False)),
        penny_pricing_flag=bool(nadac_info.get("is_penny_priced", False)),
        off_contract=off_contract,
        nadac_price=nadac_price,
    )


def _create_demo_drug(name: str) -> Drug:
    """Create a demo drug for testing."""
    if name == "ENBREL":
        return Drug(
            ndc="55555555555",  # 11-digit NDC
            drug_name="ENBREL",
            manufacturer="AMGEN",
            contract_cost=Decimal("200.00"),
            awp=Decimal("7000.00"),
            asp=Decimal("3000.00"),
            hcpcs_code="J1438",
            bill_units_per_package=4,
            therapeutic_class="TNF Inhibitor",
            is_biologic=True,
            ira_flag=True,  # ENBREL is IRA 2026
            penny_pricing_flag=False,
        )
    else:  # HUMIRA
        return Drug(
            ndc="00074433902",  # 11-digit NDC (00074-4339-02)
            drug_name="HUMIRA",
            manufacturer="ABBVIE",
            contract_cost=Decimal("150.00"),
            awp=Decimal("6500.00"),
            asp=Decimal("2800.00"),
            hcpcs_code="J0135",
            bill_units_per_package=2,
            therapeutic_class="TNF Inhibitor",
            is_biologic=True,
            ira_flag=False,
            penny_pricing_flag=False,
        )


def _render_drug_header(drug: Drug) -> None:
    """Render drug header with basic info."""
    col1, col2 = st.columns([2, 1])

    with col1:
        st.header(drug.drug_name)
        st.caption(f"NDC: {drug.ndc_formatted}")
        st.caption(f"Manufacturer: {drug.manufacturer}")

        if drug.therapeutic_class:
            st.caption(f"Class: {drug.therapeutic_class}")

        if drug.hcpcs_code:
            st.caption(f"HCPCS: {drug.hcpcs_code}")
            st.caption(f"Bill Units/Pkg: {drug.bill_units_per_package}")

    with col2:
        st.markdown("**Quick Reference**")

        # Brand/Generic indicator
        drug_type = "Brand" if drug.is_brand else "Generic"
        type_color = "#007bff" if drug.is_brand else "#28a745"
        st.markdown(
            f"<span style='background-color: {type_color}; color: white; "
            f"padding: 2px 8px; border-radius: 4px; font-weight: bold;'>"
            f"{drug_type}</span>",
            unsafe_allow_html=True,
        )
        st.caption(f"AWP Rate: {'85%' if drug.is_brand else '20%'}")

        st.metric("340B Purchase Price", f"${drug.contract_cost:,.2f}")
        st.metric("AWP", f"${drug.awp:,.2f}")

    # Comprehensive Price Reference Section
    st.markdown("---")
    st.markdown("### Price Reference")
    st.warning(
        "**Note:** Unit consistency under review. Prices may be per unit, per package, "
        "or per billing unit depending on source. Verify units before comparing."
    )

    price_col1, price_col2, price_col3, price_col4, price_col5 = st.columns(5)

    with price_col1:
        st.markdown("**340B Purchase Price**")
        st.markdown(f"**${drug.contract_cost:,.2f}**")
        st.caption("Unit Price (Current Catalog)")
        if drug.off_contract:
            st.caption("**OFF-CONTRACT**")
        else:
            st.caption("340B acquisition cost")

    with price_col2:
        st.markdown("**AWP**")
        st.markdown(f"**${drug.awp:,.2f}**")
        st.caption("Average Wholesale Price")
        st.caption("Used for retail margin")

    with price_col3:
        if drug.nadac_price:
            st.markdown("**NADAC**")
            st.markdown(f"**${drug.nadac_price:,.2f}**")
            st.caption("Natl Avg Drug Acquisition Cost")
            st.caption("Market acquisition price")
        else:
            st.markdown("**NADAC**")
            st.markdown("N/A")
            st.caption("Not in NADAC data")

    with price_col4:
        if drug.asp:
            st.markdown("**ASP (True)**")
            st.markdown(f"**${drug.asp:,.2f}**")
            st.caption("Average Sales Price")
            st.caption("Back-calculated from CMS")
        else:
            st.markdown("**ASP**")
            st.markdown("N/A")
            st.caption("No HCPCS mapping")

    with price_col5:
        if drug.asp:
            # Calculate Payment Limit (ASP x 1.06) for display
            payment_limit = drug.asp * Decimal("1.06")
            st.markdown("**Payment Limit**")
            st.markdown(f"**${payment_limit:,.2f}**")
            st.caption("CMS (ASP x 1.06)")
            st.caption("Medicare reimburse basis")
        else:
            st.markdown("**Payment Limit**")
            st.markdown("N/A")
            st.caption("No HCPCS mapping")

    # Package ASP and Medical Spread (when medical path available)
    if drug.has_medical_path() and drug.asp is not None:
        st.markdown("---")
        st.markdown("### Medical Reimbursement Summary")

        package_asp = drug.asp * Decimal("1.06") * drug.bill_units_per_package
        medical_spread = package_asp - drug.contract_cost

        med_col1, med_col2, med_col3 = st.columns(3)

        with med_col1:
            st.markdown("**Package ASP (Medicare)**")
            st.markdown(f"**${package_asp:,.2f}**")
            st.caption(
                f"Payment Limit (${drug.asp * Decimal('1.06'):,.2f}) "
                f"x {drug.bill_units_per_package} bill units"
            )

        with med_col2:
            st.markdown("**340B Purchase Price**")
            st.markdown(f"**${drug.contract_cost:,.2f}**")
            st.caption("Column O - Unit Price (Current Catalog)")

        with med_col3:
            spread_color = "green" if medical_spread > 0 else "red"
            st.markdown("**Medical Spread**")
            st.markdown(
                f"<span style='color: {spread_color}; font-size: 1.2em; font-weight: bold;'>"
                f"${medical_spread:,.2f}</span>",
                unsafe_allow_html=True,
            )
            st.caption("Package ASP - 340B Purchase Price")


def _render_5_margin_cards(
    drug: Drug,
    analysis: MarginAnalysis,
    capture_rate: Decimal,
) -> None:
    """Render 5 margin pathway cards.

    Pathways:
        1. Pharmacy - Medicaid (NADAC-based)
        2. Pharmacy - Medicare/Commercial (AWP-based)
        3. Medical - Medicaid (ASP x 1.04)
        4. Medical - Medicare (ASP x 1.06)
        5. Medical - Commercial (ASP x configurable)
    """
    # Find the best margin for highlighting
    margins = [
        ("pharmacy_medicaid", analysis.pharmacy_medicaid_margin),
        ("pharmacy_medicare_commercial", analysis.pharmacy_medicare_commercial_margin),
        ("medical_medicaid", analysis.medical_medicaid_margin),
        ("medical_medicare", analysis.medical_medicare_margin),
        ("medical_commercial", analysis.medical_commercial_margin),
    ]
    valid_margins = [(name, m) for name, m in margins if m is not None]
    best_pathway = max(valid_margins, key=lambda x: x[1])[0] if valid_margins else None

    # Row 1: Pharmacy pathways
    st.markdown("#### Pharmacy Pathways")
    pharm_col1, pharm_col2 = st.columns(2)

    with pharm_col1:
        is_best = best_pathway == "pharmacy_medicaid"
        _render_margin_card_single(
            title="Pharmacy - Medicaid",
            margin=analysis.pharmacy_medicaid_margin,
            formula="(NADAC + Dispense Fee) x (1 + Markup%) x Capture Rate - 340B Purchase Price",
            is_best=is_best,
            na_reason="No NADAC price available" if drug.nadac_price is None else None,
        )

    with pharm_col2:
        is_best = best_pathway == "pharmacy_medicare_commercial"
        awp_rate = "85%" if drug.is_brand else "20%"
        _render_margin_card_single(
            title="Pharmacy - Medicare/Commercial",
            margin=analysis.pharmacy_medicare_commercial_margin,
            formula=f"AWP x {awp_rate} ({'Brand' if drug.is_brand else 'Generic'}) x Capture Rate - 340B Purchase Price",
            is_best=is_best,
        )

    # Row 2: Medical pathways
    st.markdown("#### Medical Pathways")
    med_col1, med_col2, med_col3 = st.columns(3)

    with med_col1:
        is_best = best_pathway == "medical_medicaid"
        _render_margin_card_single(
            title="Medical - Medicaid",
            margin=analysis.medical_medicaid_margin,
            formula="ASP x 1.04 x Bill Units - 340B Purchase Price",
            is_best=is_best,
            na_reason="No ASP/HCPCS mapping" if not drug.has_medical_path() else None,
        )

    with med_col2:
        is_best = best_pathway == "medical_medicare"
        _render_margin_card_single(
            title="Medical - Medicare",
            margin=analysis.medical_medicare_margin,
            formula="ASP x 1.06 x Bill Units - 340B Purchase Price",
            is_best=is_best,
            na_reason="No ASP/HCPCS mapping" if not drug.has_medical_path() else None,
        )

    with med_col3:
        is_best = best_pathway == "medical_commercial"
        _render_margin_card_single(
            title="Medical - Commercial",
            margin=analysis.medical_commercial_margin,
            formula="ASP x (1 + Markup%) x Bill Units - 340B Purchase Price",
            is_best=is_best,
            na_reason="No ASP/HCPCS mapping" if not drug.has_medical_path() else None,
        )

    # Summary
    if best_pathway and valid_margins:
        best_margin = max(m for _, m in valid_margins)
        pathway_names = {
            "pharmacy_medicaid": "Pharmacy - Medicaid",
            "pharmacy_medicare_commercial": "Pharmacy - Medicare/Commercial",
            "medical_medicaid": "Medical - Medicaid",
            "medical_medicare": "Medical - Medicare",
            "medical_commercial": "Medical - Commercial",
        }
        st.success(
            f"**Recommended:** {pathway_names.get(best_pathway, best_pathway)} "
            f"with margin of **${best_margin:,.2f}**"
        )


def _render_margin_card_single(
    title: str,
    margin: Decimal | None,
    formula: str,
    is_best: bool = False,
    na_reason: str | None = None,
) -> None:
    """Render a single margin card."""
    if margin is not None:
        # Determine color based on margin value
        if margin > 0:
            color = "green" if is_best else "blue"
        else:
            color = "red"

        border = "3px solid #28a745" if is_best else "1px solid #ddd"
        badge = " \u2b50 BEST" if is_best else ""

        st.markdown(
            f"""
            <div style="border: {border}; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;">
                <h5 style="margin: 0;">{title}{badge}</h5>
                <h3 style="color: {color}; margin: 0.5rem 0;">${margin:,.2f}</h3>
                <small style="color: #666;">{formula}</small>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div style="border: 1px solid #ddd; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem; opacity: 0.6;">
                <h5 style="margin: 0;">{title}</h5>
                <h3 style="color: #999; margin: 0.5rem 0;">N/A</h3>
                <small style="color: #999;">{na_reason or "Not available"}</small>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_sensitivity_chart(drug: Drug) -> None:
    """Render capture rate sensitivity chart."""
    sensitivity = calculate_margin_sensitivity(drug)

    if not sensitivity:
        st.info("Sensitivity analysis not available.")
        return

    # Extract data for chart
    capture_rates = [float(s["capture_rate"]) * 100 for s in sensitivity]
    retail_margins = [float(s["retail_net"]) for s in sensitivity]
    medicare_margins = [float(s["medicare"]) for s in sensitivity]
    commercial_margins = [float(s["commercial"]) for s in sensitivity]

    # Create Plotly chart
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=capture_rates,
        y=retail_margins,
        mode="lines+markers",
        name="Retail",
        line={"color": "#1f77b4", "width": 2},
    ))

    if any(m > 0 for m in medicare_margins):
        fig.add_trace(go.Scatter(
            x=capture_rates,
            y=medicare_margins,
            mode="lines+markers",
            name="Medicare",
            line={"color": "#2ca02c", "width": 2},
        ))

    if any(m > 0 for m in commercial_margins):
        fig.add_trace(go.Scatter(
            x=capture_rates,
            y=commercial_margins,
            mode="lines+markers",
            name="Commercial",
            line={"color": "#ff7f0e", "width": 2},
        ))

    fig.update_layout(
        title="Margin by Capture Rate",
        xaxis_title="Capture Rate (%)",
        yaxis_title="Margin ($)",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
        hovermode="x unified",
    )

    st.plotly_chart(fig, width="stretch")

    # Crossover point analysis
    _analyze_crossover_points(sensitivity)


def _analyze_crossover_points(
    sensitivity: list[dict[str, Decimal | str]],
) -> None:
    """Analyze where retail becomes better/worse than medical."""
    for i, s in enumerate(sensitivity):
        retail = float(str(s["retail_net"]))
        commercial = float(str(s["commercial"]))

        if i > 0 and commercial > 0:
            prev = sensitivity[i - 1]
            prev_retail = float(str(prev["retail_net"]))
            prev_commercial = float(str(prev["commercial"]))

            # Check for crossover
            if (prev_retail < prev_commercial) and (retail >= commercial):
                rate = float(str(s["capture_rate"])) * 100
                st.info(
                    f"**Crossover Point:** At {rate:.0f}% capture rate, "
                    "retail becomes more profitable than medical billing."
                )
                return
            elif (prev_retail >= prev_commercial) and (retail < commercial):
                rate = float(str(s["capture_rate"])) * 100
                st.info(
                    f"**Crossover Point:** Below {rate:.0f}% capture rate, "
                    "medical billing becomes more profitable than retail."
                )
                return


def _has_loading_dose(drug: Drug) -> bool:
    """Check if drug has loading dose profile."""
    uploaded = st.session_state.get("uploaded_data", {})
    biologics = uploaded.get("biologics")

    if biologics is None:
        # Check common biologics
        loading_drugs = ["COSENTYX", "STELARA", "SKYRIZI", "TREMFYA"]
        return drug.drug_name.upper() in loading_drugs

    # Check biologics grid
    for row in biologics.iter_rows(named=True):
        if drug.drug_name.upper() in str(row.get("Drug Name", "")).upper():
            return True

    return False


def _render_loading_dose_analysis(drug: Drug, analysis: MarginAnalysis) -> None:
    """Render loading dose impact analysis."""
    uploaded = st.session_state.get("uploaded_data", {})
    biologics = uploaded.get("biologics")

    profile = None
    if biologics is not None:
        profile = apply_loading_dose_logic(drug.drug_name, biologics)

    if profile is None:
        # Use default profile for demo
        if drug.drug_name.upper() == "COSENTYX":
            st.markdown("""
            **Cosentyx Loading Dose Pattern:**
            - Year 1: 17 fills (5 loading doses + 12 monthly)
            - Year 2+: 12 fills (monthly maintenance)
            - Loading dose delta: +42% revenue in Year 1
            """)
        else:
            st.info("Loading dose profile not available for this drug.")
        return

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Year 1 Fills",
            profile.year_1_fills,
            delta=f"+{profile.year_1_fills - profile.year_2_plus_fills} loading",
        )

    with col2:
        st.metric(
            "Maintenance Fills",
            profile.year_2_plus_fills,
            help="Annual fills after Year 1",
        )

    with col3:
        delta_pct = (
            (profile.year_1_fills - profile.year_2_plus_fills)
            / profile.year_2_plus_fills
            * 100
        )
        st.metric(
            "Year 1 Uplift",
            f"+{delta_pct:.0f}%",
            help="Additional revenue from loading doses",
        )


def _render_provenance_chain(
    drug: Drug,
    analysis: MarginAnalysis,
    capture_rate: Decimal = Decimal("1.0"),
    dispense_fee: Decimal = Decimal("0"),
    medicaid_markup_pct: Decimal = Decimal("0"),
    commercial_asp_pct: Decimal = Decimal("0.15"),
) -> None:
    """Render calculation provenance for all 5 pathways."""
    st.markdown(
        "Every calculated margin has a complete audit trail. "
        "Click to expand each calculation."
    )

    # 1. Pharmacy - Medicaid
    with st.expander("1. Pharmacy - Medicaid"):
        if drug.nadac_price is not None:
            base = drug.nadac_price + dispense_fee
            revenue = base * (Decimal("1") + medicaid_markup_pct)
            margin = (revenue * capture_rate) - drug.contract_cost
            st.markdown(f"""
            **Formula:** (NADAC + Dispense Fee) x (1 + Markup%) x Capture Rate - 340B Purchase Price

            **Inputs:**
            - NADAC: ${drug.nadac_price:,.2f}
            - Dispense Fee: ${dispense_fee:,.2f}
            - Markup: {medicaid_markup_pct:.0%}
            - Capture Rate: {capture_rate:.0%}
            - 340B Purchase Price: ${drug.contract_cost:,.2f}

            **Calculation:**
            1. Base = ${drug.nadac_price:,.2f} + ${dispense_fee:,.2f} = ${base:,.2f}
            2. Revenue = ${base:,.2f} x (1 + {medicaid_markup_pct:.0%}) = ${revenue:,.2f}
            3. Adjusted Revenue = ${revenue:,.2f} x {capture_rate:.0%} = ${revenue * capture_rate:,.2f}
            4. Margin = ${revenue * capture_rate:,.2f} - ${drug.contract_cost:,.2f} = ${margin:,.2f}

            **Result:** ${margin:,.2f}
            """)
        else:
            st.warning("NADAC price not available for this drug.")

    # 2. Pharmacy - Medicare/Commercial
    with st.expander("2. Pharmacy - Medicare/Commercial"):
        awp_factor = Decimal("0.85") if drug.is_brand else Decimal("0.20")
        factor_label = "85% (Brand)" if drug.is_brand else "20% (Generic)"
        revenue = drug.awp * awp_factor
        margin = (revenue * capture_rate) - drug.contract_cost
        st.markdown(f"""
        **Formula:** AWP x {factor_label} x Capture Rate - 340B Purchase Price

        **Inputs:**
        - AWP: ${drug.awp:,.2f}
        - AWP Factor: {factor_label}
        - Capture Rate: {capture_rate:.0%}
        - 340B Purchase Price: ${drug.contract_cost:,.2f}

        **Calculation:**
        1. Revenue = ${drug.awp:,.2f} x {awp_factor} = ${revenue:,.2f}
        2. Adjusted Revenue = ${revenue:,.2f} x {capture_rate:.0%} = ${revenue * capture_rate:,.2f}
        3. Margin = ${revenue * capture_rate:,.2f} - ${drug.contract_cost:,.2f} = ${margin:,.2f}

        **Result:** ${margin:,.2f}
        """)

    # 3. Medical - Medicaid
    with st.expander("3. Medical - Medicaid"):
        if drug.has_medical_path() and drug.asp is not None:
            revenue = drug.asp * Decimal("1.04") * drug.bill_units_per_package
            margin = revenue - drug.contract_cost
            st.markdown(f"""
            **Formula:** ASP x 1.04 x Bill Units - 340B Purchase Price

            **Inputs:**
            - ASP: ${drug.asp:,.2f}
            - Multiplier: 1.04 (ASP + 4%)
            - Bill Units per Package: {drug.bill_units_per_package}
            - 340B Purchase Price: ${drug.contract_cost:,.2f}

            **Calculation:**
            1. Revenue = ${drug.asp:,.2f} x 1.04 x {drug.bill_units_per_package} = ${revenue:,.2f}
            2. Margin = ${revenue:,.2f} - ${drug.contract_cost:,.2f} = ${margin:,.2f}

            **Result:** ${margin:,.2f}
            """)
        else:
            st.warning("No ASP/HCPCS mapping available for medical billing.")

    # 4. Medical - Medicare
    with st.expander("4. Medical - Medicare"):
        if drug.has_medical_path() and drug.asp is not None:
            revenue = drug.asp * Decimal("1.06") * drug.bill_units_per_package
            margin = revenue - drug.contract_cost
            st.markdown(f"""
            **Formula:** ASP x 1.06 x Bill Units - 340B Purchase Price

            **Inputs:**
            - ASP: ${drug.asp:,.2f}
            - Multiplier: 1.06 (ASP + 6%)
            - Bill Units per Package: {drug.bill_units_per_package}
            - 340B Purchase Price: ${drug.contract_cost:,.2f}

            **Calculation:**
            1. Revenue = ${drug.asp:,.2f} x 1.06 x {drug.bill_units_per_package} = ${revenue:,.2f}
            2. Margin = ${revenue:,.2f} - ${drug.contract_cost:,.2f} = ${margin:,.2f}

            **Result:** ${margin:,.2f}
            """)
        else:
            st.warning("No ASP/HCPCS mapping available for medical billing.")

    # 5. Medical - Commercial
    with st.expander("5. Medical - Commercial"):
        if drug.has_medical_path() and drug.asp is not None:
            multiplier = Decimal("1") + commercial_asp_pct
            revenue = drug.asp * multiplier * drug.bill_units_per_package
            margin = revenue - drug.contract_cost
            st.markdown(f"""
            **Formula:** ASP x (1 + Markup%) x Bill Units - 340B Purchase Price

            **Inputs:**
            - ASP: ${drug.asp:,.2f}
            - Markup: {commercial_asp_pct:.0%} (Multiplier: {multiplier})
            - Bill Units per Package: {drug.bill_units_per_package}
            - 340B Purchase Price: ${drug.contract_cost:,.2f}

            **Calculation:**
            1. Revenue = ${drug.asp:,.2f} x {multiplier} x {drug.bill_units_per_package} = ${revenue:,.2f}
            2. Margin = ${revenue:,.2f} - ${drug.contract_cost:,.2f} = ${margin:,.2f}

            **Result:** ${margin:,.2f}
            """)
        else:
            st.warning("No ASP/HCPCS mapping available for medical billing.")

    # Recommendation Summary
    with st.expander("Recommendation Logic", expanded=True):
        margins = [
            ("Pharmacy - Medicaid", analysis.pharmacy_medicaid_margin),
            ("Pharmacy - Medicare/Commercial", analysis.pharmacy_medicare_commercial_margin),
            ("Medical - Medicaid", analysis.medical_medicaid_margin),
            ("Medical - Medicare", analysis.medical_medicare_margin),
            ("Medical - Commercial", analysis.medical_commercial_margin),
        ]

        st.markdown("**All Pathway Margins:**")
        for name, margin in margins:
            if margin is not None:
                color = "green" if margin > 0 else "red"
                st.markdown(f"- {name}: <span style='color:{color}'>${margin:,.2f}</span>", unsafe_allow_html=True)
            else:
                st.markdown(f"- {name}: N/A")

        valid_margins = [(name, m) for name, m in margins if m is not None]
        if valid_margins:
            best_name, best_margin = max(valid_margins, key=lambda x: x[1])
            st.markdown(f"""
            **Selection:** Highest margin pathway selected.

            **Recommended:** {best_name} with margin of **${best_margin:,.2f}**
            """)


def _render_manufacturer_risk_assessment(drug: Drug) -> None:
    """Render Manufacturer Risk Assessment section.

    Displays CP restriction alerts, compliance requirements,
    and strategic notes based on manufacturer restriction data.
    """
    cp_info = check_cp_restriction(drug.manufacturer)

    if cp_info is None:
        return

    st.markdown("### Manufacturer Risk Assessment")

    risk_level = cp_info.risk_level

    # --- CP Value Coefficient with color-coded display ---
    coeff = cp_info.cp_value_coefficient
    if coeff >= 1.0:
        coeff_color = "#28a745"  # green
        coeff_label = "No Restrictions"
    elif coeff >= 0.85:
        coeff_color = "#28a745"  # green
        coeff_label = "Full Restoration Available"
    elif coeff >= 0.70:
        coeff_color = "#ffa726"  # orange
        coeff_label = "Partial Restoration"
    elif coeff >= 0.50:
        coeff_color = "#ffa726"  # orange
        coeff_label = "Limited Restoration"
    else:
        coeff_color = "#ff4b4b"  # red
        coeff_label = "No CP Value"

    # Header row with manufacturer, risk level, and coefficient
    h_col1, h_col2, h_col3 = st.columns(3)
    with h_col1:
        st.markdown(f"**Manufacturer:** {cp_info.manufacturer}")
        if cp_info.products_notes:
            st.caption(f"Products: {cp_info.products_notes}")
    with h_col2:
        risk_colors = {"High": "#ff4b4b", "Medium": "#ffa726", "Low": "#28a745", "None": "#28a745"}
        r_color = risk_colors.get(risk_level, "#666")
        st.markdown(
            f"**Risk Level:** <span style='background-color: {r_color}; color: white; "
            f"padding: 2px 8px; border-radius: 4px; font-weight: bold;'>"
            f"{risk_level}</span>",
            unsafe_allow_html=True,
        )
    with h_col3:
        st.markdown(
            f"**CP Value Coefficient:** <span style='color: {coeff_color}; "
            f"font-weight: bold; font-size: 1.2em;'>{coeff:.2f}</span> "
            f"({coeff_label})",
            unsafe_allow_html=True,
        )

    # --- Dynamic Alerts ---

    # 1. Rebate Eligibility Alert
    if cp_info.has_single_cp_restriction:
        st.error(
            f"**Rebate restricted to one designated pharmacy.** "
            f"Restriction type: {cp_info.restriction_type}"
        )

    # 2. Administrative Burden Flag
    if cp_info.requires_data_submission:
        st.warning(
            f"**Manual reporting to independent aggregator (e.g., 340B ESP) "
            f"required for rebate clearance.** "
            f"Method: {cp_info.pricing_restoration_method}"
        )

    # 3. Legislative Impact Tag (reinforce IRA if applicable)
    if drug.ira_flag:
        st.warning(
            "**IRA Impact:** This drug is subject to Inflation Reduction Act "
            "price negotiation, which may further affect 340B pricing."
        )

    # --- Detail columns ---
    detail_col1, detail_col2 = st.columns(2)

    with detail_col1:
        st.markdown("**Restriction Details**")
        st.markdown(f"- **Type:** {cp_info.restriction_type}")
        st.markdown(f"- **EO Rx Limit:** {cp_info.eo_rx_limit}")
        if cp_info.mile_limit and cp_info.mile_limit != "-":
            st.markdown(f"- **Mile Limit:** {cp_info.mile_limit}")
        st.markdown(f"- **FQHC Applies:** {'Yes' if cp_info.fqhc_applies else 'No'}")

    with detail_col2:
        st.markdown("**Compliance & Exemptions**")
        if cp_info.pricing_restoration_method and cp_info.pricing_restoration_method != "nan":
            st.markdown(f"- **Restoration:** {cp_info.pricing_restoration_method}")
        if cp_info.states_exempt and cp_info.states_exempt not in ("-", "nan"):
            st.markdown(f"- **States Exempt:** {cp_info.states_exempt}")
        if cp_info.operational_notes and cp_info.operational_notes != "nan":
            st.markdown(f"- **Notes:** {cp_info.operational_notes}")

    # --- Strategic Recommendation ---
    if risk_level == "High":
        st.info(
            "**Strategic Note:** This drug has significant manufacturer restrictions. "
            "Consider alternative drugs with lower-risk administrative paths for "
            "contract pharmacy dispensing."
        )
