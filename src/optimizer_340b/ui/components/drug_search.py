"""Enhanced drug search component with autofill and HCPCS support.

Supports:
- Drug name search with autocomplete
- NDC11 search
- HCPCS code search with NDC selection (one-to-many)
- Enter key submission via form
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import polars as pl
import streamlit as st

from optimizer_340b.ingest.normalizers import normalize_ndc

logger = logging.getLogger(__name__)

# Path to NDC-HCPCS mapping file
MAPPING_FILE = Path(__file__).parent.parent.parent.parent.parent / "data" / "sample" / "ndc_hcpcs_mapping.csv"


def _load_hcpcs_to_ndc_mapping() -> dict[str, list[dict[str, str]]]:
    """Load HCPCS to NDC mapping from CSV file.

    Returns:
        Dictionary mapping HCPCS code to list of {ndc11, drug_name, manufacturer}.
    """
    if "hcpcs_to_ndc_map" in st.session_state:
        return st.session_state.hcpcs_to_ndc_map

    mapping: dict[str, list[dict[str, str]]] = {}

    if MAPPING_FILE.exists():
        try:
            df = pl.read_csv(str(MAPPING_FILE))
            for row in df.iter_rows(named=True):
                hcpcs = str(row.get("hcpcs_code", "")).upper().strip()
                ndc = str(row.get("ndc11", "")).strip()
                drug_name = str(row.get("drug_name", "")).strip()
                manufacturer = str(row.get("manufacturer", "")).strip()

                if hcpcs and ndc:
                    if hcpcs not in mapping:
                        mapping[hcpcs] = []
                    mapping[hcpcs].append({
                        "ndc11": ndc,
                        "drug_name": drug_name,
                        "manufacturer": manufacturer,
                    })
            logger.info(f"Loaded HCPCS mapping: {len(mapping)} codes")
        except Exception as e:
            logger.warning(f"Could not load HCPCS mapping: {e}")

    st.session_state.hcpcs_to_ndc_map = mapping
    return mapping


def _get_drug_name_options() -> list[str]:
    """Get list of unique drug names from catalog for autocomplete.

    Returns:
        Sorted list of unique drug names.
    """
    if "drug_name_options" in st.session_state:
        return st.session_state.drug_name_options

    uploaded = st.session_state.get("uploaded_data", {})
    catalog = uploaded.get("catalog")

    if catalog is None:
        return []

    names = set()
    for row in catalog.iter_rows(named=True):
        name = str(row.get("Drug Name") or row.get("Trade Name") or "").strip()
        if name and name.lower() != "unknown":
            names.add(name)

    sorted_names = sorted(names)
    st.session_state.drug_name_options = sorted_names
    return sorted_names


def _detect_query_type(query: str) -> str:
    """Detect if query is an NDC, HCPCS code, or drug name.

    Args:
        query: Search query string.

    Returns:
        One of: "ndc", "hcpcs", "name"
    """
    query = query.strip()

    if not query:
        return "name"

    # Check for HCPCS pattern: J-code, Q-code, etc. (letter + 4 digits)
    # Examples: J0135, Q5101, J9999
    hcpcs_pattern = r"^[A-Za-z][0-9]{4}$"
    if re.match(hcpcs_pattern, query):
        return "hcpcs"

    # Check for NDC pattern: 11 digits or 5-4-2 with dashes
    # Examples: 00074433902, 00074-4339-02
    ndc_clean = query.replace("-", "").replace(" ", "")
    if ndc_clean.isdigit() and len(ndc_clean) >= 10:
        return "ndc"

    # Default to drug name search
    return "name"


def _format_ndc_for_display(ndc: str) -> str:
    """Format 11-digit NDC as 5-4-2 for display.

    Args:
        ndc: 11-digit NDC string.

    Returns:
        Formatted NDC as XXXXX-XXXX-XX.
    """
    ndc = ndc.zfill(11)[-11:]  # Ensure 11 digits
    return f"{ndc[:5]}-{ndc[5:9]}-{ndc[9:]}"


def _search_drugs_by_name(query: str) -> list[dict[str, str]]:
    """Search catalog for drugs matching the query name.

    Args:
        query: Drug name search query (partial match).

    Returns:
        List of matching drugs with {ndc, drug_name, manufacturer, strength}.
    """
    uploaded = st.session_state.get("uploaded_data", {})
    catalog = uploaded.get("catalog")

    if catalog is None:
        return []

    query_upper = query.upper().strip()
    matches: list[dict[str, str]] = []

    for row in catalog.iter_rows(named=True):
        drug_name = str(row.get("Drug Name") or row.get("Trade Name") or "").strip()
        if query_upper in drug_name.upper():
            ndc = str(row.get("NDC", "")).strip()
            manufacturer = str(row.get("Manufacturer") or row.get("MANUFACTURER") or "").strip()
            # Get strength/description for differentiation
            strength = str(row.get("Strength") or row.get("Description") or "").strip()

            matches.append({
                "ndc": ndc,
                "drug_name": drug_name,
                "manufacturer": manufacturer,
                "strength": strength,
            })

    return matches


def render_drug_search(
    key_prefix: str = "search",
    on_select_callback: callable = None,
) -> str | None:
    """Render enhanced drug search with autocomplete and HCPCS support.

    Args:
        key_prefix: Unique prefix for session state keys.
        on_select_callback: Optional callback when drug is selected.

    Returns:
        Selected NDC string or None if no selection.
    """
    # Load lookups
    hcpcs_map = _load_hcpcs_to_ndc_mapping()
    drug_names = _get_drug_name_options()

    # Initialize state keys
    state_key = f"{key_prefix}_selected_ndc"
    hcpcs_results_key = f"{key_prefix}_hcpcs_results"
    name_results_key = f"{key_prefix}_name_results"

    # Return stored selection if available (persists after rerun)
    stored_ndc = st.session_state.get(state_key)

    # Show current filter if active
    if stored_ndc:
        col1, col2 = st.columns([4, 1])
        with col1:
            st.success(f"Filtering by NDC: **{_format_ndc_for_display(stored_ndc)}**")
        with col2:
            if st.button("Clear Filter", key=f"{key_prefix}_clear", type="secondary"):
                del st.session_state[state_key]
                st.rerun()

    # Search form with Enter key support
    with st.form(key=f"{key_prefix}_form", clear_on_submit=False):
        col1, col2 = st.columns([4, 1])

        with col1:
            search_query = st.text_input(
                "Search by Drug Name, NDC, or HCPCS Code",
                placeholder="Enter drug name, 11-digit NDC, or HCPCS code (e.g., J0135)...",
                key=f"{key_prefix}_query",
                help="Drug name: partial match | NDC: 11 digits or 5-4-2 format | HCPCS: J-code like J0135",
            )

        with col2:
            st.markdown("&nbsp;")  # Spacer for alignment
            submitted = st.form_submit_button("Search", type="primary", use_container_width=True)

    # Process search on submit
    if submitted and search_query:
        query_type = _detect_query_type(search_query)

        if query_type == "hcpcs":
            # HCPCS search - show list of matching NDCs
            hcpcs_code = search_query.upper().strip()
            matches = hcpcs_map.get(hcpcs_code, [])

            if matches:
                st.session_state[hcpcs_results_key] = {
                    "hcpcs": hcpcs_code,
                    "matches": matches,
                }
                # Rerun to show the selection list immediately
                st.rerun()
            else:
                st.warning(f"No NDCs found for HCPCS code **{hcpcs_code}**.")
                if hcpcs_results_key in st.session_state:
                    del st.session_state[hcpcs_results_key]
            return None

        elif query_type == "ndc":
            # NDC search - store and rerun to persist the selection
            normalized = normalize_ndc(search_query)
            st.session_state[state_key] = normalized
            if hcpcs_results_key in st.session_state:
                del st.session_state[hcpcs_results_key]
            if name_results_key in st.session_state:
                del st.session_state[name_results_key]
            st.rerun()

        else:
            # Drug name search - find all matching drugs
            matches = _search_drugs_by_name(search_query)

            # Clear previous results
            if hcpcs_results_key in st.session_state:
                del st.session_state[hcpcs_results_key]
            if name_results_key in st.session_state:
                del st.session_state[name_results_key]

            if not matches:
                st.warning(f"No drugs found matching **{search_query}**.")
                return None
            elif len(matches) == 1:
                # Single match - store and rerun to persist the selection
                st.session_state[state_key] = matches[0]["ndc"]
                st.rerun()
            else:
                # Multiple matches - show selection list
                st.session_state[name_results_key] = {
                    "query": search_query,
                    "matches": matches,
                }
                st.rerun()

    # Show HCPCS results if available
    if hcpcs_results_key in st.session_state:
        results = st.session_state[hcpcs_results_key]
        hcpcs_code = results["hcpcs"]
        matches = results["matches"]

        st.info(f"Found **{len(matches)}** NDC(s) for HCPCS **{hcpcs_code}**. Select one below or browse the filtered table:")

        # Create display options
        options = [
            f"{m['drug_name']} | {_format_ndc_for_display(m['ndc11'])} | {m['manufacturer']}"
            for m in matches
        ]

        selected_idx = st.selectbox(
            "Available NDCs",
            range(len(options)),
            format_func=lambda i: options[i],
            key=f"{key_prefix}_hcpcs_select",
            label_visibility="collapsed",
        )

        if st.button("Select This Drug", key=f"{key_prefix}_hcpcs_confirm", type="primary"):
            selected_ndc = matches[selected_idx]["ndc11"]
            st.session_state[state_key] = selected_ndc
            del st.session_state[hcpcs_results_key]
            # Rerun to update the page with the selection
            st.rerun()

        # Return HCPCS code so table filters by it while browsing options
        return f"hcpcs:{hcpcs_code}"

    # Show drug name search results if multiple matches
    if name_results_key in st.session_state:
        results = st.session_state[name_results_key]
        query = results["query"]
        matches = results["matches"]

        st.info(f"Found **{len(matches)}** drugs matching **{query}**. Select one below or browse the filtered table:")

        # Create display options with strength/description for differentiation
        options = []
        for m in matches:
            ndc_display = _format_ndc_for_display(m["ndc"])
            if m["strength"]:
                options.append(f"{m['drug_name']} | {m['strength']} | {ndc_display} | {m['manufacturer']}")
            else:
                options.append(f"{m['drug_name']} | {ndc_display} | {m['manufacturer']}")

        selected_idx = st.selectbox(
            "Available drugs",
            range(len(options)),
            format_func=lambda i: options[i],
            key=f"{key_prefix}_name_select",
            label_visibility="collapsed",
        )

        if st.button("Select This Drug", key=f"{key_prefix}_name_confirm", type="primary"):
            selected_ndc = matches[selected_idx]["ndc"]
            st.session_state[state_key] = selected_ndc
            del st.session_state[name_results_key]
            # Rerun to update the page with the selection
            st.rerun()

        # Return the search query so table filters by drug name while browsing options
        return f"name:{query}"

    # Return stored NDC if available (after rerun from selection)
    return stored_ndc


def render_drug_autocomplete(
    key_prefix: str = "autocomplete",
    label: str = "Select Drug",
) -> str | None:
    """Render drug name autocomplete selectbox.

    Args:
        key_prefix: Unique prefix for session state keys.
        label: Label for the selectbox.

    Returns:
        Selected drug name or None.
    """
    drug_names = _get_drug_name_options()

    if not drug_names:
        st.info("Load data to enable drug autocomplete.")
        return None

    # Add empty option at start
    options = [""] + drug_names

    selected = st.selectbox(
        label,
        options=options,
        key=f"{key_prefix}_autocomplete",
        placeholder="Start typing to search...",
    )

    return selected if selected else None
