"""Tests for margin calculation engine (Gold Layer Gatekeeper Tests).

These tests implement the Gatekeeper Tests from the Project Charter:
- The "Medicare" Unit Test
- The "Commercial Medical" Unit Test
- The "Capture Rate" Stress Test
"""

from decimal import Decimal

from optimizer_340b.compute.margins import (
    AWP_DISCOUNT_FACTOR,
    COMMERCIAL_ASP_MULTIPLIER,
    DEFAULT_CAPTURE_RATE,
    MEDICARE_ASP_MULTIPLIER,
    analyze_drug_margin,
    analyze_drug_with_payer,
    calculate_commercial_margin,
    calculate_margin_sensitivity,
    calculate_medicare_margin,
    calculate_retail_margin,
    determine_recommendation,
)
from optimizer_340b.models import Drug, RecommendedPath


class TestConstants:
    """Tests for margin calculation constants."""

    def test_awp_discount_factor(self) -> None:
        """AWP discount should be 85% (15% discount)."""
        assert Decimal("0.85") == AWP_DISCOUNT_FACTOR

    def test_medicare_multiplier(self) -> None:
        """Medicare should use ASP + 6%."""
        assert Decimal("1.06") == MEDICARE_ASP_MULTIPLIER

    def test_commercial_multiplier(self) -> None:
        """Commercial should use ASP + 15%."""
        assert Decimal("1.15") == COMMERCIAL_ASP_MULTIPLIER

    def test_default_capture_rate(self) -> None:
        """Default capture rate should be 100%."""
        assert Decimal("1.0") == DEFAULT_CAPTURE_RATE


class TestRetailMargin:
    """Tests for retail margin calculation."""

    def test_retail_margin_basic(self, sample_drug: Drug) -> None:
        """Basic retail margin calculation.

        HUMIRA test data:
        AWP: $6500, Contract: $150
        Gross = $6500 × 0.85 - $150 = $5375
        Net = $5375 × 1.0 = $5375 (at default 100% capture rate)
        """
        gross, net = calculate_retail_margin(sample_drug)

        expected_gross = Decimal("6500") * Decimal("0.85") - Decimal("150")
        assert gross == expected_gross
        assert gross == Decimal("5375.00")

        # Default capture rate is now 100%
        expected_net = expected_gross * Decimal("1.0")
        assert net == expected_net
        assert net == Decimal("5375.00")

    def test_retail_margin_custom_capture_rate(self, sample_drug: Drug) -> None:
        """Retail margin should scale with capture rate."""
        _, net_45 = calculate_retail_margin(sample_drug, Decimal("0.45"))
        _, net_100 = calculate_retail_margin(sample_drug, Decimal("1.00"))

        # Net at 100% should be gross
        gross, _ = calculate_retail_margin(sample_drug)
        assert net_100 == gross

        # Net at 45% should be 45% of gross
        assert net_45 == gross * Decimal("0.45")

    def test_capture_rate_stress_test(self, sample_drug: Drug) -> None:
        """Gatekeeper: Capture Rate Stress Test.

        If the Capture Rate variable is toggled from 100% to 40%,
        does the "Retail Margin" drop proportionately?
        """
        _, net_100 = calculate_retail_margin(sample_drug, Decimal("1.00"))
        _, net_40 = calculate_retail_margin(sample_drug, Decimal("0.40"))

        # Net at 40% should be exactly 40% of net at 100%
        expected_ratio = Decimal("0.40")
        actual_ratio = net_40 / net_100

        assert actual_ratio == expected_ratio

    def test_capture_rate_zero(self, sample_drug: Drug) -> None:
        """Zero capture rate should yield zero net margin."""
        gross, net = calculate_retail_margin(sample_drug, Decimal("0.00"))

        assert gross > 0  # Gross still positive
        assert net == 0  # Net is zero


class TestMedicareMargin:
    """Tests for Medicare medical margin calculation."""

    def test_medicare_margin_unit_test(self, sample_drug: Drug) -> None:
        """Gatekeeper: Medicare Unit Test.

        Manually calculate the margin for one vial using ASP + 6%.
        Does the Engine's output match to the penny?

        HUMIRA test data:
        ASP: $2800, Bill Units: 2, Contract: $150
        Revenue = $2800 × 1.06 × 2 = $5936
        Margin = $5936 - $150 = $5786
        """
        result = calculate_medicare_margin(sample_drug)

        # Manual calculation
        expected_revenue = Decimal("2800") * Decimal("1.06") * 2
        expected_margin = expected_revenue - Decimal("150")

        assert result == expected_margin
        assert result == Decimal("5786.00")

    def test_medicare_margin_returns_none_for_retail_only(
        self, sample_drug_retail_only: Drug
    ) -> None:
        """Drugs without HCPCS should return None for Medicare margin."""
        result = calculate_medicare_margin(sample_drug_retail_only)
        assert result is None

    def test_medicare_formula_components(self, sample_drug: Drug) -> None:
        """Verify each component of Medicare formula."""
        # ASP × 1.06 × Bill_Units - Contract
        asp = sample_drug.asp
        multiplier = MEDICARE_ASP_MULTIPLIER
        units = sample_drug.bill_units_per_package
        contract = sample_drug.contract_cost

        expected = asp * multiplier * units - contract
        result = calculate_medicare_margin(sample_drug)

        assert result == expected


class TestCommercialMargin:
    """Tests for Commercial medical margin calculation."""

    def test_commercial_margin_unit_test(self, sample_drug: Drug) -> None:
        """Gatekeeper: Commercial Medical Unit Test.

        Verify that switching the payer toggle to "Commercial" correctly
        applies the 1.15x multiplier to the ASP baseline.

        HUMIRA test data:
        ASP: $2800, Bill Units: 2, Contract: $150
        Revenue = $2800 × 1.15 × 2 = $6440
        Margin = $6440 - $150 = $6290
        """
        result = calculate_commercial_margin(sample_drug)

        # Manual calculation
        expected_revenue = Decimal("2800") * Decimal("1.15") * 2
        expected_margin = expected_revenue - Decimal("150")

        assert result == expected_margin
        assert result == Decimal("6290.00")

    def test_commercial_higher_than_medicare(self, sample_drug: Drug) -> None:
        """Commercial margin should be higher than Medicare (1.15 > 1.06)."""
        medicare = calculate_medicare_margin(sample_drug)
        commercial = calculate_commercial_margin(sample_drug)

        assert commercial is not None
        assert medicare is not None
        assert commercial > medicare

    def test_commercial_margin_returns_none_for_retail_only(
        self, sample_drug_retail_only: Drug
    ) -> None:
        """Drugs without HCPCS should return None for Commercial margin."""
        result = calculate_commercial_margin(sample_drug_retail_only)
        assert result is None


class TestRecommendation:
    """Tests for pathway recommendation logic."""

    def test_recommends_highest_margin(self) -> None:
        """Should recommend pathway with highest margin."""
        path, delta = determine_recommendation(
            retail_net=Decimal("1000"),
            medicare=Decimal("2000"),
            commercial=Decimal("3000"),
        )

        assert path == RecommendedPath.COMMERCIAL_MEDICAL
        assert delta == Decimal("1000")  # 3000 - 2000

    def test_recommends_retail_when_highest(self) -> None:
        """Should recommend retail when it has highest margin."""
        path, delta = determine_recommendation(
            retail_net=Decimal("5000"),
            medicare=Decimal("2000"),
            commercial=Decimal("3000"),
        )

        assert path == RecommendedPath.RETAIL
        assert delta == Decimal("2000")  # 5000 - 3000

    def test_recommends_retail_when_only_option(self) -> None:
        """Should recommend retail when no medical path available."""
        path, delta = determine_recommendation(
            retail_net=Decimal("1000"),
            medicare=None,
            commercial=None,
        )

        assert path == RecommendedPath.RETAIL
        assert delta == Decimal("1000")

    def test_recommends_medicare_over_retail(self) -> None:
        """Should recommend Medicare when it beats retail."""
        path, delta = determine_recommendation(
            retail_net=Decimal("1000"),
            medicare=Decimal("2000"),
            commercial=None,
        )

        assert path == RecommendedPath.MEDICARE_MEDICAL
        assert delta == Decimal("1000")


class TestAnalyzeDrugMargin:
    """Tests for complete drug margin analysis."""

    def test_analyze_drug_margin_complete(self, sample_drug: Drug) -> None:
        """Should calculate all margins and provide recommendation."""
        analysis = analyze_drug_margin(sample_drug)

        # Verify all margins calculated (default capture rate is now 100%)
        assert analysis.retail_gross_margin == Decimal("5375.00")
        assert analysis.retail_net_margin == Decimal("5375.00")  # 100% capture rate
        assert analysis.medicare_margin == Decimal("5786.00")
        assert analysis.commercial_margin == Decimal("6290.00")

        # Commercial should be recommended (highest)
        assert analysis.recommended_path == RecommendedPath.COMMERCIAL_MEDICAL

    def test_analyze_drug_margin_retail_only(
        self, sample_drug_retail_only: Drug
    ) -> None:
        """Retail-only drug should have None for medical margins."""
        analysis = analyze_drug_margin(sample_drug_retail_only)

        assert analysis.medicare_margin is None
        assert analysis.commercial_margin is None
        assert analysis.recommended_path == RecommendedPath.RETAIL

    def test_capture_rate_affects_recommendation(self, sample_drug: Drug) -> None:
        """Lower capture rate should potentially change recommendation."""
        # At 45% capture, retail may lose to medical
        analysis_45 = analyze_drug_margin(sample_drug, Decimal("0.45"))

        # At 100% capture, retail becomes more competitive
        analysis_100 = analyze_drug_margin(sample_drug, Decimal("1.00"))

        # Verify retail margins change appropriately
        assert analysis_100.retail_net_margin > analysis_45.retail_net_margin

        # At 45% capture, commercial should win
        assert analysis_45.recommended_path == RecommendedPath.COMMERCIAL_MEDICAL

    def test_analysis_includes_capture_rate(self, sample_drug: Drug) -> None:
        """Analysis should record the capture rate used."""
        analysis = analyze_drug_margin(sample_drug, Decimal("0.60"))
        assert analysis.retail_capture_rate == Decimal("0.60")


class TestAnalyzeDrugWithPayer:
    """Tests for payer-specific analysis."""

    def test_analyze_with_medicare(self, sample_drug: Drug) -> None:
        """Should compare retail vs Medicare specifically."""
        analysis = analyze_drug_with_payer(sample_drug, "medicare")

        assert analysis.medicare_margin is not None
        assert analysis.commercial_margin is not None  # Still calculated

    def test_analyze_with_commercial(self, sample_drug: Drug) -> None:
        """Should compare retail vs Commercial specifically."""
        analysis = analyze_drug_with_payer(sample_drug, "commercial")

        assert analysis.commercial_margin is not None
        assert analysis.recommended_path in [
            RecommendedPath.RETAIL,
            RecommendedPath.COMMERCIAL_MEDICAL,
        ]


class TestMarginSensitivity:
    """Tests for capture rate sensitivity analysis."""

    def test_sensitivity_default_rates(self, sample_drug: Drug) -> None:
        """Should calculate margins at default capture rates."""
        results = calculate_margin_sensitivity(sample_drug)

        assert len(results) == 5  # Default rates
        # Verify rates present
        rates = [r["capture_rate"] for r in results]
        assert Decimal("0.40") in rates
        assert Decimal("1.00") in rates

    def test_sensitivity_custom_rates(self, sample_drug: Drug) -> None:
        """Should accept custom capture rates."""
        rates = [Decimal("0.30"), Decimal("0.50"), Decimal("0.70")]
        results = calculate_margin_sensitivity(sample_drug, rates)

        assert len(results) == 3
        assert results[0]["capture_rate"] == Decimal("0.30")

    def test_sensitivity_includes_recommendation(self, sample_drug: Drug) -> None:
        """Each scenario should include a recommendation."""
        results = calculate_margin_sensitivity(sample_drug)

        for result in results:
            assert "recommended" in result
            assert result["recommended"] in [
                "RETAIL",
                "MEDICARE_MEDICAL",
                "COMMERCIAL_MEDICAL",
            ]

    def test_sensitivity_proportional_retail(self, sample_drug: Drug) -> None:
        """Retail margin should scale linearly with capture rate."""
        results = calculate_margin_sensitivity(
            sample_drug,
            [Decimal("0.50"), Decimal("1.00")],
        )

        retail_50 = results[0]["retail_net"]
        retail_100 = results[1]["retail_net"]

        # 50% should be exactly half of 100%
        assert retail_50 == retail_100 / 2


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_zero_contract_cost(self) -> None:
        """Drug with zero contract cost should have higher margins."""
        drug = Drug(
            ndc="1234567890",
            drug_name="FREE_DRUG",
            manufacturer="TEST",
            contract_cost=Decimal("0.00"),
            awp=Decimal("1000.00"),
            asp=Decimal("500.00"),
            hcpcs_code="J9999",
            bill_units_per_package=1,
        )

        gross, _ = calculate_retail_margin(drug)
        medicare = calculate_medicare_margin(drug)

        # Margin equals full revenue when contract is zero
        assert gross == Decimal("1000") * Decimal("0.85")
        assert medicare == Decimal("500") * Decimal("1.06") * 1

    def test_high_contract_cost_negative_margin(self) -> None:
        """Drug with contract > reimbursement should have negative margin."""
        drug = Drug(
            ndc="1234567890",
            drug_name="EXPENSIVE_DRUG",
            manufacturer="TEST",
            contract_cost=Decimal("10000.00"),  # Very high
            awp=Decimal("1000.00"),  # Low AWP
            asp=Decimal("500.00"),
            hcpcs_code="J9999",
            bill_units_per_package=1,
        )

        gross, _ = calculate_retail_margin(drug)
        medicare = calculate_medicare_margin(drug)

        # Margins should be negative
        assert gross < 0
        assert medicare is not None and medicare < 0

    def test_single_bill_unit(self) -> None:
        """Single bill unit should calculate correctly."""
        drug = Drug(
            ndc="1234567890",
            drug_name="SINGLE_UNIT",
            manufacturer="TEST",
            contract_cost=Decimal("100.00"),
            awp=Decimal("1000.00"),
            asp=Decimal("500.00"),
            hcpcs_code="J9999",
            bill_units_per_package=1,
        )

        medicare = calculate_medicare_margin(drug)
        assert medicare == Decimal("500") * Decimal("1.06") - Decimal("100")

    def test_many_bill_units(self) -> None:
        """Multiple bill units should multiply correctly."""
        drug = Drug(
            ndc="1234567890",
            drug_name="MULTI_UNIT",
            manufacturer="TEST",
            contract_cost=Decimal("100.00"),
            awp=Decimal("1000.00"),
            asp=Decimal("500.00"),
            hcpcs_code="J9999",
            bill_units_per_package=10,
        )

        medicare = calculate_medicare_margin(drug)
        # 500 * 1.06 * 10 - 100 = 5300 - 100 = 5200
        assert medicare == Decimal("5200.00")
