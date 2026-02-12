# 340B Optimizer v2

Site-of-Care Optimization Engine for 340B drug program revenue maximization.

## Overview

The 340B Optimizer analyzes drug pricing across five reimbursement pathways to identify the highest-margin site of care for each drug in a hospital's formulary:

1. **Pharmacy - Medicaid**: NADAC + dispense fee + markup
2. **Pharmacy - Medicare/Commercial**: AWP-based (85% brand, 20% generic)
3. **Medical - Medicaid**: ASP x 1.04
4. **Medical - Medicare**: ASP x 1.06
5. **Medical - Commercial**: ASP x configurable % (default 1.15)

## Project Structure

```
340b-optimizer-v2/
├── src/optimizer_340b/
│   ├── config.py              # Environment-based configuration
│   ├── models.py              # Drug, MarginAnalysis, DosingProfile
│   ├── ingest/                # Bronze/Silver Layer (data loading)
│   │   ├── loaders.py         # Excel/CSV file loading
│   │   ├── normalizers.py     # NDC normalization, column mapping, joins
│   │   └── validators.py      # Schema validation, gatekeeper tests
│   ├── compute/               # Gold Layer (margin calculation)
│   │   ├── margins.py         # 5-pathway margin engine
│   │   ├── dosing.py          # Loading dose logic (biologics)
│   │   └── retail_pricing.py  # Retail pricing utilities
│   ├── risk/                  # Risk flagging
│   │   ├── ira_flags.py       # IRA (Inflation Reduction Act) detection
│   │   ├── penny_pricing.py   # NADAC penny pricing detection
│   │   └── retail_validation.py
│   └── ui/                    # Streamlit UI
│       ├── app.py             # Main entry point
│       ├── pages/
│       │   ├── upload.py      # Sample data loading
│       │   ├── dashboard.py   # Opportunity ranking dashboard
│       │   ├── drug_detail.py # Drug deep-dive with 5 pathways
│       │   ├── ndc_lookup.py  # Batch NDC margin calculator
│       │   └── manual_upload.py # Manual file upload (10 sources)
│       └── components/
│           ├── capture_slider.py
│           ├── drug_search.py
│           ├── margin_card.py
│           └── risk_badge.py
├── tests/
│   ├── conftest.py            # Shared fixtures
│   ├── test_integration.py    # End-to-end pipeline tests
│   ├── test_models.py         # Data model tests
│   ├── test_config.py         # Configuration tests
│   ├── test_dosing.py         # Dosing calculation tests
│   ├── test_loaders.py        # File loading tests
│   ├── test_margins.py        # Margin calculation tests
│   ├── test_normalizers.py    # NDC normalization tests
│   ├── test_risk_flags.py     # IRA/penny pricing tests
│   └── test_validators.py     # Schema validation tests
├── data/
│   └── sample/                # Sample data files
├── pyproject.toml             # Project configuration
└── README.md
```

## Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Installation

```bash
cd 340b-optimizer-v2

# Create virtual environment and install
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Logging verbosity (DEBUG, INFO, WARNING, ERROR) |
| `DATA_DIR` | `./data/uploads` | Directory for uploaded data files |
| `CACHE_ENABLED` | `true` | Enable caching of computed results |
| `CACHE_TTL_HOURS` | `24` | Cache time-to-live in hours |

## Running

### Streamlit UI

```bash
streamlit run src/optimizer_340b/ui/app.py
```

### Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=src --cov-report=term-missing

# Run specific test file
pytest tests/test_integration.py -v

# Skip integration tests requiring real data
pytest tests/ -v -m "not integration"
```

## Data Sources

The optimizer ingests 10 data sources (CMS skip_rows noted):

| Source | Format | Skip Rows | Key Columns |
|---|---|---|---|
| Product Catalog | Excel | 0 | NDC, AWP, Contract Cost |
| ASP Pricing | CSV | 8 | HCPCS Code, Payment Limit |
| ASP NDC-HCPCS Crosswalk | CSV | 8 | NDC, HCPCS Code, Bill Units |
| NADAC Statistics | CSV | 0 | ndc, total_discount_340b_pct |
| NOC Pricing | CSV | 12 | Drug Generic Name, Payment Limit |
| NOC Crosswalk | CSV | 9 | NDC, Drug Generic Name |
| IRA Drug List | CSV | 0 | drug_name, ira_year |
| Biologics Logic Grid | Excel | 0 | Drug Name, Year 1 Fills |
| Wholesaler Catalog | Excel | 0 | NDC, WAC |
| Payer Mix | CSV | 0 | Payer, Percentage |

## Key Financial Formulas

- **ASP Back-calculation**: `true_asp = Payment_Limit / 1.06` (CMS Payment Limit includes 6% markup)
- **Retail Gross**: `AWP x 85% - Contract_Cost` (brand) or `AWP x 20% - Contract_Cost` (generic)
- **Medicare Medical**: `ASP x 1.06 x Bill_Units - Contract_Cost`
- **Commercial Medical**: `ASP x 1.15 x Bill_Units - Contract_Cost`
- **Medicaid Medical**: `ASP x 1.04 x Bill_Units - Contract_Cost`
- **Penny Pricing Override**: If `penny_pricing == 'Yes'`, override Cost_Basis to $0.01

## Gatekeeper Tests

These critical tests validate financial accuracy:

1. **Medicare Unit Test**: Manual calculation must match to the penny
2. **Commercial Unit Test**: 1.15x multiplier correctly applied
3. **Capture Rate Stress Test**: 100% to 40% toggle reduces retail proportionately
4. **Loading Dose Logic**: Cosentyx Psoriasis shows 17 Year 1 fills vs 12 Maintenance
5. **IRA Simulation**: Enbrel flagged as "High Risk / IRA 2026"
6. **Penny Pricing Alert**: High-discount drugs excluded from Top Opportunities
