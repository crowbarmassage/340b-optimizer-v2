"""Tests for data normalization (Silver Layer)."""

import polars as pl
import pytest

from optimizer_340b.ingest.normalizers import (
    apply_column_mapping,
    build_silver_dataset,
    fuzzy_match_drug_name,
    fuzzy_match_drug_partial,
    join_asp_pricing,
    join_catalog_to_crosswalk,
    normalize_asp_pricing,
    normalize_catalog,
    normalize_crosswalk,
    normalize_ndc,
    normalize_ndc_column,
)


class TestNDCNormalization:
    """Tests for NDC normalization to 11-digit format."""

    @pytest.mark.parametrize(
        "input_ndc,expected",
        [
            ("0074-4339-02", "00074433902"),  # Standard with dashes -> 11 digits
            ("12345678901", "12345678901"),  # 11-digit preserved as-is
            ("1234567890", "01234567890"),  # 10-digit padded to 11
            ("12345", "00000012345"),  # Short NDC zero-padded to 11
            ("0012345", "00000012345"),  # Leading zeros preserved, padded to 11
            ("00074-4339-02", "00074433902"),  # 11 digits with dashes preserved
            ("", "00000000000"),  # Empty string -> 11 zeros
            ("abc123def", "00000000123"),  # Non-numeric chars removed, padded to 11
        ],
    )
    def test_normalize_ndc(self, input_ndc: str, expected: str) -> None:
        """NDC normalization should produce 11-digit format."""
        result = normalize_ndc(input_ndc)
        assert result == expected
        assert len(result) == 11

    def test_normalize_ndc_none(self) -> None:
        """None input should return empty normalized string."""
        result = normalize_ndc(None)  # type: ignore[arg-type]
        assert result == ""

    def test_normalize_ndc_column(self) -> None:
        """Column normalization should apply to all rows with 11-digit format."""
        df = pl.DataFrame({"NDC": ["0074-4339-02", "12345", "1234567890"]})

        result = normalize_ndc_column(df)

        expected = ["00074433902", "00000012345", "01234567890"]
        assert result["ndc_normalized"].to_list() == expected
        # Verify all are 11 digits
        for ndc in result["ndc_normalized"].to_list():
            assert len(ndc) == 11

    def test_normalize_ndc_column_missing_column(self) -> None:
        """Missing NDC column should return unchanged DataFrame."""
        df = pl.DataFrame({"Other": ["A", "B"]})

        result = normalize_ndc_column(df, ndc_column="NDC")

        assert "ndc_normalized" not in result.columns
        assert result.height == 2


class TestColumnMapping:
    """Tests for column mapping/renaming."""

    def test_apply_column_mapping(self) -> None:
        """Should rename columns according to mapping."""
        df = pl.DataFrame(
            {
                "Medispan AWP": [100, 200],
                "Trade Name": ["HUMIRA", "ENBREL"],
                "Other": [1, 2],
            }
        )
        mapping = {
            "Medispan AWP": "AWP",
            "Trade Name": "Drug Name",
            "Missing": "WontRename",
        }

        result = apply_column_mapping(df, mapping)

        assert "AWP" in result.columns
        assert "Drug Name" in result.columns
        assert "Medispan AWP" not in result.columns
        assert "Trade Name" not in result.columns
        assert "Other" in result.columns  # Unmapped columns preserved

    def test_apply_column_mapping_empty(self) -> None:
        """Empty mapping should return unchanged DataFrame."""
        df = pl.DataFrame({"A": [1], "B": [2]})

        result = apply_column_mapping(df, {})

        assert result.columns == ["A", "B"]


class TestCatalogNormalization:
    """Tests for catalog normalization."""

    def test_normalize_catalog_basic(self, sample_catalog_df: pl.DataFrame) -> None:
        """Basic catalog normalization should add NDC and preserve columns."""
        result = normalize_catalog(sample_catalog_df)

        assert "ndc_normalized" in result.columns
        assert result.height == 3

    def test_normalize_catalog_renames_medispan_awp(self) -> None:
        """Should rename 'Medispan AWP' to 'AWP'."""
        df = pl.DataFrame(
            {
                "NDC": ["1234567890"],
                "Medispan AWP": [500.0],
                "Contract Cost": [100.0],
            }
        )

        result = normalize_catalog(df)

        assert "AWP" in result.columns
        assert "Medispan AWP" not in result.columns
        assert result["AWP"][0] == 500.0

    def test_normalize_catalog_derives_drug_name(self) -> None:
        """Should derive Drug Name from Trade Name if not present."""
        df = pl.DataFrame(
            {
                "NDC": ["1234567890"],
                "Trade Name": ["HUMIRA PEN"],
                "Contract Cost": [100.0],
                "AWP": [500.0],
            }
        )

        result = normalize_catalog(df)

        assert "Drug Name" in result.columns
        assert result["Drug Name"][0] == "HUMIRA PEN"


class TestCrosswalkNormalization:
    """Tests for crosswalk normalization."""

    def test_normalize_crosswalk_column_mapping(self) -> None:
        """Should rename crosswalk columns to standard names."""
        df = pl.DataFrame(
            {
                "_2025_CODE": ["J0135"],
                "NDC2": ["0074433902"],
                "LABELER NAME": ["ABBVIE"],
            }
        )

        result = normalize_crosswalk(df)

        assert "HCPCS Code" in result.columns
        assert "NDC" in result.columns
        assert "Labeler Name" in result.columns
        assert result["HCPCS Code"][0] == "J0135"

    def test_normalize_crosswalk_adds_ndc_normalized(self) -> None:
        """Should add normalized NDC column."""
        df = pl.DataFrame(
            {
                "NDC": ["0074-4339-02"],
                "HCPCS Code": ["J0135"],
            }
        )

        result = normalize_crosswalk(df)

        assert "ndc_normalized" in result.columns
        assert result["ndc_normalized"][0] == "00074433902"
        assert len(result["ndc_normalized"][0]) == 11


class TestASPPricingNormalization:
    """Tests for ASP pricing normalization."""

    def test_normalize_asp_pricing_basic(
        self, sample_asp_pricing_df: pl.DataFrame
    ) -> None:
        """Basic ASP normalization should work."""
        result = normalize_asp_pricing(sample_asp_pricing_df)

        assert "HCPCS Code" in result.columns
        assert "Payment Limit" in result.columns

    def test_normalize_asp_pricing_casts_payment_limit(self) -> None:
        """Should cast Payment Limit to float."""
        df = pl.DataFrame(
            {
                "HCPCS Code": ["J0135"],
                "Payment Limit": ["123.45"],  # String
            }
        )

        result = normalize_asp_pricing(df)

        assert result["Payment Limit"].dtype == pl.Float64
        assert result["Payment Limit"][0] == 123.45


class TestFuzzyMatching:
    """Tests for fuzzy drug name matching."""

    def test_exact_match_returns_candidate(self) -> None:
        """Exact match should return the candidate."""
        result = fuzzy_match_drug_name(
            "HUMIRA", ["HUMIRA", "ENBREL", "STELARA"], threshold=80
        )
        assert result == "HUMIRA"

    def test_close_match_returns_candidate(self) -> None:
        """Close match should return best candidate above threshold."""
        result = fuzzy_match_drug_name(
            "HUMIRA PEN", ["HUMIRA", "ENBREL", "STELARA"], threshold=60
        )
        assert result == "HUMIRA"

    def test_no_match_returns_none(self) -> None:
        """No match above threshold should return None."""
        result = fuzzy_match_drug_name(
            "COMPLETELY DIFFERENT", ["HUMIRA", "ENBREL"], threshold=80
        )
        assert result is None

    def test_case_insensitive(self) -> None:
        """Matching should be case-insensitive."""
        result = fuzzy_match_drug_name("humira", ["HUMIRA", "ENBREL"], threshold=80)
        assert result == "HUMIRA"

    def test_empty_inputs(self) -> None:
        """Empty inputs should return None."""
        assert fuzzy_match_drug_name("", ["HUMIRA"], threshold=80) is None
        assert fuzzy_match_drug_name("HUMIRA", [], threshold=80) is None

    def test_partial_match(self) -> None:
        """Partial matching should find substrings."""
        result = fuzzy_match_drug_partial(
            "HUMIRA", ["HUMIRA 40MG/0.8ML PEN", "ENBREL"], threshold=70
        )
        assert result == "HUMIRA 40MG/0.8ML PEN"


class TestCrosswalkJoin:
    """Tests for crosswalk join integrity."""

    def test_crosswalk_join_matches_correctly(
        self,
        sample_catalog_df: pl.DataFrame,
        sample_asp_crosswalk_df: pl.DataFrame,
    ) -> None:
        """Crosswalk join should match NDCs to HCPCS codes."""
        # Normalize both DataFrames
        catalog = normalize_catalog(sample_catalog_df)
        crosswalk = normalize_crosswalk(sample_asp_crosswalk_df)

        matched, orphans = join_catalog_to_crosswalk(catalog, crosswalk)

        # 2 of 3 catalog items should match (HUMIRA, ENBREL have crosswalk entries)
        assert matched.height == 2
        assert orphans.height == 1

    def test_crosswalk_join_returns_hcpcs(
        self,
        sample_catalog_df: pl.DataFrame,
        sample_asp_crosswalk_df: pl.DataFrame,
    ) -> None:
        """Joined result should contain HCPCS codes."""
        catalog = normalize_catalog(sample_catalog_df)
        crosswalk = normalize_crosswalk(sample_asp_crosswalk_df)

        matched, _ = join_catalog_to_crosswalk(catalog, crosswalk)

        assert "HCPCS Code" in matched.columns
        hcpcs_codes = matched["HCPCS Code"].to_list()
        assert "J0135" in hcpcs_codes  # HUMIRA
        assert "J1438" in hcpcs_codes  # ENBREL

    def test_crosswalk_integrity_rate(self) -> None:
        """Crosswalk should have >95% match rate for infusible drugs."""
        # Create test data with 100 infusible drugs, 96 with crosswalk matches
        catalog = pl.DataFrame(
            {
                "NDC": [f"{i:011d}" for i in range(100)],
            }
        )
        catalog = normalize_ndc_column(catalog, "NDC")

        crosswalk = pl.DataFrame(
            {
                "NDC": [f"{i:011d}" for i in range(96)],
                "HCPCS Code": [f"J{i:04d}" for i in range(96)],
            }
        )
        crosswalk = normalize_ndc_column(crosswalk, "NDC")

        matched, orphans = join_catalog_to_crosswalk(catalog, crosswalk)

        match_rate = matched.height / catalog.height * 100
        assert match_rate >= 95, f"Match rate {match_rate}% below 95% threshold"


class TestASPPricingJoin:
    """Tests for ASP pricing join."""

    def test_join_asp_pricing_basic(self) -> None:
        """Should join ASP pricing by HCPCS code."""
        joined = pl.DataFrame(
            {
                "NDC": ["0074433902"],
                "HCPCS Code": ["J0135"],
                "Drug Name": ["HUMIRA"],
            }
        )
        asp = pl.DataFrame(
            {
                "HCPCS Code": ["J0135", "J1438"],
                "Payment Limit": [2800.0, 3200.0],
            }
        )

        result = join_asp_pricing(joined, asp)

        assert "ASP" in result.columns
        assert result["ASP"][0] == 2800.0

    def test_join_asp_pricing_missing_hcpcs(self) -> None:
        """Should handle missing HCPCS gracefully."""
        joined = pl.DataFrame(
            {
                "NDC": ["0074433902"],
                "HCPCS Code": ["J9999"],  # Not in ASP
                "Drug Name": ["UNKNOWN"],
            }
        )
        asp = pl.DataFrame(
            {
                "HCPCS Code": ["J0135"],
                "Payment Limit": [2800.0],
            }
        )

        result = join_asp_pricing(joined, asp)

        assert "ASP" in result.columns
        assert result["ASP"][0] is None


class TestBuildSilverDataset:
    """Tests for complete Silver Layer pipeline."""

    def test_build_silver_dataset(
        self,
        sample_catalog_df: pl.DataFrame,
        sample_asp_crosswalk_df: pl.DataFrame,
        sample_asp_pricing_df: pl.DataFrame,
    ) -> None:
        """Should build complete Silver dataset with all joins."""
        silver, orphans = build_silver_dataset(
            sample_catalog_df,
            sample_asp_crosswalk_df,
            sample_asp_pricing_df,
        )

        # Should have matched rows with ASP pricing
        assert silver.height == 2  # HUMIRA and ENBREL match
        assert orphans.height == 1  # STELARA is orphan

        # Silver should have all key columns
        assert "ndc_normalized" in silver.columns
        assert "HCPCS Code" in silver.columns
        assert "ASP" in silver.columns

    def test_build_silver_dataset_preserves_catalog_columns(
        self,
        sample_catalog_df: pl.DataFrame,
        sample_asp_crosswalk_df: pl.DataFrame,
        sample_asp_pricing_df: pl.DataFrame,
    ) -> None:
        """Silver dataset should preserve original catalog columns."""
        silver, _ = build_silver_dataset(
            sample_catalog_df,
            sample_asp_crosswalk_df,
            sample_asp_pricing_df,
        )

        # Original catalog columns should be preserved
        assert "NDC" in silver.columns
        assert "Contract Cost" in silver.columns
        assert "AWP" in silver.columns
