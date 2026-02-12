"""Integration tests for 340B Optimizer v2 - Complete pipeline validation.

These tests validate the complete data pipeline from import verification
through margin calculation, risk flagging, and pathway recommendation.

Run with: pytest tests/test_integration.py -v
"""

from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from optimizer_340b.compute.dosing import (
    apply_loading_dose_logic,
    calculate_year_1_vs_maintenance_delta,
    load_biologics_grid,
)
from optimizer_340b.compute.margins import (
    COMMERCIAL_ASP_MULTIPLIER,
    MEDICARE_ASP_MULTIPLIER,
    MEDICAID_ASP_MULTIPLIER,
    analyze_drug_margin,
    analyze_drug_margin_5pathway,
    calculate_commercial_margin,
    calculate_margin_sensitivity,
    calculate_medical_commercial_margin,
    calculate_medical_medicaid_margin,
    calculate_medical_medicare_margin,
    calculate_medicare_margin,
    calculate_pharmacy_medicaid_margin,
    calculate_pharmacy_medicare_commercial_margin,
    calculate_retail_margin,
)
from optimizer_340b.ingest.loaders import load_csv_to_polars, load_excel_to_polars
from optimizer_340b.ingest.normalizers import (
    build_silver_dataset,
    join_catalog_to_crosswalk,
    normalize_catalog,
    normalize_crosswalk,
    normalize_ndc,
    preprocess_cms_csv,
)
from optimizer_340b.ingest.validators import (
    validate_asp_schema,
    validate_catalog_schema,
    validate_crosswalk_schema,
)
from optimizer_340b.models import (
    DosingProfile,
    Drug,
    MarginAnalysis,
    RecommendedPath,
    RiskLevel,
)
from optimizer_340b.risk.ira_flags import check_ira_status
from optimizer_340b.risk.penny_pricing import check_penny_pricing_for_drug

# Path to real data files (skip tests if not available)
DATA_DIR = Path("/Users/mohsin.ansari/Github/inbox/340B_Engine")


# ============================================================================
# IMPORT & MODULE WIRING TESTS
# ============================================================================


class TestImportWiring:
    """Verify all modules can be imported and are wired correctly."""

    def test_models_import(self) -> None:
        """Core models should be importable."""
        assert Drug is not None
        assert MarginAnalysis is not None
        assert DosingProfile is not None
        assert RecommendedPath is not None
        assert RiskLevel is not None

    def test_config_import(self) -> None:
        """Config module should be importable."""
        from optimizer_340b.config import Settings

        settings = Settings.from_env()
        assert settings.log_level in ["DEBUG", "INFO", "WARNING", "ERROR"]

    def test_ingest_loaders_import(self) -> None:
        """Ingest loaders should be importable."""
        assert load_csv_to_polars is not None
        assert load_excel_to_polars is not None

    def test_ingest_normalizers_import(self) -> None:
        """Ingest normalizers should be importable."""
        assert normalize_catalog is not None
        assert normalize_crosswalk is not None
        assert normalize_ndc is not None
        assert preprocess_cms_csv is not None
        assert build_silver_dataset is not None

    def test_ingest_validators_import(self) -> None:
        """Ingest validators should be importable."""
        assert validate_catalog_schema is not None
        assert validate_crosswalk_schema is not None
        assert validate_asp_schema is not None

    def test_compute_margins_import(self) -> None:
        """Compute margins should be importable."""
        assert analyze_drug_margin is not None
        assert analyze_drug_margin_5pathway is not None
        assert calculate_retail_margin is not None
        assert calculate_medicare_margin is not None
        assert calculate_commercial_margin is not None
        assert calculate_pharmacy_medicaid_margin is not None
        assert calculate_pharmacy_medicare_commercial_margin is not None
        assert calculate_medical_medicaid_margin is not None
        assert calculate_medical_medicare_margin is not None
        assert calculate_medical_commercial_margin is not None

    def test_compute_dosing_import(self) -> None:
        """Compute dosing should be importable."""
        assert apply_loading_dose_logic is not None
        assert calculate_year_1_vs_maintenance_delta is not None
        assert load_biologics_grid is not None

    def test_risk_ira_import(self) -> None:
        """Risk IRA flags should be importable."""
        assert check_ira_status is not None

    def test_risk_penny_pricing_import(self) -> None:
        """Risk penny pricing should be importable."""
        assert check_penny_pricing_for_drug is not None

    def test_ui_app_import(self) -> None:
        """UI app module should be importable."""
        from optimizer_340b.ui import app

        assert app is not None

    def test_ui_pages_import(self) -> None:
        """UI page modules should be importable."""
        from optimizer_340b.ui.pages import (
            dashboard,
            drug_detail,
            manual_upload,
            ndc_lookup,
            upload,
        )

        assert upload is not None
        assert dashboard is not None
        assert drug_detail is not None
        assert ndc_lookup is not None
        assert manual_upload is not None

    def test_ui_components_import(self) -> None:
        """UI component modules should be importable."""
        from optimizer_340b.ui.components import (
            capture_slider,
            drug_search,
            margin_card,
            risk_badge,
        )

        assert capture_slider is not None
        assert drug_search is not None
        assert margin_card is not None
        assert risk_badge is not None


# ============================================================================
# NDC NORMALIZATION TESTS
# ============================================================================


class TestNDCNormalization:
    """Tests for NDC normalization across the pipeline."""

    def test_ndc_normalization_dashes(self) -> None:
        """NDC with dashes should normalize to 11 digits."""
        assert normalize_ndc("0074-4339-02") == "00074433902"

    def test_ndc_normalization_11digit(self) -> None:
        """11-digit NDC should be preserved."""
        assert normalize_ndc("00074433902") == "00074433902"

    def test_ndc_normalization_short(self) -> None:
        """Short NDC should be padded to 11 digits."""
        assert normalize_ndc("74433902") == "00074433902"

    def test_ndc_normalization_10digit(self) -> None:
        """10-digit NDC should be padded to 11 digits."""
        assert normalize_ndc("1234567890") == "01234567890"

    def test_ndc_normalization_length_always_11(self) -> None:
        """All normalized NDCs should be exactly 11 digits."""
        test_cases = ["0074-4339-02", "00074433902", "74433902", "1234567890"]
        for ndc in test_cases:
            result = normalize_ndc(ndc)
            assert len(result) == 11, f"Not 11 digits for {ndc}: got {result}"

    def test_drug_model_ndc_normalized(self) -> None:
        """Drug model ndc_normalized property should match normalize_ndc."""
        drug = Drug(
            ndc="0074-4339-02",
            drug_name="HUMIRA",
            manufacturer="ABBVIE",
            contract_cost=Decimal("150.00"),
            awp=Decimal("6500.00"),
        )
        assert drug.ndc_normalized == "00074433902"

    def test_drug_model_ndc_formatted(self) -> None:
        """Drug model ndc_formatted should produce 5-4-2 dash format."""
        drug = Drug(
            ndc="00074433902",
            drug_name="HUMIRA",
            manufacturer="ABBVIE",
            contract_cost=Decimal("150.00"),
            awp=Decimal("6500.00"),
        )
        assert drug.ndc_formatted == "00074-4339-02"


# ============================================================================
# GATEKEEPER: FINANCIAL ACCURACY TESTS
# ============================================================================


class TestFinancialAccuracy:
    """Success Metric #2: Financial Accuracy.

    Margins must match manual calculation to the penny.
    """

    def test_retail_margin_calculation(self) -> None:
        """Retail margin: AWP * 85% - Contract_Cost."""
        drug = Drug(
            ndc="0074433902",
            drug_name="HUMIRA",
            manufacturer="ABBVIE",
            contract_cost=Decimal("150.00"),
            awp=Decimal("6500.00"),
        )
        gross, net = calculate_retail_margin(drug, Decimal("1.00"))
        # $6500 * 0.85 - $150 = $5525 - $150 = $5375
        assert gross == Decimal("5375.00")
        assert net == Decimal("5375.00")  # 100% capture

    def test_medicare_margin_asp_plus_6(self) -> None:
        """Medicare: ASP * 1.06 * Bill_Units - Contract_Cost."""
        drug = Drug(
            ndc="0074433902",
            drug_name="HUMIRA",
            manufacturer="ABBVIE",
            contract_cost=Decimal("150.00"),
            awp=Decimal("6500.00"),
            asp=Decimal("2800.00"),
            hcpcs_code="J0135",
            bill_units_per_package=2,
        )
        margin = calculate_medicare_margin(drug)
        # $2800 * 1.06 * 2 - $150 = $5936 - $150 = $5786
        expected = Decimal("2800") * Decimal("1.06") * 2 - Decimal("150")
        assert margin == expected
        assert margin == Decimal("5786.00")

    def test_commercial_margin_asp_plus_15(self) -> None:
        """Commercial: ASP * 1.15 * Bill_Units - Contract_Cost."""
        drug = Drug(
            ndc="0074433902",
            drug_name="HUMIRA",
            manufacturer="ABBVIE",
            contract_cost=Decimal("150.00"),
            awp=Decimal("6500.00"),
            asp=Decimal("2800.00"),
            hcpcs_code="J0135",
            bill_units_per_package=2,
        )
        margin = calculate_commercial_margin(drug)
        # $2800 * 1.15 * 2 - $150 = $6440 - $150 = $6290
        expected = Decimal("2800") * Decimal("1.15") * 2 - Decimal("150")
        assert margin == expected
        assert margin == Decimal("6290.00")

    def test_commercial_higher_than_medicare(self) -> None:
        """Commercial margin should always exceed Medicare (1.15 > 1.06)."""
        drug = Drug(
            ndc="1234567890",
            drug_name="TEST_DRUG",
            manufacturer="TEST",
            contract_cost=Decimal("100.00"),
            awp=Decimal("1000.00"),
            asp=Decimal("500.00"),
            hcpcs_code="J9999",
            bill_units_per_package=1,
        )
        medicare = calculate_medicare_margin(drug)
        commercial = calculate_commercial_margin(drug)
        assert commercial is not None
        assert medicare is not None
        assert commercial > medicare

    def test_margin_multiplier_constants(self) -> None:
        """Verify ASP multiplier constants."""
        assert MEDICAID_ASP_MULTIPLIER == Decimal("1.04")
        assert MEDICARE_ASP_MULTIPLIER == Decimal("1.06")
        assert COMMERCIAL_ASP_MULTIPLIER == Decimal("1.15")

    def test_all_pathway_precision(self) -> None:
        """Complete analysis should match expected values to the penny."""
        drug = Drug(
            ndc="0074433902",
            drug_name="HUMIRA",
            manufacturer="ABBVIE",
            contract_cost=Decimal("150.00"),
            awp=Decimal("6500.00"),
            asp=Decimal("2800.00"),
            hcpcs_code="J0135",
            bill_units_per_package=2,
        )
        analysis = analyze_drug_margin(drug)
        assert analysis.retail_gross_margin == Decimal("5375.00")
        assert analysis.medicare_margin == Decimal("5786.00")
        assert analysis.commercial_margin == Decimal("6290.00")


# ============================================================================
# GATEKEEPER: CAPTURE RATE STRESS TESTS
# ============================================================================


class TestCaptureRateStress:
    """Gatekeeper: Capture Rate Stress Test.

    Toggling from 100% to 40% should reduce retail proportionately.
    """

    def test_capture_rate_100_to_40_proportional(self) -> None:
        """Retail margin at 40% should be exactly 40% of margin at 100%."""
        drug = Drug(
            ndc="0074433902",
            drug_name="HUMIRA",
            manufacturer="ABBVIE",
            contract_cost=Decimal("150.00"),
            awp=Decimal("6500.00"),
        )
        _, net_100 = calculate_retail_margin(drug, Decimal("1.00"))
        _, net_40 = calculate_retail_margin(drug, Decimal("0.40"))
        assert net_40 == net_100 * Decimal("0.40")

    def test_capture_rate_sensitivity_linear(self) -> None:
        """Retail margins should scale linearly with capture rate."""
        drug = Drug(
            ndc="1234567890",
            drug_name="TEST_DRUG",
            manufacturer="TEST",
            contract_cost=Decimal("100.00"),
            awp=Decimal("1000.00"),
        )
        results = calculate_margin_sensitivity(
            drug,
            [Decimal("0.20"), Decimal("0.40"), Decimal("0.60"), Decimal("0.80")],
        )
        margins = [r["retail_net"] for r in results]
        deltas = [margins[i + 1] - margins[i] for i in range(len(margins) - 1)]
        assert all(d == deltas[0] for d in deltas)

    def test_capture_rate_zero_yields_negative(self) -> None:
        """Zero capture rate should yield negative margin (just -contract_cost)."""
        drug = Drug(
            ndc="0074433902",
            drug_name="HUMIRA",
            manufacturer="ABBVIE",
            contract_cost=Decimal("150.00"),
            awp=Decimal("6500.00"),
        )
        _, net = calculate_retail_margin(drug, Decimal("0.00"))
        assert net == Decimal("0") * Decimal("5375.00")  # 0% of gross


# ============================================================================
# GATEKEEPER: LOADING DOSE LOGIC
# ============================================================================


class TestLoadingDoseLogic:
    """Gatekeeper: Loading Dose Logic.

    Cosentyx Psoriasis should show 17 Year 1 fills vs 12 Maintenance.
    """

    @pytest.fixture
    def dosing_grid(self) -> pl.DataFrame:
        return pl.DataFrame({
            "Drug Name": ["COSENTYX", "COSENTYX", "HUMIRA"],
            "Indication": ["Psoriasis", "Ankylosing Spondylitis", "RA"],
            "Year 1 Fills": [17, 13, 26],
            "Year 2+ Fills": [12, 12, 26],
        })

    def test_cosentyx_psoriasis_year_1_fills(
        self, dosing_grid: pl.DataFrame
    ) -> None:
        """Cosentyx Psoriasis should have 17 Year 1 fills."""
        profile = apply_loading_dose_logic(
            "COSENTYX", dosing_grid, indication="Psoriasis"
        )
        assert profile is not None
        assert profile.year_1_fills == 17
        assert profile.year_2_plus_fills == 12

    def test_cosentyx_loading_dose_delta(
        self, dosing_grid: pl.DataFrame
    ) -> None:
        """Year 1 revenue should exceed maintenance by >20%."""
        profile = apply_loading_dose_logic(
            "COSENTYX", dosing_grid, indication="Psoriasis"
        )
        assert profile is not None
        margin_per_fill = Decimal("1000.00")
        result = calculate_year_1_vs_maintenance_delta(profile, margin_per_fill)
        assert result["loading_dose_delta"] > 0
        assert result["loading_dose_delta_pct"] > Decimal("20")

    def test_missing_drug_returns_none(
        self, dosing_grid: pl.DataFrame
    ) -> None:
        """Unknown drug name should return None."""
        profile = apply_loading_dose_logic("NONEXISTENT", dosing_grid)
        assert profile is None


# ============================================================================
# GATEKEEPER: RISK FLAGGING TESTS
# ============================================================================


class TestRiskFlagging:
    """Success Metric #4: Risk Flagging.

    IRA and penny pricing flags must trigger correctly.
    """

    def test_enbrel_ira_flagged(self) -> None:
        """Enbrel should be flagged as IRA 2026 High Risk."""
        status = check_ira_status("ENBREL")
        assert status["is_ira_drug"] is True
        assert status["ira_year"] == 2026
        assert status["risk_level"] == "High Risk"

    def test_enbrel_case_insensitive(self) -> None:
        """IRA check should be case-insensitive."""
        status = check_ira_status("enbrel")
        assert status["is_ira_drug"] is True

    def test_non_ira_drug(self) -> None:
        """Non-IRA drug should be flagged as Low Risk."""
        status = check_ira_status("HUMIRA")
        assert status["is_ira_drug"] is False
        assert status["risk_level"] == "Low Risk"

    def test_penny_pricing_high_discount(self) -> None:
        """Drug with >95% discount should be flagged as penny priced."""
        nadac_df = pl.DataFrame({
            "ndc": ["9999999999"],
            "total_discount_340b_pct": [99.9],
            "penny_pricing": [True],
        })
        status = check_penny_pricing_for_drug("9999999999", nadac_df)
        assert status.is_penny_priced is True
        assert status.should_exclude is True

    def test_penny_pricing_normal_drug(self) -> None:
        """Drug with normal discount should NOT be flagged."""
        nadac_df = pl.DataFrame({
            "ndc": ["0074433902"],
            "total_discount_340b_pct": [45.0],
            "penny_pricing": [False],
        })
        status = check_penny_pricing_for_drug("0074433902", nadac_df)
        assert status.is_penny_priced is False
        assert status.should_exclude is False


# ============================================================================
# RECOMMENDATION LOGIC TESTS
# ============================================================================


class TestRecommendationLogic:
    """Tests for pathway recommendation logic."""

    def test_all_pathways_for_dual_drug(self) -> None:
        """Drug with HCPCS should have all three pathway margins."""
        drug = Drug(
            ndc="0074433902",
            drug_name="HUMIRA",
            manufacturer="ABBVIE",
            contract_cost=Decimal("150.00"),
            awp=Decimal("6500.00"),
            asp=Decimal("2800.00"),
            hcpcs_code="J0135",
            bill_units_per_package=2,
        )
        analysis = analyze_drug_margin(drug, Decimal("0.45"))
        assert analysis.retail_gross_margin > 0
        assert analysis.retail_net_margin > 0
        assert analysis.medicare_margin is not None
        assert analysis.commercial_margin is not None
        assert analysis.recommended_path in [
            RecommendedPath.RETAIL,
            RecommendedPath.MEDICARE_MEDICAL,
            RecommendedPath.COMMERCIAL_MEDICAL,
        ]

    def test_retail_only_drug(self) -> None:
        """Drug without HCPCS should only have retail pathway."""
        drug = Drug(
            ndc="9999999999",
            drug_name="ORAL_DRUG",
            manufacturer="TEST",
            contract_cost=Decimal("50.00"),
            awp=Decimal("500.00"),
        )
        analysis = analyze_drug_margin(drug)
        assert analysis.retail_gross_margin > 0
        assert analysis.medicare_margin is None
        assert analysis.commercial_margin is None
        assert analysis.recommended_path == RecommendedPath.RETAIL

    def test_recommendation_changes_with_capture_rate(self) -> None:
        """Lower capture rate may shift recommendation to medical."""
        drug = Drug(
            ndc="0074433902",
            drug_name="HUMIRA",
            manufacturer="ABBVIE",
            contract_cost=Decimal("150.00"),
            awp=Decimal("6500.00"),
            asp=Decimal("2800.00"),
            hcpcs_code="J0135",
            bill_units_per_package=2,
        )
        analysis_low = analyze_drug_margin(drug, Decimal("0.10"))
        analysis_high = analyze_drug_margin(drug, Decimal("1.00"))
        assert analysis_low.recommended_path is not None
        assert analysis_high.recommended_path is not None
        assert analysis_high.retail_net_margin > analysis_low.retail_net_margin


# ============================================================================
# 5-PATHWAY MARGIN TESTS
# ============================================================================


class TestFivePathwayMargins:
    """Tests for the new 5-pathway margin calculation."""

    def test_pharmacy_medicaid_margin(self) -> None:
        """Pharmacy Medicaid: (NADAC + dispense_fee) * (1 + markup) * capture - cost."""
        drug = Drug(
            ndc="0074433902",
            drug_name="HUMIRA",
            manufacturer="ABBVIE",
            contract_cost=Decimal("150.00"),
            awp=Decimal("6500.00"),
            nadac_price=Decimal("500.00"),
        )
        margin = calculate_pharmacy_medicaid_margin(drug)
        # $500 * 1 * 1 - $150 = $350
        assert margin == Decimal("350.00")

    def test_pharmacy_medicaid_no_nadac_returns_none(self) -> None:
        """Drug without NADAC should return None for Medicaid pharmacy."""
        drug = Drug(
            ndc="0074433902",
            drug_name="HUMIRA",
            manufacturer="ABBVIE",
            contract_cost=Decimal("150.00"),
            awp=Decimal("6500.00"),
        )
        margin = calculate_pharmacy_medicaid_margin(drug)
        assert margin is None

    def test_pharmacy_medicare_commercial_brand(self) -> None:
        """Pharmacy Medicare/Commercial for brand: AWP * 85% - cost."""
        drug = Drug(
            ndc="0074433902",
            drug_name="HUMIRA",
            manufacturer="ABBVIE",
            contract_cost=Decimal("150.00"),
            awp=Decimal("6500.00"),
            is_brand=True,
        )
        margin = calculate_pharmacy_medicare_commercial_margin(drug)
        # $6500 * 0.85 - $150 = $5375
        assert margin == Decimal("5375.00")

    def test_pharmacy_medicare_commercial_generic(self) -> None:
        """Pharmacy Medicare/Commercial for generic: AWP * 20% - cost."""
        drug = Drug(
            ndc="1234567890",
            drug_name="GENERIC",
            manufacturer="TEVA",
            contract_cost=Decimal("10.00"),
            awp=Decimal("100.00"),
            is_brand=False,
        )
        margin = calculate_pharmacy_medicare_commercial_margin(drug)
        # $100 * 0.20 - $10 = $10
        assert margin == Decimal("10.00")

    def test_medical_medicaid_margin(self) -> None:
        """Medical Medicaid: ASP * 1.04 * bill_units - cost."""
        drug = Drug(
            ndc="0074433902",
            drug_name="HUMIRA",
            manufacturer="ABBVIE",
            contract_cost=Decimal("150.00"),
            awp=Decimal("6500.00"),
            asp=Decimal("2800.00"),
            hcpcs_code="J0135",
            bill_units_per_package=2,
        )
        margin = calculate_medical_medicaid_margin(drug)
        # $2800 * 1.04 * 2 - $150 = $5824 - $150 = $5674
        expected = Decimal("2800") * Decimal("1.04") * 2 - Decimal("150")
        assert margin == expected

    def test_5pathway_analysis(self) -> None:
        """5-pathway analysis should populate all margins for dual-eligible drug."""
        drug = Drug(
            ndc="0074433902",
            drug_name="HUMIRA",
            manufacturer="ABBVIE",
            contract_cost=Decimal("150.00"),
            awp=Decimal("6500.00"),
            asp=Decimal("2800.00"),
            hcpcs_code="J0135",
            bill_units_per_package=2,
            nadac_price=Decimal("500.00"),
        )
        analysis = analyze_drug_margin_5pathway(drug)
        assert analysis.pharmacy_medicaid_margin is not None
        assert analysis.pharmacy_medicare_commercial_margin is not None
        assert analysis.medical_medicaid_margin is not None
        assert analysis.medical_medicare_margin is not None
        assert analysis.medical_commercial_margin is not None


# ============================================================================
# AUDITABILITY TESTS
# ============================================================================


class TestAuditability:
    """Success Metric #3: Auditability.

    Every calculated margin should have a clear provenance chain.
    """

    def test_analysis_display_dict(self) -> None:
        """Analysis should contain all input values for audit trail."""
        drug = Drug(
            ndc="0074433902",
            drug_name="HUMIRA",
            manufacturer="ABBVIE",
            contract_cost=Decimal("150.00"),
            awp=Decimal("6500.00"),
            asp=Decimal("2800.00"),
            hcpcs_code="J0135",
            bill_units_per_package=2,
        )
        analysis = analyze_drug_margin(drug, Decimal("0.45"))
        display = analysis.to_display_dict()
        assert "ndc" in display
        assert "drug_name" in display
        assert "contract_cost" in display
        assert "retail_net_margin" in display
        assert "medicare_margin" in display
        assert "commercial_margin" in display
        assert "recommendation" in display

    def test_capture_rate_recorded(self) -> None:
        """Analysis should record the capture rate used."""
        drug = Drug(
            ndc="1234567890",
            drug_name="TEST",
            manufacturer="TEST",
            contract_cost=Decimal("100.00"),
            awp=Decimal("1000.00"),
        )
        analysis = analyze_drug_margin(drug, Decimal("0.60"))
        assert analysis.retail_capture_rate == Decimal("0.60")


# ============================================================================
# OPTIMIZATION VELOCITY TESTS
# ============================================================================


class TestOptimizationVelocity:
    """Success Metric #1: Optimization Velocity.

    100 drug margin calculations should complete quickly.
    """

    def test_margin_calculation_performance(self) -> None:
        """100 drug margin calculations should complete in <5 seconds."""
        import time

        drugs = [
            Drug(
                ndc=f"{i:011d}",
                drug_name=f"TEST_DRUG_{i}",
                manufacturer="TEST",
                contract_cost=Decimal("100.00"),
                awp=Decimal("1000.00"),
                asp=Decimal("500.00"),
                hcpcs_code=f"J{i:04d}",
                bill_units_per_package=1,
            )
            for i in range(100)
        ]

        start = time.time()
        for drug in drugs:
            analysis = analyze_drug_margin(drug)
            _ = analysis.recommended_path
        elapsed = time.time() - start

        assert elapsed < 5.0, f"100 lookups took {elapsed:.2f}s, expected <5s"


# ============================================================================
# END-TO-END WITH REAL DATA (skipped if data not available)
# ============================================================================


@pytest.mark.skipif(
    not DATA_DIR.exists(),
    reason=f"Data directory not found: {DATA_DIR}",
)
class TestEndToEndWithSampleData:
    """End-to-end tests using real data files."""

    def test_silver_to_margin_calculation(self) -> None:
        """Build Silver dataset and calculate margins for sample drugs."""
        catalog_path = DATA_DIR / "product_catalog.xlsx"
        crosswalk_path = DATA_DIR / "October 2025 ASP NDC-HCPCS Crosswalk 090525.csv"
        asp_path = DATA_DIR / "Oct 2025 ASP Pricing File updated 120925.csv"

        for path in [catalog_path, crosswalk_path, asp_path]:
            if not path.exists():
                pytest.skip(f"File not found: {path}")

        catalog_raw = load_excel_to_polars(catalog_path)
        crosswalk_raw = preprocess_cms_csv(str(crosswalk_path), skip_rows=8)
        asp_raw = preprocess_cms_csv(str(asp_path), skip_rows=8)

        silver, _ = build_silver_dataset(catalog_raw, crosswalk_raw, asp_raw)

        # Get a sample drug with complete data
        sample = silver.filter(
            pl.col("ASP").is_not_null()
            & pl.col("AWP").is_not_null()
            & pl.col("Contract Cost").is_not_null()
            & (pl.col("ASP") > 0)
            & (pl.col("AWP") > 0)
        ).head(1)

        if sample.height == 0:
            pytest.skip("No drugs with complete pricing data")

        row = sample.row(0, named=True)
        drug = Drug(
            ndc=str(row["NDC"]),
            drug_name=row.get("Drug Name", "UNKNOWN") or "UNKNOWN",
            manufacturer="UNKNOWN",
            contract_cost=Decimal(str(row["Contract Cost"])),
            awp=Decimal(str(row["AWP"])),
            asp=Decimal(str(row["ASP"])),
            hcpcs_code=row["HCPCS Code"],
            bill_units_per_package=1,
        )

        analysis = analyze_drug_margin(drug)
        assert analysis.retail_gross_margin is not None
        assert analysis.medicare_margin is not None
        assert analysis.commercial_margin is not None
        assert analysis.recommended_path is not None

    def test_crosswalk_join_rate(self) -> None:
        """Crosswalk join should produce >4000 matched rows."""
        catalog_path = DATA_DIR / "product_catalog.xlsx"
        crosswalk_path = DATA_DIR / "October 2025 ASP NDC-HCPCS Crosswalk 090525.csv"

        for path in [catalog_path, crosswalk_path]:
            if not path.exists():
                pytest.skip(f"File not found: {path}")

        catalog_raw = load_excel_to_polars(catalog_path)
        crosswalk_raw = preprocess_cms_csv(str(crosswalk_path), skip_rows=8)

        catalog = normalize_catalog(catalog_raw)
        crosswalk = normalize_crosswalk(crosswalk_raw)

        matched, orphans = join_catalog_to_crosswalk(catalog, crosswalk)
        assert matched.height > 4000, f"Only {matched.height} matched rows"
        assert orphans.height > 0, "Should have some orphans"
