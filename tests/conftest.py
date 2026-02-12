"""Shared pytest fixtures for 340B Optimizer tests."""

import os
from collections.abc import Generator
from decimal import Decimal
from unittest.mock import patch

import polars as pl
import pytest

from optimizer_340b.config import Settings
from optimizer_340b.models import DosingProfile, Drug, MarginAnalysis, RecommendedPath


@pytest.fixture
def mock_env_vars() -> Generator[dict[str, str], None, None]:
    """Set up mock environment variables for testing.

    Yields:
        Dictionary of mock environment variables.
    """
    env_vars = {
        "LOG_LEVEL": "DEBUG",
        "DATA_DIR": "/tmp/test_data",
        "CACHE_ENABLED": "false",
        "CACHE_TTL_HOURS": "1",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        yield env_vars


@pytest.fixture
def test_settings(mock_env_vars: dict[str, str]) -> Settings:
    """Create test settings with mock values.

    Args:
        mock_env_vars: Mock environment variables fixture.

    Returns:
        Settings instance configured for testing.
    """
    return Settings.from_env()


@pytest.fixture
def sample_drug() -> Drug:
    """Sample drug for testing - Humira-like profile.

    Returns:
        Drug instance with realistic Humira-like pricing.
    """
    return Drug(
        ndc="0074-4339-02",
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


@pytest.fixture
def sample_drug_retail_only() -> Drug:
    """Sample drug without HCPCS mapping (retail only).

    Returns:
        Drug instance that can only be dispensed via retail.
    """
    return Drug(
        ndc="1234567890",
        drug_name="GENERIC ORAL",
        manufacturer="TEVA",
        contract_cost=Decimal("10.00"),
        awp=Decimal("100.00"),
        asp=None,
        hcpcs_code=None,
        bill_units_per_package=1,
        therapeutic_class="Generic",
        is_biologic=False,
        ira_flag=False,
        penny_pricing_flag=False,
    )


@pytest.fixture
def sample_drug_ira_flagged() -> Drug:
    """Sample drug subject to IRA price negotiation.

    Returns:
        Drug instance flagged for IRA 2026.
    """
    return Drug(
        ndc="5555555555",
        drug_name="ENBREL",
        manufacturer="AMGEN",
        contract_cost=Decimal("200.00"),
        awp=Decimal("7000.00"),
        asp=Decimal("3000.00"),
        hcpcs_code="J1438",
        bill_units_per_package=4,
        therapeutic_class="TNF Inhibitor",
        is_biologic=True,
        ira_flag=True,
        penny_pricing_flag=False,
    )


@pytest.fixture
def sample_dosing_profile() -> DosingProfile:
    """Sample dosing profile for Cosentyx-like drug.

    Returns:
        DosingProfile with loading dose pattern.
    """
    return DosingProfile(
        drug_name="COSENTYX",
        indication="Psoriasis",
        year_1_fills=17,  # Loading: 5 fills in month 1, then monthly
        year_2_plus_fills=12,  # Monthly maintenance
        adjusted_year_1_fills=Decimal("15.3"),  # 90% compliance
    )


@pytest.fixture
def sample_margin_analysis(sample_drug: Drug) -> MarginAnalysis:
    """Sample margin analysis for testing.

    Args:
        sample_drug: Sample drug fixture.

    Returns:
        MarginAnalysis instance with pre-calculated values.
    """
    return MarginAnalysis(
        drug=sample_drug,
        retail_gross_margin=Decimal("5375.00"),
        retail_net_margin=Decimal("2418.75"),
        retail_capture_rate=Decimal("0.45"),
        medicare_margin=Decimal("5786.00"),
        commercial_margin=Decimal("6290.00"),
        recommended_path=RecommendedPath.COMMERCIAL_MEDICAL,
        margin_delta=Decimal("504.00"),
    )


@pytest.fixture
def sample_catalog_df() -> pl.DataFrame:
    """Sample product catalog DataFrame.

    Returns:
        Polars DataFrame with sample catalog data.
    """
    return pl.DataFrame(
        {
            "NDC": ["0074-4339-02", "1234567890", "5555555555"],
            "Drug Name": ["HUMIRA", "GENERIC ORAL", "ENBREL"],
            "Manufacturer": ["ABBVIE", "TEVA", "AMGEN"],
            "Contract Cost": [150.00, 10.00, 200.00],
            "AWP": [6500.00, 100.00, 7000.00],
        }
    )


@pytest.fixture
def sample_asp_crosswalk_df() -> pl.DataFrame:
    """Sample ASP NDC-HCPCS crosswalk DataFrame.

    Returns:
        Polars DataFrame with sample crosswalk data.
    """
    return pl.DataFrame(
        {
            "NDC": ["0074-4339-02", "5555555555"],
            "HCPCS Code": ["J0135", "J1438"],
            "Billing Units Per Package": [2, 4],
        }
    )


@pytest.fixture
def sample_asp_pricing_df() -> pl.DataFrame:
    """Sample ASP pricing file DataFrame.

    Returns:
        Polars DataFrame with sample ASP pricing.
    """
    return pl.DataFrame(
        {
            "HCPCS Code": ["J0135", "J1438"],
            "Payment Limit": [2800.00, 3000.00],
        }
    )


@pytest.fixture
def sample_nadac_df() -> pl.DataFrame:
    """Sample NADAC statistics DataFrame.

    Returns:
        Polars DataFrame with sample NADAC data.
    """
    return pl.DataFrame(
        {
            "ndc": ["0074433902", "1234567890", "9999999999"],
            "total_discount_340b_pct": [85.5, 45.0, 99.9],
            "penny_pricing": [False, False, True],
        }
    )
