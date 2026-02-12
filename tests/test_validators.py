"""Tests for schema validation (Bronze Layer Gatekeeper Tests)."""

import polars as pl

from optimizer_340b.ingest.validators import (
    TOP_50_DRUG_NAMES,
    ValidationResult,
    validate_asp_quarter,
    validate_asp_schema,
    validate_catalog_row_volume,
    validate_catalog_schema,
    validate_crosswalk_integrity,
    validate_crosswalk_schema,
    validate_nadac_schema,
    validate_top_drugs_pricing,
)


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_default_values(self) -> None:
        """ValidationResult should have sensible defaults."""
        result = ValidationResult(is_valid=True, message="OK")

        assert result.missing_columns == []
        assert result.row_count == 0
        assert result.warnings == []

    def test_with_all_fields(self) -> None:
        """ValidationResult should accept all fields."""
        result = ValidationResult(
            is_valid=False,
            message="Failed",
            missing_columns=["A", "B"],
            row_count=100,
            warnings=["Warning 1"],
        )

        assert result.is_valid is False
        assert result.missing_columns == ["A", "B"]
        assert result.row_count == 100
        assert len(result.warnings) == 1


class TestCatalogValidation:
    """Tests for catalog schema validation."""

    def test_valid_catalog_passes(self, sample_catalog_df: pl.DataFrame) -> None:
        """Valid catalog with required columns should pass."""
        result = validate_catalog_schema(sample_catalog_df)

        assert result.is_valid is True
        assert result.missing_columns == []
        assert result.row_count == 3

    def test_missing_ndc_fails(self) -> None:
        """Catalog without NDC column should fail."""
        df = pl.DataFrame({"Contract Cost": [100], "AWP": [200]})

        result = validate_catalog_schema(df)

        assert result.is_valid is False
        assert "NDC" in result.missing_columns

    def test_missing_contract_cost_fails(self) -> None:
        """Catalog without Contract Cost should fail."""
        df = pl.DataFrame({"NDC": ["123"], "AWP": [200]})

        result = validate_catalog_schema(df)

        assert result.is_valid is False
        assert "Contract Cost" in result.missing_columns

    def test_missing_awp_fails(self) -> None:
        """Catalog without AWP should fail."""
        df = pl.DataFrame({"NDC": ["123"], "Contract Cost": [100]})

        result = validate_catalog_schema(df)

        assert result.is_valid is False
        assert "AWP" in result.missing_columns

    def test_missing_multiple_columns(self) -> None:
        """Should report all missing columns."""
        df = pl.DataFrame({"Other": [1, 2, 3]})

        result = validate_catalog_schema(df)

        assert result.is_valid is False
        # Now requires NDC + AWP (2 columns), cost column checked separately
        assert len(result.missing_columns) == 2
        assert set(result.missing_columns) == {"NDC", "AWP"}

    def test_warns_on_missing_optional_columns(self) -> None:
        """Should warn when recommended columns are missing."""
        df = pl.DataFrame(
            {
                "NDC": ["123"],
                "Contract Cost": [100],
                "AWP": [200],
            }
        )

        result = validate_catalog_schema(df)

        assert result.is_valid is True
        assert len(result.warnings) > 0
        assert any("recommended columns" in w for w in result.warnings)


class TestCatalogRowVolume:
    """Tests for catalog row volume validation."""

    def test_sufficient_rows_passes(self) -> None:
        """Catalog with enough rows should pass."""
        df = pl.DataFrame({"NDC": [f"{i:011d}" for i in range(35000)]})

        result = validate_catalog_row_volume(df, min_rows=30000)

        assert result.is_valid is True
        assert result.row_count == 35000

    def test_insufficient_rows_fails(self) -> None:
        """Catalog with too few rows should fail."""
        df = pl.DataFrame({"NDC": ["123", "456"]})

        result = validate_catalog_row_volume(df, min_rows=30000)

        assert result.is_valid is False
        assert "expected >30,000" in result.message

    def test_custom_threshold(self) -> None:
        """Should respect custom row threshold."""
        df = pl.DataFrame({"NDC": [f"{i}" for i in range(100)]})

        # Should pass with lower threshold
        result = validate_catalog_row_volume(df, min_rows=50)
        assert result.is_valid is True

        # Should fail with higher threshold
        result = validate_catalog_row_volume(df, min_rows=200)
        assert result.is_valid is False


class TestASPValidation:
    """Tests for ASP file validation."""

    def test_valid_asp_passes(self, sample_asp_pricing_df: pl.DataFrame) -> None:
        """Valid ASP file should pass."""
        result = validate_asp_schema(sample_asp_pricing_df)

        assert result.is_valid is True
        assert result.row_count == 2

    def test_missing_hcpcs_fails(self) -> None:
        """ASP file without HCPCS Code should fail."""
        df = pl.DataFrame({"Payment Limit": [100, 200]})

        result = validate_asp_schema(df)

        assert result.is_valid is False
        assert "HCPCS Code" in result.missing_columns

    def test_missing_payment_limit_fails(self) -> None:
        """ASP file without Payment Limit should fail."""
        df = pl.DataFrame({"HCPCS Code": ["J0135"]})

        result = validate_asp_schema(df)

        assert result.is_valid is False
        assert "Payment Limit" in result.missing_columns


class TestASPQuarterValidation:
    """Tests for ASP file currency validation."""

    def test_correct_quarter_passes(self) -> None:
        """ASP file with expected quarter should pass."""
        df = pl.DataFrame(
            {
                "HCPCS Code": ["J0135"],
                "Payment Limit": [100],
                "Quarter": ["Q4 2025"],
            }
        )

        result = validate_asp_quarter(df, expected_quarter="Q4 2025")

        assert result.is_valid is True

    def test_wrong_quarter_fails(self) -> None:
        """ASP file with wrong quarter should fail."""
        df = pl.DataFrame(
            {
                "HCPCS Code": ["J0135"],
                "Quarter": ["Q3 2025"],
            }
        )

        result = validate_asp_quarter(df, expected_quarter="Q4 2025")

        assert result.is_valid is False
        assert "Q4 2025" in result.message

    def test_no_quarter_column_passes_with_warning(self) -> None:
        """Missing quarter column should pass with warning."""
        df = pl.DataFrame({"HCPCS Code": ["J0135"], "Payment Limit": [100]})

        result = validate_asp_quarter(df, expected_quarter="Q4 2025")

        assert result.is_valid is True
        assert len(result.warnings) > 0


class TestCrosswalkValidation:
    """Tests for NDC-HCPCS crosswalk validation."""

    def test_valid_crosswalk_passes(
        self, sample_asp_crosswalk_df: pl.DataFrame
    ) -> None:
        """Valid crosswalk should pass."""
        result = validate_crosswalk_schema(sample_asp_crosswalk_df)

        assert result.is_valid is True
        assert result.row_count == 2

    def test_missing_ndc_fails(self) -> None:
        """Crosswalk without NDC should fail."""
        df = pl.DataFrame({"HCPCS Code": ["J0135"]})

        result = validate_crosswalk_schema(df)

        assert result.is_valid is False
        assert "NDC" in result.missing_columns

    def test_missing_hcpcs_fails(self) -> None:
        """Crosswalk without HCPCS Code should fail."""
        df = pl.DataFrame({"NDC": ["1234567890"]})

        result = validate_crosswalk_schema(df)

        assert result.is_valid is False
        assert "HCPCS Code" in result.missing_columns


class TestCrosswalkIntegrity:
    """Tests for crosswalk integrity (match rate) validation."""

    def test_high_match_rate_passes(self) -> None:
        """Match rate above threshold should pass."""
        catalog = pl.DataFrame({"NDC": [f"{i:011d}" for i in range(100)]})
        crosswalk = pl.DataFrame(
            {
                "NDC": [f"{i:011d}" for i in range(96)],  # 96% match
                "HCPCS Code": [f"J{i:04d}" for i in range(96)],
            }
        )

        result = validate_crosswalk_integrity(catalog, crosswalk, min_match_rate=0.95)

        assert result.is_valid is True
        assert "96" in result.message or "0.96" in result.message

    def test_low_match_rate_fails(self) -> None:
        """Match rate below threshold should fail."""
        catalog = pl.DataFrame({"NDC": [f"{i:011d}" for i in range(100)]})
        crosswalk = pl.DataFrame(
            {
                "NDC": [f"{i:011d}" for i in range(50)],  # 50% match
                "HCPCS Code": [f"J{i:04d}" for i in range(50)],
            }
        )

        result = validate_crosswalk_integrity(catalog, crosswalk, min_match_rate=0.95)

        assert result.is_valid is False
        assert "50" in result.message or "below" in result.message.lower()

    def test_custom_threshold(self) -> None:
        """Should respect custom match rate threshold."""
        catalog = pl.DataFrame({"NDC": [f"{i:011d}" for i in range(100)]})
        crosswalk = pl.DataFrame(
            {
                "NDC": [f"{i:011d}" for i in range(80)],
                "HCPCS Code": [f"J{i:04d}" for i in range(80)],
            }
        )

        # Should pass with 75% threshold
        result = validate_crosswalk_integrity(catalog, crosswalk, min_match_rate=0.75)
        assert result.is_valid is True

        # Should fail with 90% threshold
        result = validate_crosswalk_integrity(catalog, crosswalk, min_match_rate=0.90)
        assert result.is_valid is False


class TestTop50DrugsPricing:
    """Tests for Top 50 drug pricing validation (risk mitigation)."""

    def test_all_drugs_present_passes(self) -> None:
        """Should pass when most Top 50 drugs have complete pricing."""
        # Create catalog with most Top 50 drugs
        drugs = TOP_50_DRUG_NAMES[:48]  # 96% present
        df = pl.DataFrame(
            {
                "Drug Name": drugs,
                "NDC": [f"{i:011d}" for i in range(len(drugs))],
                "Contract Cost": [100.0] * len(drugs),
                "AWP": [500.0] * len(drugs),
            }
        )

        result = validate_top_drugs_pricing(df)

        assert result.is_valid is True

    def test_too_many_missing_fails(self) -> None:
        """Should fail when >5% of Top 50 drugs are missing."""
        # Create catalog with only a few Top 50 drugs
        drugs = TOP_50_DRUG_NAMES[:10]  # Only 20% present = 80% missing
        df = pl.DataFrame(
            {
                "Drug Name": drugs,
                "NDC": [f"{i:011d}" for i in range(len(drugs))],
                "Contract Cost": [100.0] * len(drugs),
                "AWP": [500.0] * len(drugs),
            }
        )

        result = validate_top_drugs_pricing(df, max_missing_pct=0.05)

        assert result.is_valid is False
        assert "missing" in result.message.lower() or "WARNING" in result.message

    def test_warns_on_incomplete_pricing(self) -> None:
        """Should warn when drugs have zero/null pricing."""
        drugs = TOP_50_DRUG_NAMES[:48]
        contract_costs = [100.0] * 45 + [0.0] * 3  # 3 with zero cost
        df = pl.DataFrame(
            {
                "Drug Name": drugs,
                "NDC": [f"{i:011d}" for i in range(len(drugs))],
                "Contract Cost": contract_costs,
                "AWP": [500.0] * len(drugs),
            }
        )

        result = validate_top_drugs_pricing(df)

        # Should have warnings about incomplete pricing
        assert len(result.warnings) > 0 or not result.is_valid

    def test_handles_missing_drug_name_column(self) -> None:
        """Should handle gracefully when Drug Name column is missing."""
        df = pl.DataFrame(
            {
                "NDC": ["123", "456"],
                "Contract Cost": [100, 200],
            }
        )

        result = validate_top_drugs_pricing(df)

        # Should pass with warning, not fail
        assert result.is_valid is True
        assert len(result.warnings) > 0

    def test_case_insensitive_matching(self) -> None:
        """Should match drug names case-insensitively."""
        df = pl.DataFrame(
            {
                "Drug Name": ["humira", "ENBREL", "Stelara"],  # Mixed case
                "NDC": ["1", "2", "3"],
                "Contract Cost": [100.0, 100.0, 100.0],
                "AWP": [500.0, 500.0, 500.0],
            }
        )

        result = validate_top_drugs_pricing(df)

        # Should find all 3 drugs despite case differences
        assert "3" in result.message or result.is_valid


class TestNADACValidation:
    """Tests for NADAC statistics file validation."""

    def test_valid_nadac_passes(self, sample_nadac_df: pl.DataFrame) -> None:
        """Valid NADAC file should pass."""
        result = validate_nadac_schema(sample_nadac_df)

        assert result.is_valid is True
        assert result.row_count == 3

    def test_missing_ndc_fails(self) -> None:
        """NADAC without ndc column should fail."""
        df = pl.DataFrame({"total_discount_340b_pct": [50.0]})

        result = validate_nadac_schema(df)

        assert result.is_valid is False
        assert "ndc" in result.missing_columns

    def test_missing_discount_pct_fails(self) -> None:
        """NADAC without discount column should fail."""
        df = pl.DataFrame({"ndc": ["1234567890"]})

        result = validate_nadac_schema(df)

        assert result.is_valid is False
        assert "total_discount_340b_pct" in result.missing_columns
