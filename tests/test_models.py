"""Tests for 340B Optimizer data models."""

from decimal import Decimal

import pytest

from optimizer_340b.models import (
    DosingProfile,
    Drug,
    MarginAnalysis,
    RecommendedPath,
    RiskLevel,
)


class TestDrug:
    """Tests for Drug dataclass."""

    def test_drug_creation(self, sample_drug: Drug) -> None:
        """Drug should be created with all required fields."""
        assert sample_drug.ndc == "0074-4339-02"
        assert sample_drug.drug_name == "HUMIRA"
        assert sample_drug.manufacturer == "ABBVIE"
        assert sample_drug.contract_cost == Decimal("150.00")
        assert sample_drug.awp == Decimal("6500.00")

    def test_drug_with_asp(self, sample_drug: Drug) -> None:
        """Drug with ASP and HCPCS should have medical path."""
        assert sample_drug.asp == Decimal("2800.00")
        assert sample_drug.hcpcs_code == "J0135"
        assert sample_drug.has_medical_path() is True

    def test_drug_without_asp(self, sample_drug_retail_only: Drug) -> None:
        """Drug without ASP should not have medical path."""
        assert sample_drug_retail_only.asp is None
        assert sample_drug_retail_only.hcpcs_code is None
        assert sample_drug_retail_only.has_medical_path() is False

    def test_drug_ndc_normalized(self, sample_drug: Drug) -> None:
        """NDC should normalize to 11 digits without dashes."""
        assert sample_drug.ndc_normalized == "00074433902"
        assert len(sample_drug.ndc_normalized) == 11

    def test_drug_ndc_formatted(self, sample_drug: Drug) -> None:
        """NDC should format in 5-4-2 dash format."""
        assert sample_drug.ndc_formatted == "00074-4339-02"

    def test_drug_defaults(self) -> None:
        """Drug defaults should be sensible."""
        drug = Drug(
            ndc="1234567890",
            drug_name="TEST",
            manufacturer="TEST",
            contract_cost=Decimal("100.00"),
            awp=Decimal("1000.00"),
        )
        assert drug.asp is None
        assert drug.hcpcs_code is None
        assert drug.bill_units_per_package == 1
        assert drug.is_biologic is False
        assert drug.is_brand is True
        assert drug.ira_flag is False
        assert drug.penny_pricing_flag is False
        assert drug.nadac_price is None

    def test_drug_ira_flag(self, sample_drug_ira_flagged: Drug) -> None:
        """IRA-flagged drug should have flag set."""
        assert sample_drug_ira_flagged.ira_flag is True
        assert sample_drug_ira_flagged.drug_name == "ENBREL"

    def test_drug_therapeutic_class(self, sample_drug: Drug) -> None:
        """Drug should store therapeutic class."""
        assert sample_drug.therapeutic_class == "TNF Inhibitor"

    def test_drug_has_medical_path_requires_both(self) -> None:
        """has_medical_path requires both ASP and HCPCS code."""
        # ASP only, no HCPCS
        drug_asp_only = Drug(
            ndc="1234567890",
            drug_name="TEST",
            manufacturer="TEST",
            contract_cost=Decimal("100.00"),
            awp=Decimal("1000.00"),
            asp=Decimal("500.00"),
            hcpcs_code=None,
        )
        assert drug_asp_only.has_medical_path() is False

        # HCPCS only, no ASP
        drug_hcpcs_only = Drug(
            ndc="1234567890",
            drug_name="TEST",
            manufacturer="TEST",
            contract_cost=Decimal("100.00"),
            awp=Decimal("1000.00"),
            asp=None,
            hcpcs_code="J0135",
        )
        assert drug_hcpcs_only.has_medical_path() is False


class TestDosingProfile:
    """Tests for DosingProfile dataclass."""

    def test_dosing_profile_creation(
        self, sample_dosing_profile: DosingProfile
    ) -> None:
        """DosingProfile should be created with correct fields."""
        assert sample_dosing_profile.drug_name == "COSENTYX"
        assert sample_dosing_profile.indication == "Psoriasis"
        assert sample_dosing_profile.year_1_fills == 17
        assert sample_dosing_profile.year_2_plus_fills == 12

    def test_year_1_revenue(self, sample_dosing_profile: DosingProfile) -> None:
        """Year 1 revenue uses adjusted fills * margin."""
        revenue = sample_dosing_profile.year_1_revenue(Decimal("1000.00"))
        # 15.3 * $1000 = $15,300
        assert revenue == Decimal("15300.0")

    def test_maintenance_revenue(self, sample_dosing_profile: DosingProfile) -> None:
        """Maintenance revenue uses year_2_plus_fills * margin."""
        revenue = sample_dosing_profile.maintenance_revenue(Decimal("1000.00"))
        # 12 * $1000 = $12,000
        assert revenue == Decimal("12000.00")

    def test_loading_dose_delta(self, sample_dosing_profile: DosingProfile) -> None:
        """Loading dose delta = Year 1 - Maintenance."""
        delta = sample_dosing_profile.loading_dose_delta(Decimal("1000.00"))
        # $15,300 - $12,000 = $3,300
        assert delta == Decimal("3300.0")

    def test_adjusted_fills_compliance(
        self, sample_dosing_profile: DosingProfile
    ) -> None:
        """Adjusted Year 1 fills should reflect 90% compliance."""
        # 17 * 0.90 = 15.3
        assert sample_dosing_profile.adjusted_year_1_fills == Decimal("15.3")


class TestMarginAnalysis:
    """Tests for MarginAnalysis dataclass."""

    def test_margin_analysis_creation(
        self, sample_margin_analysis: MarginAnalysis
    ) -> None:
        """MarginAnalysis should store all margins."""
        assert sample_margin_analysis.retail_gross_margin == Decimal("5375.00")
        assert sample_margin_analysis.retail_net_margin == Decimal("2418.75")
        assert sample_margin_analysis.medicare_margin == Decimal("5786.00")
        assert sample_margin_analysis.commercial_margin == Decimal("6290.00")

    def test_recommended_path(self, sample_margin_analysis: MarginAnalysis) -> None:
        """Recommendation should be the highest-margin path."""
        assert (
            sample_margin_analysis.recommended_path
            == RecommendedPath.COMMERCIAL_MEDICAL
        )

    def test_display_dict_keys(self, sample_margin_analysis: MarginAnalysis) -> None:
        """Display dict should contain all required keys."""
        display = sample_margin_analysis.to_display_dict()
        required_keys = [
            "ndc",
            "drug_name",
            "manufacturer",
            "contract_cost",
            "awp",
            "asp",
            "retail_gross_margin",
            "retail_net_margin",
            "retail_capture_rate",
            "medicare_margin",
            "commercial_margin",
            "recommendation",
            "margin_delta",
            "ira_risk",
            "penny_pricing",
        ]
        for key in required_keys:
            assert key in display, f"Missing key: {key}"

    def test_display_dict_values(self, sample_margin_analysis: MarginAnalysis) -> None:
        """Display dict should contain correct float values."""
        display = sample_margin_analysis.to_display_dict()
        assert display["ndc"] == "0074-4339-02"
        assert display["drug_name"] == "HUMIRA"
        assert display["contract_cost"] == 150.00
        assert display["recommendation"] == "COMMERCIAL_MEDICAL"


class TestEnums:
    """Tests for enum types."""

    def test_recommended_path_values(self) -> None:
        """RecommendedPath should have all three paths."""
        assert RecommendedPath.RETAIL.value == "RETAIL"
        assert RecommendedPath.MEDICARE_MEDICAL.value == "MEDICARE_MEDICAL"
        assert RecommendedPath.COMMERCIAL_MEDICAL.value == "COMMERCIAL_MEDICAL"

    def test_risk_level_values(self) -> None:
        """RiskLevel should have LOW, MEDIUM, HIGH."""
        assert RiskLevel.LOW.value == "LOW"
        assert RiskLevel.MEDIUM.value == "MEDIUM"
        assert RiskLevel.HIGH.value == "HIGH"

    def test_enum_string_comparison(self) -> None:
        """Enum values should work with string comparison (str, Enum)."""
        assert RecommendedPath.RETAIL == "RETAIL"
        assert RiskLevel.HIGH == "HIGH"
