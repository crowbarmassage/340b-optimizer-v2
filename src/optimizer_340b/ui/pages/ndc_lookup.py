"""NDC Lookup page for batch margin analysis.

Upload a CSV with drug names and NDC codes, validate matches against
product catalog, and output pharmacy channel margins.
"""

import io
import logging
from decimal import Decimal, InvalidOperation

import pandas as pd
import polars as pl
import streamlit as st

logger = logging.getLogger(__name__)

# AWP multipliers by drug type
AWP_MULTIPLIERS = {
    "BRAND": Decimal("0.85"),
    "SPECIALTY": Decimal("0.85"),
    "GENERIC": Decimal("0.20"),
}


def render_ndc_lookup_page() -> None:
    """Render the NDC Lookup page for batch margin analysis."""
    st.title("NDC Lookup & Margin Calculator")
    st.markdown(
        """
        Upload a CSV with drug names and NDC codes to:
        - Validate drug name matches against the product catalog
        - Calculate pharmacy channel margins (Medicaid & Medicare/Commercial)
        - Download results with match status and margins
        """
    )

    # Check if catalog is loaded
    uploaded = st.session_state.get("uploaded_data", {})
    catalog = uploaded.get("catalog")
    nadac = uploaded.get("nadac")

    if catalog is None:
        st.warning(
            "Please upload the Product Catalog first. "
            "Go to **Upload Data** in the sidebar."
        )
        return

    # Show data status
    col1, col2 = st.columns(2)
    with col1:
        st.info(f"Product Catalog: {catalog.height:,} drugs loaded")
    with col2:
        if nadac is not None:
            st.info(f"NADAC Pricing: {nadac.height:,} prices loaded")
        else:
            st.warning("NADAC not loaded - Medicaid margins will be N/A")

    st.markdown("---")

    # Configurable parameters in expander
    st.markdown("### Margin Analysis Parameters")
    with st.expander("Adjust Analysis Parameters", expanded=False):
        param_col1, param_col2, param_col3 = st.columns(3)

        with param_col1:
            dispense_fee = st.number_input(
                "Dispense Fee ($)",
                min_value=0.0,
                max_value=100.0,
                value=0.0,
                step=0.50,
                help="Medicaid pharmacy dispense fee added to NADAC",
                key="ndc_dispense_fee",
            )
            medicaid_markup = st.number_input(
                "Medicaid Markup (%)",
                min_value=0.0,
                max_value=50.0,
                value=0.0,
                step=1.0,
                help="Additional Medicaid pharmacy markup percentage",
                key="ndc_medicaid_markup",
            )

        with param_col2:
            awp_discount = st.number_input(
                "AWP Discount (%)",
                min_value=0.0,
                max_value=50.0,
                value=15.0,
                step=1.0,
                help="AWP discount for Medicare/Commercial (default 15% = AWP x 0.85)",
                key="ndc_awp_discount",
            )

        with param_col3:
            capture_rate_pct = st.number_input(
                "Capture Rate (%)",
                min_value=0.0,
                max_value=100.0,
                value=100.0,
                step=5.0,
                help="Pharmacy channel capture rate",
                key="ndc_capture_rate",
            )

    # Convert to Decimals for calculations
    dispense_fee_dec = Decimal(str(dispense_fee))
    medicaid_markup_dec = Decimal(str(medicaid_markup)) / Decimal("100")
    awp_discount_dec = Decimal(str(awp_discount)) / Decimal("100")
    capture_rate_dec = Decimal(str(capture_rate_pct)) / Decimal("100")

    st.markdown("---")

    # File format instructions
    with st.expander("CSV Format Requirements", expanded=False):
        st.markdown(
            """
            **Required columns (in order):**
            1. `Drug Description` - Your drug name/description
            2. `NDC11` - NDC code (will be left-padded to 11 digits)
            3. `Type` - BRAND, SPECIALTY, or GENERIC
            4. `Product Description` - Expected catalog description (optional)
            5. `HCPCS` - HCPCS/J-code (optional)

            **Example:**
            ```
            Drug Description,NDC11,Type,Product Description,HCPCS
            HUMIRA PEN 40 MG/0.8ML,74433902,SPECIALTY,HUMIRA PEN KT 40MG/0.8ML 2,J0135
            ELIQUIS 5 MG TABLET,3089421,BRAND,ELIQUIS TB 5MG 60,
            ```
            """
        )

    # File upload
    uploaded_file = st.file_uploader(
        "Upload NDC List (CSV)",
        type=["csv"],
        help="CSV with Drug Description, NDC11, Type, Product Description columns",
    )

    if uploaded_file is not None:
        try:
            # Read the uploaded CSV
            input_df = _parse_input_csv(uploaded_file)

            if input_df is None or len(input_df) == 0:
                st.error("Could not parse CSV. Please check the format.")
                return

            st.success(f"Loaded {len(input_df)} rows from CSV")

            # Show preview
            with st.expander("Preview Input Data", expanded=True):
                st.dataframe(input_df.head(10), use_container_width=True)

            # Process button
            if st.button("Calculate Margins", type="primary"):
                with st.spinner("Processing NDC lookups..."):
                    results_df = _process_ndc_lookup(
                        input_df,
                        catalog,
                        nadac,
                        dispense_fee=dispense_fee_dec,
                        medicaid_markup=medicaid_markup_dec,
                        awp_discount=awp_discount_dec,
                        capture_rate=capture_rate_dec,
                    )

                if results_df is not None and len(results_df) > 0:
                    st.markdown("---")
                    st.markdown("### Results")

                    # Summary metrics
                    _render_summary_metrics(results_df)

                    # Results table
                    st.dataframe(results_df, use_container_width=True)

                    # Download button
                    csv_buffer = io.StringIO()
                    results_df.to_csv(csv_buffer, index=False)
                    csv_data = csv_buffer.getvalue()

                    st.download_button(
                        label="Download Results CSV",
                        data=csv_data,
                        file_name="ndc_margin_results.csv",
                        mime="text/csv",
                    )

        except Exception as e:
            logger.exception("Error processing NDC lookup")
            st.error(f"Error processing file: {e}")


def _parse_input_csv(uploaded_file) -> pd.DataFrame | None:
    """Parse the uploaded CSV file.

    Expected columns: Drug Description, NDC11, Type, Product Description, HCPCS (optional)

    Args:
        uploaded_file: Streamlit uploaded file object.

    Returns:
        DataFrame with standardized columns, or None if parsing fails.
    """
    try:
        # Try reading with different options
        content = uploaded_file.getvalue().decode("utf-8")

        # Check if it has headers
        first_line = content.split("\n")[0].strip().upper()

        # Common header keywords that indicate row is a header
        header_keywords = [
            "DRUG", "DESC", "NDC", "TYPE", "PRODUCT", "MED_DESC", "NAME", "HCPCS"
        ]

        # Standard column names (5 columns)
        standard_cols = ["Drug Description", "NDC11", "Type", "Product Description", "HCPCS"]

        # If no comma in first line, try tab-separated
        if "," not in first_line:
            df = pd.read_csv(
                io.StringIO(content),
                sep="\t",
                header=None,
                names=standard_cols[:4],
            )
        elif any(kw in first_line for kw in header_keywords):
            # Has headers - read with header row
            df = pd.read_csv(io.StringIO(content))
        else:
            # No headers, assign column names based on number of columns
            df = pd.read_csv(io.StringIO(content), header=None)
            df.columns = standard_cols[: len(df.columns)]

        # Standardize column names if they don't match expected
        if len(df.columns) >= 4 and "Drug Description" not in df.columns:
            df.columns = standard_cols[: len(df.columns)]

        # Ensure we have at least the required columns
        if len(df.columns) < 2:
            logger.error("CSV must have at least Drug Description and NDC11 columns")
            return None

        # Add missing columns if needed
        if "Type" not in df.columns:
            df["Type"] = "BRAND"
        if "Product Description" not in df.columns:
            df["Product Description"] = ""
        if "HCPCS" not in df.columns:
            df["HCPCS"] = ""

        return df

    except Exception as e:
        logger.exception(f"Error parsing CSV: {e}")
        return None


def _normalize_ndc(ndc: str | int | float) -> str:
    """Normalize NDC to 11 digits with left-padding.

    Args:
        ndc: NDC value (may be numeric or string).

    Returns:
        11-digit NDC string with leading zeros.
    """
    if pd.isna(ndc):
        return ""

    # Convert to string and clean
    ndc_str = str(ndc).strip()

    # Remove any non-numeric characters
    ndc_clean = "".join(c for c in ndc_str if c.isdigit())

    # Left-pad to 11 digits
    return ndc_clean.zfill(11)


def _names_match(str1: str, str2: str) -> bool:
    """Check if two drug names match (case-insensitive).

    Args:
        str1: First drug name.
        str2: Second drug name.

    Returns:
        True if names match (case-insensitive).
    """
    if not str1 or not str2:
        return False

    # Normalize strings: uppercase and strip whitespace
    s1 = str1.upper().strip()
    s2 = str2.upper().strip()

    return s1 == s2


def _extract_first_word(description: str) -> str:
    """Extract the first word (trade name) from drug description.

    Args:
        description: Full drug description.

    Returns:
        First word (trade name) in uppercase.
    """
    if not description:
        return ""

    # Get the first word - this is the trade name
    desc_upper = description.upper().strip()

    # Split on whitespace and take first word
    words = desc_upper.split()
    if words:
        return words[0]

    return ""


def _determine_match_status(
    input_name: str,
    catalog_name: str | None,
    generic_name: str | None,
    ndc_found: bool,
) -> tuple[str, bool]:
    """Determine match status based on drug name comparison.

    Checks input name against both Product Description and Generic Name.

    Args:
        input_name: User's drug name.
        catalog_name: Catalog Product Description (None if NDC not found).
        generic_name: Catalog Generic Name (None if not available).
        ndc_found: Whether NDC was found in catalog.

    Returns:
        Tuple of (status_string, is_match).
    """
    if not ndc_found:
        return "NDC NOT FOUND", False

    if not catalog_name and not generic_name:
        return "NO CATALOG NAME", False

    # Extract first word (trade name) for comparison
    input_trade = _extract_first_word(input_name)

    # Check against Product Description
    if catalog_name:
        catalog_trade = _extract_first_word(catalog_name)
        if _names_match(input_trade, catalog_trade):
            return "MATCH", True

    # Check against Generic Name
    if generic_name:
        generic_trade = _extract_first_word(generic_name)
        if _names_match(input_trade, generic_trade):
            return "MATCH (GENERIC)", True

    return "MISMATCH - VERIFY", False


def _process_ndc_lookup(
    input_df: pd.DataFrame,
    catalog: pl.DataFrame,
    nadac: pl.DataFrame | None = None,
    dispense_fee: Decimal = Decimal("0"),
    medicaid_markup: Decimal = Decimal("0"),
    awp_discount: Decimal = Decimal("0.15"),
    capture_rate: Decimal = Decimal("1"),
) -> pd.DataFrame:
    """Process NDC lookup and calculate margins.

    Args:
        input_df: Input DataFrame with drug list.
        catalog: Product catalog DataFrame.
        nadac: Optional NADAC pricing DataFrame.
        dispense_fee: Dispense fee to add to NADAC (default $0).
        medicaid_markup: Medicaid markup percentage as decimal (default 0).
        awp_discount: AWP discount percentage as decimal (default 0.15 = 15%).
        capture_rate: Capture rate as decimal (default 1.0 = 100%).

    Returns:
        Results DataFrame with match status and margins.
    """
    # Build catalog lookup by NDC
    catalog_lookup = _build_catalog_lookup(catalog)

    # Build NADAC lookup if available
    nadac_lookup = _build_nadac_lookup(nadac) if nadac is not None else {}

    results = []

    for _, row in input_df.iterrows():
        input_name = str(row.get("Drug Description", "")).strip()
        raw_ndc = row.get("NDC11", "")
        drug_type = str(row.get("Type", "BRAND")).upper().strip()
        expected_desc = str(row.get("Product Description", "")).strip()
        hcpcs = str(row.get("HCPCS", "")).strip() if pd.notna(row.get("HCPCS")) else ""

        # Skip header-like rows (NDC contains no digits or is a column name)
        raw_ndc_str = str(raw_ndc).upper().strip()
        if not any(c.isdigit() for c in raw_ndc_str) or raw_ndc_str in (
            "NDC", "NDC11", "NDC_CODE", "NDC CODE"
        ):
            logger.debug(f"Skipping header-like row: {raw_ndc_str}")
            continue

        # Normalize NDC
        ndc11 = _normalize_ndc(raw_ndc)

        # Look up in catalog
        catalog_data = catalog_lookup.get(ndc11)

        # Look up NADAC price
        nadac_price = nadac_lookup.get(ndc11)

        if catalog_data:
            catalog_name = catalog_data.get("drug_name", "")
            generic_name = catalog_data.get("generic_name", "")
            contract_cost = catalog_data.get("contract_cost")
            awp = catalog_data.get("awp")
            package_size = catalog_data.get("package_size", Decimal("1"))

            # Determine match status (checks both Product Description and Generic Name)
            match_status, is_match = _determine_match_status(
                input_name, catalog_name, generic_name, True
            )

            # Calculate margins if we have pricing
            # Note: NADAC is per-unit, so multiply by package_size for per-package comparison
            medicaid_margin, medicare_commercial_margin = _calculate_pharmacy_margins(
                contract_cost=contract_cost,
                awp=awp,
                nadac_price=nadac_price,
                drug_type=drug_type,
                package_size=package_size,
                dispense_fee=dispense_fee,
                medicaid_markup=medicaid_markup,
                awp_discount=awp_discount,
                capture_rate=capture_rate,
            )
        else:
            catalog_name = ""
            contract_cost = None
            awp = None
            match_status, is_match = _determine_match_status(
                input_name, None, None, False
            )
            medicaid_margin = None
            medicare_commercial_margin = None

        # Floor negative/N/A Medicaid margins to $0.00 only if Medicare/Commercial is available
        if medicare_commercial_margin is not None:
            medicaid_display = _format_currency_floor_zero(medicaid_margin)
        else:
            medicaid_display = _format_currency(medicaid_margin)

        results.append({
            "Input Drug Name": input_name,
            "NDC11": ndc11,
            "HCPCS": hcpcs,
            "Match Status": match_status,
            "Catalog Description": catalog_name,
            "Type": drug_type,
            "Contract Cost": _format_currency(contract_cost),
            "AWP": _format_currency(awp),
            "Pharmacy Medicaid Margin": medicaid_display,
            "Pharmacy Medicare/Commercial Margin": _format_currency(
                medicare_commercial_margin
            ),
        })

    return pd.DataFrame(results)


def _find_column(columns: list[str], *candidates: str) -> str | None:
    """Find a column name from a list of candidates (case-insensitive).

    Args:
        columns: List of available column names.
        candidates: Possible column names to search for.

    Returns:
        Matching column name or None.
    """
    columns_upper = {c.upper(): c for c in columns}
    for candidate in candidates:
        if candidate.upper() in columns_upper:
            return columns_upper[candidate.upper()]
    return None


def _build_catalog_lookup(catalog: pl.DataFrame) -> dict[str, dict]:
    """Build lookup dictionary from catalog by NDC.

    Args:
        catalog: Product catalog DataFrame.

    Returns:
        Dictionary mapping NDC11 to catalog data.
    """
    lookup = {}

    # Find column names (case-insensitive)
    ndc_col = _find_column(catalog.columns, "NDC", "NDC11", "NDC Code")
    name_col = _find_column(catalog.columns, "Product Description", "Description", "Drug Name")
    generic_col = _find_column(catalog.columns, "Generic Name", "GenericName", "Generic")
    cost_col = _find_column(catalog.columns, "Contract Cost", "ContractCost", "Cost")
    awp_col = _find_column(catalog.columns, "Medispan AWP", "AWP", "MedispanAWP", "Medispan_AWP")
    pkg_size_col = _find_column(catalog.columns, "Package Size", "PackageSize", "Pkg Size", "Size")

    if not ndc_col:
        logger.error(f"NDC column not found in catalog. Available: {catalog.columns}")
        return lookup

    logger.info(f"Using columns: NDC={ndc_col}, Name={name_col}, Generic={generic_col}, Cost={cost_col}, AWP={awp_col}, PkgSize={pkg_size_col}")

    for row in catalog.iter_rows(named=True):
        raw_ndc = row.get(ndc_col, "")
        ndc11 = _normalize_ndc(raw_ndc)

        if not ndc11:
            continue

        # Get values
        drug_name = str(row.get(name_col, "")) if name_col else ""
        generic_name = str(row.get(generic_col, "")) if generic_col else ""
        contract_cost = row.get(cost_col) if cost_col else None
        awp = row.get(awp_col) if awp_col else None
        package_size = row.get(pkg_size_col) if pkg_size_col else None

        # Convert to Decimal if numeric
        if contract_cost is not None:
            try:
                contract_cost = Decimal(str(contract_cost))
            except (ValueError, TypeError, InvalidOperation):
                contract_cost = None

        if awp is not None:
            try:
                awp = Decimal(str(awp))
            except (ValueError, TypeError, InvalidOperation):
                awp = None

        if package_size is not None:
            try:
                package_size = Decimal(str(package_size))
                if package_size <= 0:
                    package_size = Decimal("1")
            except (ValueError, TypeError, InvalidOperation):
                package_size = Decimal("1")
        else:
            package_size = Decimal("1")

        # Store first occurrence (or best price)
        if ndc11 not in lookup:
            lookup[ndc11] = {
                "drug_name": drug_name,
                "generic_name": generic_name,
                "contract_cost": contract_cost,
                "awp": awp,
                "package_size": package_size,
            }
        else:
            # Keep the one with lower contract cost (best 340B price)
            existing_cost = lookup[ndc11].get("contract_cost")
            if (
                contract_cost is not None
                and (existing_cost is None or contract_cost < existing_cost)
            ):
                lookup[ndc11] = {
                    "drug_name": drug_name,
                    "generic_name": generic_name,
                    "contract_cost": contract_cost,
                    "awp": awp,
                    "package_size": package_size,
                }

    logger.info(f"Built catalog lookup with {len(lookup)} unique NDCs")
    return lookup


def _build_nadac_lookup(nadac: pl.DataFrame) -> dict[str, Decimal]:
    """Build NADAC price lookup by NDC.

    Args:
        nadac: NADAC pricing DataFrame.

    Returns:
        Dictionary mapping NDC11 to NADAC price.
    """
    lookup = {}

    logger.info(f"NADAC columns available: {nadac.columns}")

    # Find column names - try many variations
    ndc_col = _find_column(
        nadac.columns,
        "ndc", "NDC", "NDC11", "ndc11", "NDC_Code", "ndc_code",
        "NDC Description", "ndc_description"
    )
    # Use last_price as the current NADAC price (most recent)
    price_col = _find_column(
        nadac.columns,
        "last_price", "Last Price", "last_nadac",
        "NADAC_Per_Unit", "nadac_per_unit", "NADAC Per Unit",
        "NADAC", "nadac", "nadac_price", "Price", "price",
        "mean_price", "median_price"
    )

    if not ndc_col or not price_col:
        logger.warning(f"NADAC columns not found. NDC col: {ndc_col}, Price col: {price_col}")
        logger.warning(f"Available columns: {nadac.columns}")
        return lookup

    logger.info(f"Using NADAC columns: NDC={ndc_col}, Price={price_col}")

    for row in nadac.iter_rows(named=True):
        raw_ndc = row.get(ndc_col, "")
        ndc11 = _normalize_ndc(raw_ndc)

        if not ndc11:
            continue

        price = row.get(price_col)
        if price is not None:
            try:
                lookup[ndc11] = Decimal(str(price))
            except (ValueError, TypeError, InvalidOperation):
                continue

    logger.info(f"Built NADAC lookup with {len(lookup)} NDCs")
    return lookup


def _calculate_pharmacy_margins(
    contract_cost: Decimal | None,
    awp: Decimal | None,
    nadac_price: Decimal | None,
    drug_type: str,
    package_size: Decimal = Decimal("1"),
    dispense_fee: Decimal = Decimal("0"),
    medicaid_markup: Decimal = Decimal("0"),
    awp_discount: Decimal = Decimal("0.15"),
    capture_rate: Decimal = Decimal("1"),
) -> tuple[Decimal | None, Decimal | None]:
    """Calculate pharmacy channel margins.

    Pharmacy Medicaid: ((NADAC x Pkg Size) + Dispense Fee) x (1 + Markup%) x Capture Rate - Contract Cost
    Pharmacy Medicare/Commercial: AWP x (1 - Discount%) x Capture Rate - Contract Cost

    Note: NADAC is per-unit price, Contract Cost is per-package.
    We multiply NADAC by package_size to get per-package NADAC.

    Args:
        contract_cost: 340B acquisition cost (per package).
        awp: Average Wholesale Price (per package).
        nadac_price: NADAC price per unit.
        drug_type: BRAND, SPECIALTY, or GENERIC.
        package_size: Number of units per package (default 1).
        dispense_fee: Dispense fee to add (default $0).
        medicaid_markup: Medicaid markup as decimal (default 0).
        awp_discount: AWP discount as decimal (default 0.15 = 15%).
        capture_rate: Capture rate as decimal (default 1.0 = 100%).

    Returns:
        Tuple of (medicaid_margin, medicare_commercial_margin).
    """
    # Pharmacy Medicaid: ((NADAC x Pkg Size) + Dispense Fee) x (1 + Markup%) x Capture Rate - Contract Cost
    if contract_cost is not None and nadac_price is not None:
        nadac_per_package = nadac_price * package_size
        base = nadac_per_package + dispense_fee
        revenue = base * (Decimal("1") + medicaid_markup)
        medicaid_margin = (revenue * capture_rate) - contract_cost
    else:
        medicaid_margin = None

    # Pharmacy Medicare/Commercial: AWP x (1 - Discount%) x Capture Rate - Contract Cost
    if contract_cost is not None and awp is not None:
        # Apply AWP discount (e.g., 15% discount = multiply by 0.85)
        awp_multiplier = Decimal("1") - awp_discount
        revenue = awp * awp_multiplier
        medicare_commercial_margin = (revenue * capture_rate) - contract_cost
    else:
        medicare_commercial_margin = None

    return medicaid_margin, medicare_commercial_margin


def _format_currency(value: Decimal | None) -> str:
    """Format value as currency string.

    Args:
        value: Decimal value or None.

    Returns:
        Formatted string like "$1,234.56" or "N/A".
    """
    if value is None:
        return "N/A"

    try:
        return f"${float(value):,.2f}"
    except (ValueError, TypeError):
        return "N/A"


def _format_currency_floor_zero(value: Decimal | None) -> str:
    """Format value as currency, flooring negative/None to $0.00.

    Args:
        value: Decimal value or None.

    Returns:
        Formatted string like "$1,234.56" or "$0.00" if negative/None.
    """
    if value is None or value < 0:
        return "$0.00"

    try:
        return f"${float(value):,.2f}"
    except (ValueError, TypeError):
        return "$0.00"


def _render_summary_metrics(results_df: pd.DataFrame) -> None:
    """Render summary metrics for the results.

    Args:
        results_df: Results DataFrame.
    """
    col1, col2, col3, col4 = st.columns(4)

    total = len(results_df)

    with col1:
        st.metric("Total Drugs", total)

    with col2:
        matches = len(results_df[results_df["Match Status"] == "MATCH"])
        st.metric("Matches", matches)

    with col3:
        mismatches = len(
            results_df[results_df["Match Status"].str.contains("MISMATCH|NOT FOUND")]
        )
        st.metric("Mismatches", mismatches)

    with col4:
        has_margin = len(
            results_df[results_df["Pharmacy Medicare/Commercial Margin"] != "N/A"]
        )
        st.metric("With Margins", has_margin)
