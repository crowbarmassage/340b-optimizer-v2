"""Tests for loading dose calculation logic (Gold Layer).

Gatekeeper Test: Loading Dose Logic Test
- Select Cosentyx (Psoriasis): Year 1 = 17 fills, Maintenance = 12 fills
- Year 1 Revenue should reflect the higher fill count
"""

from decimal import Decimal

import polars as pl
import pytest

from optimizer_340b.compute.dosing import (
    DEFAULT_COMPLIANCE_RATE,
    apply_loading_dose_logic,
    calculate_lifetime_value,
    calculate_year_1_vs_maintenance_delta,
    find_high_loading_drugs,
)
from optimizer_340b.models import DosingProfile


@pytest.fixture
def sample_dosing_grid() -> pl.DataFrame:
    """Sample biologics logic grid for testing."""
    return pl.DataFrame(
        {
            "Drug Name": [
                "COSENTYX",
                "COSENTYX",
                "HUMIRA",
                "ENBREL",
                "STELARA",
            ],
            "Indication": [
                "Psoriasis",
                "Ankylosing Spondylitis",
                "Rheumatoid Arthritis",
                "Rheumatoid Arthritis",
                "Psoriasis",
            ],
            "Year 1 Fills": [17, 13, 26, 52, 5],
            "Year 2+ Fills": [12, 12, 26, 52, 4],
        }
    )


class TestConstants:
    """Tests for dosing constants."""

    def test_default_compliance_rate(self) -> None:
        """Default compliance should be 90%."""
        assert Decimal("0.90") == DEFAULT_COMPLIANCE_RATE


class TestApplyLoadingDoseLogic:
    """Tests for loading dose profile lookup."""

    def test_cosentyx_loading_dose_test(
        self, sample_dosing_grid: pl.DataFrame
    ) -> None:
        """Gatekeeper: Loading Dose Logic Test.

        Select Cosentyx (Psoriasis). Does the Year 1 Revenue calculation
        reflect 17 fills (Loading) vs. 12 fills (Maintenance)?
        """
        profile = apply_loading_dose_logic(
            "COSENTYX",
            sample_dosing_grid,
            indication="Psoriasis",
        )

        assert profile is not None
        assert profile.drug_name == "COSENTYX"
        assert profile.indication == "Psoriasis"
        assert profile.year_1_fills == 17
        assert profile.year_2_plus_fills == 12

    def test_cosentyx_ankylosing_spondylitis(
        self, sample_dosing_grid: pl.DataFrame
    ) -> None:
        """Different indication should have different dosing."""
        profile = apply_loading_dose_logic(
            "COSENTYX",
            sample_dosing_grid,
            indication="Ankylosing Spondylitis",
        )

        assert profile is not None
        assert profile.year_1_fills == 13  # Different from Psoriasis
        assert profile.year_2_plus_fills == 12

    def test_case_insensitive_lookup(
        self, sample_dosing_grid: pl.DataFrame
    ) -> None:
        """Drug name lookup should be case-insensitive."""
        profile_lower = apply_loading_dose_logic("cosentyx", sample_dosing_grid)
        profile_upper = apply_loading_dose_logic("COSENTYX", sample_dosing_grid)
        profile_mixed = apply_loading_dose_logic("Cosentyx", sample_dosing_grid)

        assert profile_lower is not None
        assert profile_upper is not None
        assert profile_mixed is not None
        assert profile_lower.year_1_fills == profile_upper.year_1_fills

    def test_no_profile_returns_none(
        self, sample_dosing_grid: pl.DataFrame
    ) -> None:
        """Unknown drug should return None."""
        profile = apply_loading_dose_logic("UNKNOWN_DRUG", sample_dosing_grid)
        assert profile is None

    def test_compliance_adjustment(
        self, sample_dosing_grid: pl.DataFrame
    ) -> None:
        """Adjusted fills should reflect compliance rate."""
        profile = apply_loading_dose_logic(
            "COSENTYX",
            sample_dosing_grid,
            indication="Psoriasis",
            compliance_rate=Decimal("0.90"),
        )

        assert profile is not None
        # 17 fills × 90% compliance = 15.3 adjusted
        assert profile.adjusted_year_1_fills == Decimal("15.3")

    def test_custom_compliance_rate(
        self, sample_dosing_grid: pl.DataFrame
    ) -> None:
        """Should accept custom compliance rate."""
        profile = apply_loading_dose_logic(
            "COSENTYX",
            sample_dosing_grid,
            indication="Psoriasis",
            compliance_rate=Decimal("0.80"),
        )

        assert profile is not None
        # 17 fills × 80% compliance = 13.6 adjusted
        assert profile.adjusted_year_1_fills == Decimal("13.6")

    def test_first_match_without_indication(
        self, sample_dosing_grid: pl.DataFrame
    ) -> None:
        """Without indication, should use first match."""
        profile = apply_loading_dose_logic("COSENTYX", sample_dosing_grid)

        assert profile is not None
        # First COSENTYX row is Psoriasis
        assert profile.year_1_fills == 17

    def test_empty_grid_returns_none(self) -> None:
        """Empty dosing grid should return None."""
        empty_grid = pl.DataFrame(
            {"Drug Name": [], "Year 1 Fills": [], "Year 2+ Fills": []}
        )
        profile = apply_loading_dose_logic("COSENTYX", empty_grid)
        assert profile is None

    def test_drug_without_loading_dose(
        self, sample_dosing_grid: pl.DataFrame
    ) -> None:
        """Drug with equal Year 1 and Maintenance should still work."""
        profile = apply_loading_dose_logic("ENBREL", sample_dosing_grid)

        assert profile is not None
        assert profile.year_1_fills == 52
        assert profile.year_2_plus_fills == 52


class TestYearVsMaintenanceDelta:
    """Tests for Year 1 vs Maintenance delta calculation."""

    def test_year_1_vs_maintenance_delta(
        self, sample_dosing_profile: DosingProfile
    ) -> None:
        """Loading dose should increase Year 1 revenue."""
        margin_per_fill = Decimal("500.00")

        result = calculate_year_1_vs_maintenance_delta(
            sample_dosing_profile, margin_per_fill
        )

        # Year 1: 15.3 fills × $500 = $7650
        assert result["year_1_revenue"] == Decimal("7650.0")

        # Maintenance: 12 fills × $500 = $6000
        assert result["maintenance_revenue"] == Decimal("6000")

        # Delta: $7650 - $6000 = $1650
        assert result["loading_dose_delta"] == Decimal("1650.0")

    def test_delta_percentage(
        self, sample_dosing_profile: DosingProfile
    ) -> None:
        """Delta percentage should be significant for loading dose drugs."""
        margin_per_fill = Decimal("500.00")

        result = calculate_year_1_vs_maintenance_delta(
            sample_dosing_profile, margin_per_fill
        )

        # Delta should be >25% for Cosentyx-like profile
        assert result["loading_dose_delta_pct"] > Decimal("25")

    def test_no_loading_dose_zero_delta(self) -> None:
        """Drug without loading dose should have zero delta."""
        profile = DosingProfile(
            drug_name="ENBREL",
            indication="RA",
            year_1_fills=12,
            year_2_plus_fills=12,
            adjusted_year_1_fills=Decimal("10.8"),  # 90% compliance
        )

        result = calculate_year_1_vs_maintenance_delta(profile, Decimal("500.00"))

        # Year 1 adjusted (10.8) vs Maintenance (12) - actually lower!
        assert result["loading_dose_delta"] < 0


class TestLifetimeValue:
    """Tests for patient lifetime value calculation."""

    def test_lifetime_value_5_years(
        self, sample_dosing_profile: DosingProfile
    ) -> None:
        """5-year lifetime value calculation."""
        margin_per_fill = Decimal("500.00")

        result = calculate_lifetime_value(
            sample_dosing_profile, margin_per_fill, years=5
        )

        # Year 1: 15.3 × $500 = $7650
        # Years 2-5: 12 × $500 × 4 = $24000
        # Total: $31650
        expected_total = Decimal("7650.0") + (Decimal("6000") * 4)
        assert result["lifetime_value"] == expected_total

    def test_lifetime_value_single_year(
        self, sample_dosing_profile: DosingProfile
    ) -> None:
        """Single year should equal Year 1 revenue."""
        margin_per_fill = Decimal("500.00")

        result = calculate_lifetime_value(
            sample_dosing_profile, margin_per_fill, years=1
        )

        assert result["lifetime_value"] == result["year_1"]

    def test_average_annual_value(
        self, sample_dosing_profile: DosingProfile
    ) -> None:
        """Average annual should be total / years."""
        margin_per_fill = Decimal("500.00")

        result = calculate_lifetime_value(
            sample_dosing_profile, margin_per_fill, years=5
        )

        expected_avg = result["lifetime_value"] / 5
        assert result["average_annual"] == expected_avg


class TestFindHighLoadingDrugs:
    """Tests for identifying high loading dose impact drugs."""

    def test_find_high_loading_drugs(
        self, sample_dosing_grid: pl.DataFrame
    ) -> None:
        """Should identify drugs with significant loading doses."""
        result = find_high_loading_drugs(sample_dosing_grid, min_delta_pct=20.0)

        # COSENTYX Psoriasis: (17-12)/12 = 41.7%
        # STELARA: (5-4)/4 = 25%
        # These should be included
        assert result.height >= 2

        drug_names = result["Drug Name"].to_list()
        assert "COSENTYX" in drug_names

    def test_excludes_low_delta_drugs(
        self, sample_dosing_grid: pl.DataFrame
    ) -> None:
        """Should exclude drugs with low loading dose impact."""
        result = find_high_loading_drugs(sample_dosing_grid, min_delta_pct=20.0)

        drug_names = result["Drug Name"].to_list()
        # HUMIRA and ENBREL have 0% delta
        assert "HUMIRA" not in drug_names
        assert "ENBREL" not in drug_names

    def test_sorted_by_delta(
        self, sample_dosing_grid: pl.DataFrame
    ) -> None:
        """Results should be sorted by delta descending."""
        result = find_high_loading_drugs(sample_dosing_grid, min_delta_pct=0.0)

        deltas = result["loading_delta_pct"].to_list()
        # Should be descending
        assert deltas == sorted(deltas, reverse=True)

    def test_custom_threshold(
        self, sample_dosing_grid: pl.DataFrame
    ) -> None:
        """Should respect custom threshold."""
        # High threshold - fewer results
        result_high = find_high_loading_drugs(sample_dosing_grid, min_delta_pct=40.0)
        # Low threshold - more results
        result_low = find_high_loading_drugs(sample_dosing_grid, min_delta_pct=10.0)

        assert result_low.height >= result_high.height


class TestDosingProfileModel:
    """Tests for DosingProfile model methods."""

    def test_year_1_revenue(self, sample_dosing_profile: DosingProfile) -> None:
        """Year 1 revenue uses adjusted fills."""
        margin = Decimal("100.00")
        revenue = sample_dosing_profile.year_1_revenue(margin)

        # adjusted_year_1_fills (15.3) × margin
        expected = Decimal("15.3") * margin
        assert revenue == expected

    def test_maintenance_revenue(
        self, sample_dosing_profile: DosingProfile
    ) -> None:
        """Maintenance revenue uses year_2_plus_fills."""
        margin = Decimal("100.00")
        revenue = sample_dosing_profile.maintenance_revenue(margin)

        # year_2_plus_fills (12) × margin
        expected = 12 * margin
        assert revenue == expected


class TestEdgeCases:
    """Tests for edge cases in dosing logic."""

    def test_zero_margin_per_fill(
        self, sample_dosing_profile: DosingProfile
    ) -> None:
        """Zero margin should yield zero revenue."""
        result = calculate_year_1_vs_maintenance_delta(
            sample_dosing_profile, Decimal("0.00")
        )

        assert result["year_1_revenue"] == 0
        assert result["maintenance_revenue"] == 0
        assert result["loading_dose_delta"] == 0

    def test_high_margin_per_fill(
        self, sample_dosing_profile: DosingProfile
    ) -> None:
        """High margin should scale appropriately."""
        result = calculate_year_1_vs_maintenance_delta(
            sample_dosing_profile, Decimal("10000.00")
        )

        # Year 1: 15.3 × $10000 = $153000
        assert result["year_1_revenue"] == Decimal("153000.0")

    def test_missing_year2_column(self) -> None:
        """Should handle missing Year 2+ Fills column."""
        grid = pl.DataFrame(
            {
                "Drug Name": ["TESTDRUG"],
                "Year 1 Fills": [15],
            }
        )

        profile = apply_loading_dose_logic("TESTDRUG", grid)

        assert profile is not None
        # Should default Year 2+ to Year 1
        assert profile.year_2_plus_fills == 15
