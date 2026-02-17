"""Manufacturer Contract Pharmacy (CP) restriction detection for 340B.

Loads manufacturer CP restriction data and provides lookup by manufacturer name.
Restrictions limit which pharmacies can dispense 340B drugs at discounted pricing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)


@dataclass
class CPRestrictionInfo:
    """Contract pharmacy restriction info for a manufacturer."""

    manufacturer: str
    products_notes: str
    restriction_type: str
    eo_rx_limit: str
    mile_limit: str
    pricing_restoration_method: str
    states_exempt: str
    fqhc_applies: bool
    cp_value_coefficient: float
    operational_notes: str

    @property
    def risk_level(self) -> str:
        """Classify risk based on CP Value Coefficient.

        Returns:
            'High', 'Medium', 'Low', or 'None'.
        """
        if self.cp_value_coefficient >= 1.0:
            return "None"
        if self.cp_value_coefficient >= 0.85:
            return "Low"
        if self.cp_value_coefficient >= 0.70:
            return "Medium"
        return "High"

    @property
    def has_single_cp_restriction(self) -> bool:
        """Whether manufacturer restricts to a single contract pharmacy."""
        return "1 CP" in self.restriction_type

    @property
    def requires_data_submission(self) -> bool:
        """Whether pricing restoration requires data submission."""
        method = self.pricing_restoration_method.upper()
        return "CP DATA" in method or "340B ESP" in method or "ATTESTATION" in method


# Module-level restriction lookup (populated on load)
CP_RESTRICTIONS: dict[str, CPRestrictionInfo] = {}


def _get_default_cp_path() -> Path | None:
    """Find the CP restrictions file in standard locations."""
    candidates = [
        Path(__file__).parent.parent.parent.parent / "data" / "sample" / "Mfr_CP_Restrictions_Lookup_FQHC.xlsx",
        Path("data") / "sample" / "Mfr_CP_Restrictions_Lookup_FQHC.xlsx",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def load_cp_restrictions(df: pl.DataFrame) -> dict[str, CPRestrictionInfo]:
    """Load CP restrictions from a DataFrame into lookup dict.

    Args:
        df: DataFrame from the 'Mfr CP Restrictions' sheet.

    Returns:
        Dictionary keyed by uppercase manufacturer name.
    """
    restrictions: dict[str, CPRestrictionInfo] = {}

    for row in df.iter_rows(named=True):
        manufacturer = str(row.get("Manufacturer", "")).strip()
        if not manufacturer:
            continue

        fqhc_raw = str(row.get("FQHC Applies", "")).strip().upper()
        fqhc_applies = fqhc_raw in ("YES", "Y", "TRUE")

        coeff_raw = row.get("CP Value Coefficient", 0)
        try:
            coefficient = float(coeff_raw) if coeff_raw is not None else 0.0
        except (ValueError, TypeError):
            coefficient = 0.0

        info = CPRestrictionInfo(
            manufacturer=manufacturer,
            products_notes=str(row.get("Products/Notes", "") or ""),
            restriction_type=str(row.get("CP Restriction Type", "") or ""),
            eo_rx_limit=str(row.get("EO Rx Limit", "") or ""),
            mile_limit=str(row.get("Mile Limit", "") or ""),
            pricing_restoration_method=str(row.get("Pricing Restoration Method", "") or ""),
            states_exempt=str(row.get("States Exempt", "") or ""),
            fqhc_applies=fqhc_applies,
            cp_value_coefficient=coefficient,
            operational_notes=str(row.get("Operational Notes", "") or ""),
        )

        restrictions[manufacturer.upper()] = info

    logger.info(f"Loaded CP restrictions for {len(restrictions)} manufacturers")
    return restrictions


def reload_cp_restrictions(df: pl.DataFrame | None = None) -> None:
    """Reload CP restrictions into the module-level lookup.

    Args:
        df: DataFrame to load from. If None, attempts to load from file.
    """
    global CP_RESTRICTIONS

    if df is not None:
        CP_RESTRICTIONS = load_cp_restrictions(df)
        return

    # Try loading from file
    path = _get_default_cp_path()
    if path is not None:
        try:
            from optimizer_340b.ingest.loaders import load_excel_to_polars

            file_df = load_excel_to_polars(str(path), sheet_name="Mfr CP Restrictions")
            CP_RESTRICTIONS = load_cp_restrictions(file_df)
        except Exception as e:
            logger.warning(f"Could not load CP restrictions from file: {e}")
    else:
        logger.debug("No CP restrictions file found")


def check_cp_restriction(manufacturer_name: str) -> CPRestrictionInfo | None:
    """Look up CP restriction for a manufacturer using fuzzy matching.

    Checks if any restriction key is a substring of the catalog manufacturer name.
    E.g., restriction key "ABBVIE" matches catalog "ABBVIE US LLC SPD".

    Args:
        manufacturer_name: Manufacturer name from the product catalog.

    Returns:
        CPRestrictionInfo if matched, None otherwise.
    """
    if not manufacturer_name or not CP_RESTRICTIONS:
        return None

    name_upper = manufacturer_name.upper().strip()

    # Try exact match first
    if name_upper in CP_RESTRICTIONS:
        return CP_RESTRICTIONS[name_upper]

    # Fuzzy match: check if any restriction key is contained in the catalog name
    for key, info in CP_RESTRICTIONS.items():
        if key in name_upper:
            return info

    return None
