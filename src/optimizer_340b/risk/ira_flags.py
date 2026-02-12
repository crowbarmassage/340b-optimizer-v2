"""IRA (Inflation Reduction Act) risk flagging for 340B drugs.

The Inflation Reduction Act allows Medicare to negotiate prices for certain
high-spend drugs. Drugs subject to IRA negotiation may see significant
price reductions, impacting 340B margins.

Gatekeeper Test: Enbrel Simulation
- Force-feed Enbrel into the pipeline
- System should flag it with "High Risk / IRA 2026" warning

IRA Drug Selection Timeline:
- 2026: First 10 drugs (announced August 2023)
- 2027: 15 additional drugs
- 2028+: Up to 20 drugs per year

Data Source:
- Primary: data/sample/ira_drug_list.csv (loaded at runtime)
- Fallback: hardcoded values below (used if CSV not found)
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)

# Hardcoded fallback values - used only if CSV file is not available
# These are kept for backwards compatibility and as a safety net
_FALLBACK_IRA_2026_DRUGS = {
    "ELIQUIS": "Blood thinner (apixaban)",
    "JARDIANCE": "Diabetes (empagliflozin)",
    "XARELTO": "Blood thinner (rivaroxaban)",
    "JANUVIA": "Diabetes (sitagliptin)",
    "FARXIGA": "Diabetes/Heart failure (dapagliflozin)",
    "ENTRESTO": "Heart failure (sacubitril/valsartan)",
    "ENBREL": "Autoimmune (etanercept)",
    "IMBRUVICA": "Cancer (ibrutinib)",
    "STELARA": "Autoimmune (ustekinumab)",
    "FIASP": "Insulin (insulin aspart)",
    "FIASP FLEXTOUCH": "Insulin (insulin aspart)",
    "FIASP PENFILL": "Insulin (insulin aspart)",
    "NOVOLOG": "Insulin (insulin aspart)",
    "NOVOLOG FLEXPEN": "Insulin (insulin aspart)",
    "NOVOLOG MIX": "Insulin (insulin aspart)",
}

_FALLBACK_IRA_2027_DRUGS = {
    "OZEMPIC": "Diabetes/Weight loss (semaglutide)",
    "RYBELSUS": "Diabetes (oral semaglutide)",
    "WEGOVY": "Weight loss (semaglutide)",
    "TRELEGY ELLIPTA": "COPD (fluticasone/umeclidinium/vilanterol)",
    "TRULICITY": "Diabetes (dulaglutide)",
    "POMALYST": "Cancer (pomalidomide)",
    "AUSTEDO": "Movement disorders (deutetrabenazine)",
    "IBRANCE": "Cancer (palbociclib)",
    "OTEZLA": "Autoimmune (apremilast)",
    "COSENTYX": "Autoimmune (secukinumab)",
    "TALZENNA": "Cancer (talazoparib)",
    "AUBAGIO": "Multiple sclerosis (teriflunomide)",
    "OMVOH": "Ulcerative colitis (mirikizumab)",
    "XTANDI": "Cancer (enzalutamide)",
    "SIVEXTRO": "Antibiotic (tedizolid)",
}


def _get_default_ira_csv_path() -> Path:
    """Get the default path to the IRA drug list CSV file."""
    # Try multiple potential locations
    base_path = Path(__file__).parent.parent.parent.parent
    potential_paths = [
        base_path / "data" / "sample" / "ira_drug_list.csv",
        Path.cwd() / "data" / "sample" / "ira_drug_list.csv",
    ]
    for path in potential_paths:
        if path.exists():
            return path
    return potential_paths[0]  # Return first path even if doesn't exist


def load_ira_drugs_from_csv(
    csv_path: Path | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Load IRA drugs from CSV file.

    Args:
        csv_path: Path to the IRA drug list CSV file.
            If None, uses default location.

    Returns:
        Tuple of (ira_2026_drugs, ira_2027_drugs) dictionaries
        mapping drug names to descriptions.
    """
    if csv_path is None:
        csv_path = _get_default_ira_csv_path()

    if not csv_path.exists():
        logger.warning(
            f"IRA CSV file not found at {csv_path}, using fallback hardcoded values"
        )
        return _FALLBACK_IRA_2026_DRUGS.copy(), _FALLBACK_IRA_2027_DRUGS.copy()

    try:
        df = pl.read_csv(csv_path)
        logger.info(f"Loaded IRA drug list from {csv_path}: {df.height} drugs")

        ira_2026: dict[str, str] = {}
        ira_2027: dict[str, str] = {}

        for row in df.iter_rows(named=True):
            drug_name = str(row.get("drug_name", "")).upper().strip()
            year = int(row.get("ira_year", 0))
            description = str(row.get("description", ""))

            if not drug_name:
                continue

            if year == 2026:
                ira_2026[drug_name] = description
            elif year == 2027:
                ira_2027[drug_name] = description
            else:
                logger.warning(f"Unknown IRA year {year} for drug {drug_name}")

        logger.info(
            f"Loaded {len(ira_2026)} IRA 2026 drugs and {len(ira_2027)} IRA 2027 drugs"
        )
        return ira_2026, ira_2027

    except Exception as e:
        logger.error(f"Error loading IRA CSV from {csv_path}: {e}")
        logger.warning("Using fallback hardcoded IRA values")
        return _FALLBACK_IRA_2026_DRUGS.copy(), _FALLBACK_IRA_2027_DRUGS.copy()


def load_ira_drugs_from_dataframe(
    df: pl.DataFrame,
) -> tuple[dict[str, str], dict[str, str]]:
    """Load IRA drugs from a Polars DataFrame (e.g., from uploaded file).

    Args:
        df: DataFrame with columns: drug_name, ira_year, description

    Returns:
        Tuple of (ira_2026_drugs, ira_2027_drugs) dictionaries.
    """
    ira_2026: dict[str, str] = {}
    ira_2027: dict[str, str] = {}

    for row in df.iter_rows(named=True):
        drug_name = str(row.get("drug_name", "")).upper().strip()
        year = int(row.get("ira_year", 0))
        description = str(row.get("description", ""))

        if not drug_name:
            continue

        if year == 2026:
            ira_2026[drug_name] = description
        elif year == 2027:
            ira_2027[drug_name] = description

    logger.info(
        f"Loaded {len(ira_2026)} IRA 2026 drugs and "
        f"{len(ira_2027)} IRA 2027 drugs from DataFrame"
    )
    return ira_2026, ira_2027


# Load IRA drugs at module initialization
# These will be used by check_ira_status() and other functions
IRA_2026_DRUGS, IRA_2027_DRUGS = load_ira_drugs_from_csv()

# Combined lookup for all IRA drugs
IRA_DRUGS_BY_YEAR: dict[str, int] = {}
for drug in IRA_2026_DRUGS:
    IRA_DRUGS_BY_YEAR[drug.upper()] = 2026
for drug in IRA_2027_DRUGS:
    IRA_DRUGS_BY_YEAR[drug.upper()] = 2027


def reload_ira_drugs(
    csv_path: Path | None = None, df: pl.DataFrame | None = None
) -> None:
    """Reload IRA drugs from CSV or DataFrame, updating module-level variables.

    This function allows updating the IRA drug lists at runtime, for example
    when a user uploads a new IRA drug list file.

    Args:
        csv_path: Path to CSV file. If provided, loads from file.
        df: DataFrame to load from. If provided, takes precedence over csv_path.
    """
    global IRA_2026_DRUGS, IRA_2027_DRUGS, IRA_DRUGS_BY_YEAR

    if df is not None:
        IRA_2026_DRUGS, IRA_2027_DRUGS = load_ira_drugs_from_dataframe(df)
    else:
        IRA_2026_DRUGS, IRA_2027_DRUGS = load_ira_drugs_from_csv(csv_path)

    # Rebuild the combined lookup
    IRA_DRUGS_BY_YEAR = {}
    for drug in IRA_2026_DRUGS:
        IRA_DRUGS_BY_YEAR[drug.upper()] = 2026
    for drug in IRA_2027_DRUGS:
        IRA_DRUGS_BY_YEAR[drug.upper()] = 2027

    logger.info(f"Reloaded IRA drugs: {len(IRA_DRUGS_BY_YEAR)} total drugs")


@dataclass
class IRARiskStatus:
    """IRA risk assessment for a drug.

    Attributes:
        is_ira_drug: Whether the drug is subject to IRA negotiation.
        ira_year: Year when IRA pricing takes effect (2026, 2027, etc.).
        drug_name: Matched drug name from IRA list.
        description: Drug description/category.
        warning_message: Human-readable risk warning.
        risk_level: "High Risk", "Moderate Risk", or "Low Risk".
    """

    is_ira_drug: bool
    ira_year: int | None
    drug_name: str | None
    description: str | None
    warning_message: str
    risk_level: str


def check_ira_status(drug_name: str) -> dict[str, object]:
    """Check if a drug is subject to IRA price negotiation.

    Gatekeeper Test: Enbrel Simulation
    - Input: "ENBREL"
    - Expected: is_ira_drug=True, ira_year=2026, "High Risk" warning

    Args:
        drug_name: Name of the drug to check.

    Returns:
        Dictionary with IRA risk assessment:
        - is_ira_drug: bool
        - ira_year: int or None
        - drug_name: matched name or None
        - description: drug description or None
        - warning_message: str
        - risk_level: str
    """
    if not drug_name:
        return {
            "is_ira_drug": False,
            "ira_year": None,
            "drug_name": None,
            "description": None,
            "warning_message": "No drug name provided",
            "risk_level": "Unknown",
        }

    # Normalize drug name for matching
    name_upper = drug_name.upper().strip()

    # Check for exact match first
    if name_upper in IRA_DRUGS_BY_YEAR:
        year = IRA_DRUGS_BY_YEAR[name_upper]
        description = (
            IRA_2026_DRUGS.get(name_upper) or IRA_2027_DRUGS.get(name_upper)
        )

        logger.warning(f"IRA drug detected: {drug_name} (IRA {year})")

        return {
            "is_ira_drug": True,
            "ira_year": year,
            "drug_name": name_upper,
            "description": description,
            "warning_message": (
                f"High Risk / IRA {year}: {drug_name} is subject to Medicare "
                f"price negotiation. 340B margins may be significantly reduced "
                f"starting {year}."
            ),
            "risk_level": "High Risk",
        }

    # Check for partial match (drug name contains IRA drug)
    for ira_drug, year in IRA_DRUGS_BY_YEAR.items():
        if ira_drug in name_upper or name_upper in ira_drug:
            description = (
                IRA_2026_DRUGS.get(ira_drug) or IRA_2027_DRUGS.get(ira_drug)
            )

            logger.warning(f"Potential IRA drug match: {drug_name} -> {ira_drug}")

            return {
                "is_ira_drug": True,
                "ira_year": year,
                "drug_name": ira_drug,
                "description": description,
                "warning_message": (
                    f"High Risk / IRA {year}: {drug_name} appears to match "
                    f"{ira_drug}, which is subject to Medicare price negotiation."
                ),
                "risk_level": "High Risk",
            }

    # Not an IRA drug
    return {
        "is_ira_drug": False,
        "ira_year": None,
        "drug_name": None,
        "description": None,
        "warning_message": "No IRA risk detected",
        "risk_level": "Low Risk",
    }


def get_ira_risk_status(drug_name: str) -> IRARiskStatus:
    """Get structured IRA risk status for a drug.

    Args:
        drug_name: Name of the drug to check.

    Returns:
        IRARiskStatus dataclass with risk assessment.
    """
    result = check_ira_status(drug_name)
    return IRARiskStatus(
        is_ira_drug=bool(result["is_ira_drug"]),
        ira_year=result["ira_year"],  # type: ignore[arg-type]
        drug_name=result["drug_name"],  # type: ignore[arg-type]
        description=result["description"],  # type: ignore[arg-type]
        warning_message=str(result["warning_message"]),
        risk_level=str(result["risk_level"]),
    )


def filter_ira_drugs(drug_names: list[str]) -> list[dict[str, object]]:
    """Filter a list of drugs to find IRA-affected drugs.

    Args:
        drug_names: List of drug names to check.

    Returns:
        List of IRA risk assessments for affected drugs only.
    """
    ira_drugs = []
    for name in drug_names:
        status = check_ira_status(name)
        if status["is_ira_drug"]:
            status["input_name"] = name
            ira_drugs.append(status)

    logger.info(f"Found {len(ira_drugs)} IRA-affected drugs out of {len(drug_names)}")
    return ira_drugs


def get_all_ira_drugs() -> dict[str, dict[str, object]]:
    """Get complete list of all IRA-negotiated drugs.

    Returns:
        Dictionary mapping drug names to their IRA info.
    """
    all_drugs = {}

    for drug, description in IRA_2026_DRUGS.items():
        all_drugs[drug] = {
            "year": 2026,
            "description": description,
            "risk_level": "High Risk",
        }

    for drug, description in IRA_2027_DRUGS.items():
        all_drugs[drug] = {
            "year": 2027,
            "description": description,
            "risk_level": "High Risk",
        }

    return all_drugs
