"""Dashboard page for 340B Optimizer - Ranked opportunity list."""

import logging
from decimal import Decimal

import polars as pl
import streamlit as st

from optimizer_340b.compute.margins import analyze_drug_margin
from optimizer_340b.compute.retail_pricing import (
    DrugCategory,
    classify_drug_category,
    load_drug_category_lookup,
)
from optimizer_340b.ingest.normalizers import normalize_ndc
from optimizer_340b.models import Drug, MarginAnalysis
from optimizer_340b.risk import check_ira_status
from optimizer_340b.risk.penny_pricing import (
    INFLATION_PENALTY_THRESHOLD,
    PENNY_COST_OVERRIDE,
    build_nadac_lookup,
)
from optimizer_340b.risk.retail_validation import (
    build_retail_validation_lookup,
    load_wholesaler_catalog,
)
from optimizer_340b.ui.components.drug_search import render_drug_search

logger = logging.getLogger(__name__)


def render_dashboard_page() -> None:
    """Render the main optimization dashboard.

    Shows ranked list of optimization opportunities with:
    - Margin comparison (Retail vs Medical)
    - Risk flags (IRA, Penny Pricing)
    - Capture rate adjustment
    - Search and filter capabilities
    """
    st.title("340B Optimization Dashboard")

    # Check if data is loaded
    if not _check_data_loaded():
        st.warning(
            "Please upload data files first. "
            "Select **Upload Data** from the sidebar."
        )
        return

    # Main content
    _render_summary_metrics()

    st.markdown("---")

    # Controls in main panel
    st.markdown("### Filters")

    # Default capture rate to 100% (feature temporarily disabled)
    capture_rate = Decimal("1.0")

    ctrl_col1, ctrl_col2 = st.columns(2)

    with ctrl_col1:
        show_ira_only = st.checkbox("Show IRA drugs only", value=False)
        hide_penny = st.checkbox("Hide penny pricing drugs", value=False)

    with ctrl_col2:
        min_delta = st.number_input(
            "Min margin delta ($)",
            min_value=0,
            max_value=10000,
            value=0,
            step=50,
        )

    st.markdown("---")

    # Enhanced search with HCPCS support
    st.markdown("### Search")
    search_result = render_drug_search(key_prefix="dashboard")

    # Parse search result for filtering
    # - "name:query" = filter by drug name (partial match)
    # - "hcpcs:code" = filter by HCPCS code
    # - NDC string = filter by NDC
    search_query = ""
    if search_result:
        if search_result.startswith("name:"):
            search_query = search_result[5:]  # Drug name search
        elif search_result.startswith("hcpcs:"):
            search_query = search_result[6:]  # HCPCS code search
        else:
            search_query = search_result  # NDC search

    # Get and display opportunities
    opportunities = _calculate_opportunities(capture_rate)

    # Apply filters with context
    filtered, filter_context = _apply_filters_with_context(
        opportunities,
        search_query=search_query,
        show_ira_only=show_ira_only,
        hide_penny=hide_penny,
        min_delta=Decimal(str(min_delta)),
    )

    # Show filter context
    _render_filter_summary(filtered, filter_context, search_query)

    # Render opportunity table
    _render_opportunity_table(filtered)


def _check_data_loaded() -> bool:
    """Check if required data is loaded in session state."""
    uploaded = st.session_state.get("uploaded_data", {})
    return "catalog" in uploaded


def _render_summary_metrics() -> None:
    """Render summary metrics at top of dashboard."""
    uploaded = st.session_state.get("uploaded_data", {})

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        catalog = uploaded.get("catalog")
        drug_count = catalog.height if catalog is not None else 0
        st.metric("Total Drugs", f"{drug_count:,}")

    with col2:
        crosswalk = uploaded.get("crosswalk")
        hcpcs_count = crosswalk.height if crosswalk is not None else 0
        st.metric("HCPCS Mappings", f"{hcpcs_count:,}")

    with col3:
        # Calculate medical-eligible drugs
        joined = uploaded.get("joined_data")
        if joined is not None:
            medical_eligible = joined.filter(pl.col("HCPCS Code").is_not_null()).height
        else:
            medical_eligible = 0
        st.metric("Medical Eligible", f"{medical_eligible:,}")

    with col4:
        nadac = uploaded.get("nadac")
        if nadac is not None:
            penny_count = nadac.filter(
                pl.col("total_discount_340b_pct") >= 95.0
            ).height
        else:
            penny_count = 0
        st.metric("Penny Pricing", f"{penny_count:,}")


def _calculate_opportunities(capture_rate: Decimal) -> list[MarginAnalysis]:
    """Calculate margin opportunities for all drugs.

    Args:
        capture_rate: Retail capture rate.

    Returns:
        List of MarginAnalysis objects sorted by margin delta.
    """
    uploaded = st.session_state.get("uploaded_data", {})
    catalog = uploaded.get("catalog")
    asp_pricing = uploaded.get("asp_pricing")
    crosswalk = uploaded.get("crosswalk")
    nadac = uploaded.get("nadac")
    noc_pricing = uploaded.get("noc_pricing")
    noc_crosswalk = uploaded.get("noc_crosswalk")
    ravenswood_categories = uploaded.get("ravenswood_categories")

    if catalog is None:
        return []

    # Build drug objects and analyze margins
    analyses: list[MarginAnalysis] = []

    # Prepare lookup tables
    hcpcs_lookup = _build_hcpcs_lookup(crosswalk, asp_pricing)
    noc_lookup = _build_noc_lookup(noc_crosswalk, noc_pricing)

    # Build enhanced NADAC lookup with penny cost override and inflation
    if nadac is not None:
        nadac_enhanced = build_nadac_lookup(nadac)
    else:
        nadac_enhanced = {}

    # Build drug category lookup from Ravenswood (if available)
    if ravenswood_categories is not None:
        category_lookup = load_drug_category_lookup(ravenswood_categories)
    else:
        category_lookup = {}

    for row in catalog.iter_rows(named=True):
        try:
            drug = _row_to_drug(
                row, hcpcs_lookup, nadac_enhanced, noc_lookup, category_lookup
            )
            if drug is not None:
                analysis = analyze_drug_margin(drug, capture_rate)
                analyses.append(analysis)
        except Exception as e:
            logger.debug(f"Error analyzing drug: {e}")
            continue

    # Sort by margin delta descending
    analyses.sort(key=lambda a: a.margin_delta, reverse=True)

    return analyses


def _build_hcpcs_lookup(
    crosswalk: pl.DataFrame | None,
    asp_pricing: pl.DataFrame | None,
) -> dict[str, dict[str, object]]:
    """Build HCPCS lookup from crosswalk and ASP pricing.

    Returns:
        Dictionary mapping normalized NDC to HCPCS info.
    """
    if crosswalk is None or asp_pricing is None:
        return {}

    lookup: dict[str, dict[str, object]] = {}

    # Normalize column names for crosswalk
    ndc_col = "NDC" if "NDC" in crosswalk.columns else "NDC2"
    hcpcs_col = (
        "HCPCS Code" if "HCPCS Code" in crosswalk.columns else "_2025_CODE"
    )

    if ndc_col not in crosswalk.columns or hcpcs_col not in crosswalk.columns:
        return {}

    # Build ASP pricing lookup by HCPCS
    # IMPORTANT: CMS Payment Limit already includes 6% markup (Payment Limit = ASP x 1.06)
    # We must back-calculate the true ASP for correct margin calculations
    PAYMENT_LIMIT_MARKUP = 1.06
    asp_lookup: dict[str, float] = {}
    payment_col = (
        "Payment Limit"
        if "Payment Limit" in asp_pricing.columns
        else "PAYMENT_LIMIT"
    )

    if payment_col in asp_pricing.columns and "HCPCS Code" in asp_pricing.columns:
        for row in asp_pricing.iter_rows(named=True):
            hcpcs = row.get("HCPCS Code")
            payment = row.get(payment_col)
            if hcpcs and payment:
                # Handle N/A and other non-numeric values
                try:
                    payment_limit = float(payment)
                    # Back-calculate true ASP from Payment Limit
                    true_asp = payment_limit / PAYMENT_LIMIT_MARKUP
                    asp_lookup[str(hcpcs).upper()] = true_asp
                except (ValueError, TypeError):
                    continue  # Skip non-numeric payment values

    # Build combined lookup
    for row in crosswalk.iter_rows(named=True):
        ndc = str(row.get(ndc_col, "")).replace("-", "").strip()
        hcpcs = str(row.get(hcpcs_col, "")).upper().strip()

        if ndc and hcpcs:
            asp = asp_lookup.get(hcpcs)
            bill_units = row.get("Billing Units Per Package", 1) or 1

            lookup[ndc] = {
                "hcpcs_code": hcpcs,
                "asp": asp,
                "bill_units": int(bill_units),
            }

    return lookup


def _build_noc_lookup(
    noc_crosswalk: pl.DataFrame | None,
    noc_pricing: pl.DataFrame | None,
) -> dict[str, dict[str, object]]:
    """Build NOC lookup for drugs without permanent J-codes.

    NOC (Not Otherwise Classified) provides fallback pricing for new drugs
    that don't yet have a permanent HCPCS code.

    Returns:
        Dictionary mapping normalized NDC to NOC pricing info.
    """
    if noc_crosswalk is None or noc_pricing is None:
        return {}

    lookup: dict[str, dict[str, object]] = {}

    # Build pricing lookup by generic drug name
    # IMPORTANT: CMS Payment Limit already includes 6% markup (Payment Limit = ASP x 1.06)
    # We must back-calculate the true ASP for correct margin calculations
    PAYMENT_LIMIT_MARKUP = 1.06
    pricing_lookup: dict[str, float] = {}
    if "Drug Generic Name" in noc_pricing.columns and "Payment Limit" in noc_pricing.columns:
        for row in noc_pricing.iter_rows(named=True):
            drug_name = row.get("Drug Generic Name")
            payment = row.get("Payment Limit")
            if drug_name and payment:
                try:
                    # Normalize name for matching
                    # Back-calculate true ASP from Payment Limit
                    payment_limit = float(payment)
                    true_asp = payment_limit / PAYMENT_LIMIT_MARKUP
                    pricing_lookup[str(drug_name).upper().strip()] = true_asp
                except (ValueError, TypeError):
                    continue

    # Build NDC lookup from crosswalk
    ndc_col = "NDC" if "NDC" in noc_crosswalk.columns else "NDC or ALTERNATE ID"
    generic_col = "Drug Generic Name"
    bill_units_col = "Bill Units Per Pkg" if "Bill Units Per Pkg" in noc_crosswalk.columns else "BILLUNITSPKG"

    if ndc_col not in noc_crosswalk.columns or generic_col not in noc_crosswalk.columns:
        return {}

    for row in noc_crosswalk.iter_rows(named=True):
        ndc = str(row.get(ndc_col, "")).replace("-", "").strip()
        generic_name = str(row.get(generic_col, "")).upper().strip()

        if ndc and generic_name:
            # Look up payment from pricing file
            asp = pricing_lookup.get(generic_name)
            bill_units = row.get(bill_units_col, 1) or 1

            if asp is not None:
                lookup[ndc] = {
                    "generic_name": generic_name,
                    "asp": asp,
                    "bill_units": int(bill_units) if bill_units else 1,
                    "is_noc": True,
                }

    return lookup


def _row_to_drug(
    row: dict[str, object],
    hcpcs_lookup: dict[str, dict[str, object]],
    nadac_lookup: dict[str, dict[str, object]],
    noc_lookup: dict[str, dict[str, object]] | None = None,
    category_lookup: dict[str, DrugCategory] | None = None,
) -> Drug | None:
    """Convert a catalog row to a Drug object.

    Args:
        row: Row from catalog DataFrame.
        hcpcs_lookup: HCPCS/ASP lookup by NDC.
        nadac_lookup: Enhanced NADAC lookup with penny override and inflation.
        noc_lookup: NOC fallback lookup by NDC (for drugs without J-codes).
        category_lookup: Drug category lookup from Ravenswood matrix.

    Returns:
        Drug object or None if invalid.
    """
    # Get NDC
    ndc = str(row.get("NDC", ""))
    if not ndc:
        return None

    ndc_normalized = ndc.replace("-", "").strip().zfill(11)[-11:]

    # Get drug name (handle different column names)
    drug_name = (
        row.get("Drug Name")
        or row.get("Trade Name")
        or row.get("DRUG_NAME")
        or "Unknown"
    )

    # Get manufacturer
    manufacturer = row.get("Manufacturer") or row.get("MANUFACTURER") or "Unknown"

    # Get contract cost (340B acquisition cost from Unit Price Current Catalog)
    contract_cost = (
        row.get("Unit Price (Current Catalog)")
        or row.get("Contract Cost")
        or row.get("CONTRACT_COST")
        or 0
    )
    try:
        contract_cost = Decimal(str(contract_cost))
    except Exception:
        return None

    # Get AWP (handle different column names)
    awp = row.get("AWP") or row.get("Medispan AWP") or row.get("MEDISPAN_AWP") or 0
    try:
        awp = Decimal(str(awp))
    except Exception:
        return None

    # Lookup HCPCS/ASP info (primary source)
    hcpcs_info = hcpcs_lookup.get(ndc_normalized, {})
    asp = hcpcs_info.get("asp")
    hcpcs_code = hcpcs_info.get("hcpcs_code")
    bill_units = hcpcs_info.get("bill_units", 1)

    # NOC fallback: if not in ASP crosswalk, check NOC crosswalk
    if asp is None and noc_lookup:
        noc_info = noc_lookup.get(ndc_normalized, {})
        if noc_info:
            asp = noc_info.get("asp")
            bill_units = noc_info.get("bill_units", 1)
            # NOC drugs use generic codes, mark as NOC for display
            hcpcs_code = "NOC"  # Indicates Not Otherwise Classified

    # Lookup NADAC info (enhanced with penny override and inflation)
    nadac_info = nadac_lookup.get(ndc_normalized, {})
    penny_pricing = nadac_info.get("is_penny_priced", False)

    # Apply penny cost override per manifest:
    # "If penny_pricing == 'Yes', override Cost_Basis to $0.01"
    if penny_pricing and nadac_info.get("override_cost"):
        contract_cost = nadac_info["override_cost"]
        logger.debug(f"Applied penny cost override for NDC {ndc}: ${contract_cost}")

    # Check for high inflation penalty (>20%)
    inflation_penalty = nadac_info.get("inflation_penalty_pct")
    has_inflation_flag = nadac_info.get("has_inflation_penalty", False)

    # Get NADAC price (most recent)
    nadac_price = nadac_info.get("nadac_price")

    # Check IRA status
    ira_status = check_ira_status(str(drug_name))
    ira_flag = ira_status.get("is_ira_drug", False)

    # Classify drug category (for retail pricing multiplier)
    drug_category = classify_drug_category(str(drug_name), category_lookup)
    # Brand/Specialty use 85% AWP, Generic uses 20% AWP
    is_brand = drug_category != DrugCategory.GENERIC

    return Drug(
        ndc=ndc,
        drug_name=str(drug_name),
        manufacturer=str(manufacturer),
        contract_cost=contract_cost,
        awp=awp,
        asp=Decimal(str(asp)) if asp else None,
        hcpcs_code=str(hcpcs_code) if hcpcs_code else None,
        bill_units_per_package=int(str(bill_units)) if bill_units else 1,
        is_brand=is_brand,
        ira_flag=bool(ira_flag),
        penny_pricing_flag=bool(penny_pricing),
        nadac_price=nadac_price,
    )


def _apply_filters(
    analyses: list[MarginAnalysis],
    search_query: str = "",
    show_ira_only: bool = False,
    hide_penny: bool = True,
    min_delta: Decimal = Decimal("0"),
) -> list[MarginAnalysis]:
    """Apply filters to opportunity list.

    Args:
        analyses: List of MarginAnalysis objects.
        search_query: Drug name, NDC, or HCPCS code search.
        show_ira_only: Show only IRA-affected drugs.
        hide_penny: Hide penny-priced drugs.
        min_delta: Minimum margin delta.

    Returns:
        Filtered list of analyses.
    """
    filtered = analyses

    # Search filter - supports drug name, NDC (11-digit or 5-4-2 format), or HCPCS code
    if search_query:
        query = search_query.upper()
        query_ndc = normalize_ndc(search_query)  # Normalize for NDC matching
        filtered = [
            a for a in filtered
            if query in a.drug.drug_name.upper()
            or query_ndc in a.drug.ndc
            or query in a.drug.ndc  # Also check raw query for partial matches
            or (a.drug.hcpcs_code and query == a.drug.hcpcs_code.upper())  # HCPCS match
        ]

    # IRA filter
    if show_ira_only:
        filtered = [a for a in filtered if a.drug.ira_flag]

    # Penny pricing filter
    if hide_penny:
        filtered = [a for a in filtered if not a.drug.penny_pricing_flag]

    # Margin delta filter
    filtered = [a for a in filtered if a.margin_delta >= min_delta]

    return filtered


def _apply_filters_with_context(
    analyses: list[MarginAnalysis],
    search_query: str = "",
    show_ira_only: bool = False,
    hide_penny: bool = True,
    min_delta: Decimal = Decimal("0"),
) -> tuple[list[MarginAnalysis], dict[str, int]]:
    """Apply filters and return context about what was filtered.

    Returns:
        Tuple of (filtered list, context dict with counts).
    """
    context: dict[str, int] = {
        "total": len(analyses),
        "search_matches": 0,
        "hidden_by_ira": 0,
        "hidden_by_penny": 0,
        "hidden_by_delta": 0,
    }

    filtered = analyses

    # Search filter - supports drug name, NDC (11-digit or 5-4-2 format), or HCPCS code
    if search_query:
        query = search_query.upper()
        query_ndc = normalize_ndc(search_query)  # Normalize for NDC matching
        search_results = [
            a for a in filtered
            if query in a.drug.drug_name.upper()
            or query_ndc in a.drug.ndc
            or query in a.drug.ndc  # Also check raw query for partial matches
            or (a.drug.hcpcs_code and query == a.drug.hcpcs_code.upper())  # HCPCS match
        ]
        context["search_matches"] = len(search_results)
        filtered = search_results
    else:
        context["search_matches"] = len(filtered)

    # IRA filter
    if show_ira_only:
        before_ira = len(filtered)
        filtered = [a for a in filtered if a.drug.ira_flag]
        context["hidden_by_ira"] = before_ira - len(filtered)

    # Penny pricing filter
    if hide_penny:
        before_penny = len(filtered)
        filtered = [a for a in filtered if not a.drug.penny_pricing_flag]
        context["hidden_by_penny"] = before_penny - len(filtered)

    # Margin delta filter
    before_delta = len(filtered)
    filtered = [a for a in filtered if a.margin_delta >= min_delta]
    context["hidden_by_delta"] = before_delta - len(filtered)

    return filtered, context


def _render_filter_summary(
    filtered: list[MarginAnalysis],
    context: dict[str, int],
    search_query: str,
) -> None:
    """Render summary of filtering results."""
    if search_query:
        # Show search-specific context
        matches = context["search_matches"]
        shown = len(filtered)
        hidden = matches - shown

        if hidden > 0:
            st.markdown(
                f"**Showing {shown} of {matches} drugs matching '{search_query}'** "
                f"({hidden} hidden by filters)"
            )
            # Show breakdown of what's hidden
            details = []
            if context["hidden_by_penny"] > 0:
                details.append(f"{context['hidden_by_penny']} penny-priced")
            if context["hidden_by_delta"] > 0:
                details.append(f"{context['hidden_by_delta']} below min delta")
            if context["hidden_by_ira"] > 0:
                details.append(f"{context['hidden_by_ira']} non-IRA")
            if details:
                st.caption(f"Hidden: {', '.join(details)}")
        else:
            st.markdown(
                f"**Showing {shown} drug{'s' if shown != 1 else ''} "
                f"matching '{search_query}'**"
            )
    else:
        # No search - show total context
        st.markdown(f"**Showing {len(filtered)} of {context['total']} drugs**")


def _render_opportunity_table(analyses: list[MarginAnalysis]) -> None:
    """Render the opportunity table with clickable rows."""
    if not analyses:
        st.info("No opportunities match the current filters.")
        return

    # Prepare data for display
    table_data = []

    for analysis in analyses[:100]:  # Limit to top 100 for performance
        drug = analysis.drug

        # Build risk flags as plain text (HTML doesn't render in dataframes)
        flags = []
        if drug.ira_flag:
            flags.append("\u26a0\ufe0f IRA")
        if drug.penny_pricing_flag:
            flags.append("\U0001f4b0 Penny")
        risk_text = " | ".join(flags) if flags else ""

        # Determine best margin
        best_margin = analysis.retail_net_margin
        if analysis.commercial_margin and analysis.commercial_margin > best_margin:
            best_margin = analysis.commercial_margin
        if analysis.medicare_margin and analysis.medicare_margin > best_margin:
            best_margin = analysis.medicare_margin

        table_data.append({
            "Drug": drug.drug_name,
            "NDC": drug.ndc_formatted,
            "Best Margin": f"${best_margin:,.2f}",
            "Retail": f"${analysis.retail_net_margin:,.2f}",
            "Medicare": (
                f"${analysis.medicare_margin:,.2f}"
                if analysis.medicare_margin else "N/A"
            ),
            "Commercial": (
                f"${analysis.commercial_margin:,.2f}"
                if analysis.commercial_margin else "N/A"
            ),
            "Recommendation": analysis.recommended_path.value.replace("_", " "),
            "Delta": f"${analysis.margin_delta:,.2f}",
            "Risk": risk_text,
        })

    # Create DataFrame
    df = pl.DataFrame(table_data)

    # Display with st.dataframe for performance
    st.dataframe(
        df.to_pandas(),
        width="stretch",
        hide_index=True,
        column_config={
            "Risk": st.column_config.Column(
                "Risk Flags",
                help="IRA and Penny Pricing alerts",
            ),
        },
    )

    # Drug detail links
    st.markdown("---")
    st.markdown("**View Drug Details** - Select drug, then go to Drug Detail page")

    cols = st.columns(5)
    for i, analysis in enumerate(analyses[:5]):
        with cols[i]:
            if st.button(analysis.drug.drug_name, key=f"detail_{i}"):
                st.session_state.selected_drug = analysis.drug.ndc
                st.info(f"Selected {analysis.drug.drug_name}. Go to Drug Detail.")
