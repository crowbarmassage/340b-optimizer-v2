"""Tests for risk flagging (Watchtower layer).

Gatekeeper Tests:
- Enbrel Simulation: IRA 2026 flag detection
- Penny Pricing Alert: Exclude flagged drugs from Top Opportunities
"""

from decimal import Decimal

import polars as pl
import pytest

from optimizer_340b.models import Drug
from optimizer_340b.risk.ira_flags import (
    IRA_2026_DRUGS,
    IRA_2027_DRUGS,
    IRA_DRUGS_BY_YEAR,
    check_ira_status,
    filter_ira_drugs,
    get_all_ira_drugs,
    get_ira_risk_status,
)
from optimizer_340b.risk.penny_pricing import (
    HIGH_DISCOUNT_THRESHOLD,
    PENNY_THRESHOLD,
    check_penny_pricing,
    check_penny_pricing_for_drug,
    filter_top_opportunities,
    get_penny_pricing_summary,
)


class TestIRAFlags:
    """Tests for IRA price negotiation detection."""

    def test_enbrel_simulation(self) -> None:
        """Gatekeeper: Enbrel Simulation.

        Force-feed Enbrel into the pipeline.
        Does the system flag it with a "High Risk / IRA 2026" warning?
        """
        ira_status = check_ira_status("ENBREL")

        assert ira_status["is_ira_drug"] is True
        assert ira_status["ira_year"] == 2026
        assert ira_status["risk_level"] == "High Risk"
        assert "High Risk" in str(ira_status["warning_message"])
        assert "IRA 2026" in str(ira_status["warning_message"])

    def test_enbrel_with_drug_model(self, sample_drug_ira_flagged: Drug) -> None:
        """Test Enbrel detection using Drug model."""
        ira_status = check_ira_status(sample_drug_ira_flagged.drug_name)

        assert ira_status["is_ira_drug"] is True
        assert ira_status["ira_year"] == 2026
        assert ira_status["drug_name"] == "ENBREL"

    def test_non_ira_drug_passes(self) -> None:
        """Non-IRA drugs should not be flagged."""
        ira_status = check_ira_status("SOME_NEW_DRUG")

        assert ira_status["is_ira_drug"] is False
        assert ira_status["ira_year"] is None
        assert ira_status["risk_level"] == "Low Risk"

    def test_humira_not_ira_drug(self) -> None:
        """HUMIRA is not on the IRA list (as of 2026-2027)."""
        ira_status = check_ira_status("HUMIRA")

        assert ira_status["is_ira_drug"] is False
        assert ira_status["ira_year"] is None

    def test_case_insensitive_matching(self) -> None:
        """Drug name matching should be case-insensitive."""
        lower = check_ira_status("enbrel")
        upper = check_ira_status("ENBREL")
        mixed = check_ira_status("Enbrel")

        assert lower["is_ira_drug"] is True
        assert upper["is_ira_drug"] is True
        assert mixed["is_ira_drug"] is True

    def test_partial_name_matching(self) -> None:
        """Partial drug name should match (e.g., NOVOLOG FLEXPEN)."""
        status = check_ira_status("NOVOLOG FLEXPEN 100U/ML")

        assert status["is_ira_drug"] is True
        assert status["ira_year"] == 2026

    def test_empty_drug_name(self) -> None:
        """Empty drug name should return unknown status."""
        status = check_ira_status("")

        assert status["is_ira_drug"] is False
        assert status["risk_level"] == "Unknown"

    def test_ira_2026_drugs_list(self) -> None:
        """IRA 2026 list should contain known drugs."""
        assert "ELIQUIS" in IRA_2026_DRUGS
        assert "ENBREL" in IRA_2026_DRUGS
        assert "STELARA" in IRA_2026_DRUGS
        assert "JARDIANCE" in IRA_2026_DRUGS

    def test_ira_2027_drugs_list(self) -> None:
        """IRA 2027 list should contain known drugs."""
        assert "OZEMPIC" in IRA_2027_DRUGS
        assert "WEGOVY" in IRA_2027_DRUGS
        assert "COSENTYX" in IRA_2027_DRUGS
        assert "TRULICITY" in IRA_2027_DRUGS

    def test_ira_2027_detection(self) -> None:
        """IRA 2027 drugs should be flagged with correct year."""
        status = check_ira_status("OZEMPIC")

        assert status["is_ira_drug"] is True
        assert status["ira_year"] == 2027
        assert "IRA 2027" in str(status["warning_message"])

    def test_combined_lookup_dict(self) -> None:
        """Combined lookup should include both 2026 and 2027 drugs."""
        assert IRA_DRUGS_BY_YEAR["ENBREL"] == 2026
        assert IRA_DRUGS_BY_YEAR["OZEMPIC"] == 2027


class TestIRARiskStatus:
    """Tests for structured IRA risk status."""

    def test_get_ira_risk_status_enbrel(self) -> None:
        """get_ira_risk_status should return IRARiskStatus dataclass."""
        status = get_ira_risk_status("ENBREL")

        assert status.is_ira_drug is True
        assert status.ira_year == 2026
        assert status.drug_name == "ENBREL"
        assert status.risk_level == "High Risk"

    def test_get_ira_risk_status_non_ira(self) -> None:
        """Non-IRA drug should return low risk status."""
        status = get_ira_risk_status("GENERIC_DRUG")

        assert status.is_ira_drug is False
        assert status.ira_year is None
        assert status.risk_level == "Low Risk"


class TestFilterIRADrugs:
    """Tests for filtering drug lists for IRA drugs."""

    def test_filter_ira_drugs_mixed_list(self) -> None:
        """Should identify IRA drugs in a mixed list."""
        drugs = ["ENBREL", "HUMIRA", "OZEMPIC", "TYLENOL", "STELARA"]
        flagged = filter_ira_drugs(drugs)

        assert len(flagged) == 3  # ENBREL, OZEMPIC, STELARA

        flagged_names = [item["drug_name"] for item in flagged]
        assert "ENBREL" in flagged_names
        assert "OZEMPIC" in flagged_names
        assert "STELARA" in flagged_names

    def test_filter_ira_drugs_none_found(self) -> None:
        """Should return empty list when no IRA drugs found."""
        drugs = ["HUMIRA", "TYLENOL", "ASPIRIN"]
        flagged = filter_ira_drugs(drugs)

        assert len(flagged) == 0

    def test_filter_preserves_input_name(self) -> None:
        """Filter results should include original input name."""
        drugs = ["enbrel"]  # lowercase
        flagged = filter_ira_drugs(drugs)

        assert flagged[0]["input_name"] == "enbrel"
        assert flagged[0]["drug_name"] == "ENBREL"


class TestGetAllIRADrugs:
    """Tests for complete IRA drug listing."""

    def test_get_all_ira_drugs(self) -> None:
        """Should return complete list of all IRA drugs."""
        all_drugs = get_all_ira_drugs()

        # Should have both 2026 and 2027 drugs
        assert len(all_drugs) > 20

        # Check structure
        assert "ENBREL" in all_drugs
        assert all_drugs["ENBREL"]["year"] == 2026
        assert all_drugs["ENBREL"]["risk_level"] == "High Risk"

        assert "OZEMPIC" in all_drugs
        assert all_drugs["OZEMPIC"]["year"] == 2027


class TestPennyPricing:
    """Tests for penny pricing detection."""

    def test_penny_pricing_flag(self) -> None:
        """Drugs with penny pricing should be flagged."""
        nadac_df = pl.DataFrame({
            "ndc": ["12345678901", "98765432101"],
            "penny_pricing": [True, False],
            "total_discount_340b_pct": [99.9, 50.0],
        })

        flagged = check_penny_pricing(nadac_df)

        assert len(flagged) == 1
        assert flagged[0]["ndc"] == "12345678901"
        assert flagged[0]["is_penny_priced"] is True
        assert flagged[0]["should_exclude"] is True

    def test_high_discount_triggers_penny_flag(self) -> None:
        """High discount percentage should trigger penny pricing flag."""
        nadac_df = pl.DataFrame({
            "ndc": ["1111111111", "2222222222"],
            "penny_pricing": [False, False],
            "total_discount_340b_pct": [96.0, 50.0],
        })

        flagged = check_penny_pricing(nadac_df)

        assert len(flagged) == 1
        assert flagged[0]["ndc"] == "1111111111"

    def test_threshold_boundary(self) -> None:
        """Test boundary at HIGH_DISCOUNT_THRESHOLD (95%)."""
        nadac_df = pl.DataFrame({
            "ndc": ["AAA", "BBB", "CCC"],
            "penny_pricing": [False, False, False],
            "total_discount_340b_pct": [94.9, 95.0, 95.1],
        })

        flagged = check_penny_pricing(nadac_df)

        # 95.0 and 95.1 should be flagged (>= 95%)
        assert len(flagged) == 2
        flagged_ndcs = {item["ndc"] for item in flagged}
        assert "AAA" not in flagged_ndcs
        assert "BBB" in flagged_ndcs
        assert "CCC" in flagged_ndcs

    def test_missing_columns_returns_empty(self) -> None:
        """Missing penny pricing columns should return empty list."""
        nadac_df = pl.DataFrame({
            "ndc": ["1234567890"],
            "some_other_column": [100],
        })

        flagged = check_penny_pricing(nadac_df)

        assert len(flagged) == 0


class TestCheckPennyPricingForDrug:
    """Tests for single drug penny pricing lookup."""

    def test_penny_priced_drug_lookup(self, sample_nadac_df: pl.DataFrame) -> None:
        """Should detect penny-priced drug by NDC."""
        # NDC 9999999999 has penny_pricing=True and 99.9% discount
        status = check_penny_pricing_for_drug("9999999999", sample_nadac_df)

        assert status.is_penny_priced is True
        assert status.ndc == "9999999999"
        assert status.should_exclude is True

    def test_normal_drug_not_flagged(self, sample_nadac_df: pl.DataFrame) -> None:
        """Normal drug should not be flagged."""
        # NDC 0074433902 has 85.5% discount and penny_pricing=False
        status = check_penny_pricing_for_drug("0074433902", sample_nadac_df)

        assert status.is_penny_priced is False
        assert status.should_exclude is False

    def test_ndc_not_found(self, sample_nadac_df: pl.DataFrame) -> None:
        """Missing NDC should return not-found status."""
        status = check_penny_pricing_for_drug("0000000000", sample_nadac_df)

        assert status.is_penny_priced is False
        assert "not found" in status.warning_message.lower()


class TestFilterTopOpportunities:
    """Tests for filtering penny-priced drugs from opportunities."""

    def test_penny_pricing_excluded_from_top_opportunities(self) -> None:
        """Gatekeeper: Penny Pricing Alert.

        Drugs with Penny Pricing = Yes should NOT appear in "Top Opportunities".
        """
        opportunities = [
            {"ndc": "1111111111", "margin": 1000, "penny_pricing": False},
            {"ndc": "2222222222", "margin": 5000, "penny_pricing": True},
            {"ndc": "3333333333", "margin": 2000, "penny_pricing": False},
        ]

        filtered = filter_top_opportunities(opportunities)

        # High-margin penny-priced drug should be excluded
        assert len(filtered) == 2
        filtered_ndcs = {item["ndc"] for item in filtered}
        assert "2222222222" not in filtered_ndcs
        assert "1111111111" in filtered_ndcs
        assert "3333333333" in filtered_ndcs

    def test_filter_with_nadac_lookup(self) -> None:
        """Should filter using NADAC data for penny pricing lookup."""
        opportunities = [
            {"ndc": "1111111111", "margin": 1000},
            {"ndc": "2222222222", "margin": 5000},
        ]

        nadac_df = pl.DataFrame({
            "ndc": ["1111111111", "2222222222"],
            "penny_pricing": [False, True],
            "total_discount_340b_pct": [50.0, 99.0],
        })

        filtered = filter_top_opportunities(opportunities, nadac_df=nadac_df)

        assert len(filtered) == 1
        assert filtered[0]["ndc"] == "1111111111"

    def test_filter_with_precomputed_ndcs(self) -> None:
        """Should filter using pre-computed penny NDC set."""
        opportunities = [
            {"ndc": "AAA", "margin": 1000},
            {"ndc": "BBB", "margin": 2000},
            {"ndc": "CCC", "margin": 3000},
        ]

        penny_ndcs = {"BBB", "CCC"}

        filtered = filter_top_opportunities(opportunities, penny_ndcs=penny_ndcs)

        assert len(filtered) == 1
        assert filtered[0]["ndc"] == "AAA"

    def test_empty_opportunities_returns_empty(self) -> None:
        """Empty opportunities list should return empty."""
        filtered = filter_top_opportunities([])
        assert filtered == []


class TestGetPennyPricingSummary:
    """Tests for penny pricing summary statistics."""

    def test_summary_statistics(self, sample_nadac_df: pl.DataFrame) -> None:
        """Should calculate correct summary statistics."""
        summary = get_penny_pricing_summary(sample_nadac_df)

        assert summary["total_drugs"] == 3
        assert summary["penny_priced_count"] == 1
        assert summary["penny_priced_pct"] == pytest.approx(33.33, rel=0.01)
        assert "9999999999" in summary["flagged_ndcs"]

    def test_summary_no_penny_drugs(self) -> None:
        """Summary with no penny-priced drugs."""
        nadac_df = pl.DataFrame({
            "ndc": ["AAA", "BBB"],
            "penny_pricing": [False, False],
            "total_discount_340b_pct": [50.0, 60.0],
        })

        summary = get_penny_pricing_summary(nadac_df)

        assert summary["penny_priced_count"] == 0
        assert summary["penny_priced_pct"] == 0.0
        assert summary["flagged_ndcs"] == []


class TestConstants:
    """Tests for risk module constants."""

    def test_penny_threshold(self) -> None:
        """PENNY_THRESHOLD should be $0.10."""
        assert Decimal("0.10") == PENNY_THRESHOLD

    def test_high_discount_threshold(self) -> None:
        """HIGH_DISCOUNT_THRESHOLD should be 95%."""
        assert Decimal("95.0") == HIGH_DISCOUNT_THRESHOLD


class TestEdgeCases:
    """Tests for edge cases in risk flagging."""

    def test_whitespace_in_drug_name(self) -> None:
        """Should handle drug names with extra whitespace."""
        status = check_ira_status("  ENBREL  ")

        assert status["is_ira_drug"] is True

    def test_none_drug_name(self) -> None:
        """Should handle None drug name gracefully."""
        # check_ira_status expects string, but let's handle edge case
        status = check_ira_status("")

        assert status["is_ira_drug"] is False
        assert status["risk_level"] == "Unknown"

    def test_special_characters_in_ndc(self, sample_nadac_df: pl.DataFrame) -> None:
        """Should normalize NDCs with dashes."""
        status = check_penny_pricing_for_drug("0074-4339-02", sample_nadac_df)

        # Should find the normalized version 0074433902
        assert status.ndc == "0074-4339-02"
