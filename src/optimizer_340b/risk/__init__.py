"""Risk flagging module (Watchtower Layer).

Provides risk detection for 340B drug pricing decisions:
- IRA (Inflation Reduction Act) price negotiation detection
- Penny pricing alerts for NADAC floor drugs
- Retail price validation against wholesaler catalog
"""

from optimizer_340b.risk.ira_flags import (
    IRA_2026_DRUGS,
    IRA_2027_DRUGS,
    IRA_DRUGS_BY_YEAR,
    IRARiskStatus,
    check_ira_status,
    filter_ira_drugs,
    get_all_ira_drugs,
    get_ira_risk_status,
)
from optimizer_340b.risk.penny_pricing import (
    HIGH_DISCOUNT_THRESHOLD,
    PENNY_THRESHOLD,
    PennyPricingStatus,
    check_penny_pricing,
    check_penny_pricing_for_drug,
    filter_top_opportunities,
    get_penny_pricing_summary,
)

__all__ = [
    # IRA flags
    "IRA_2026_DRUGS",
    "IRA_2027_DRUGS",
    "IRA_DRUGS_BY_YEAR",
    "IRARiskStatus",
    "check_ira_status",
    "filter_ira_drugs",
    "get_all_ira_drugs",
    "get_ira_risk_status",
    # Penny pricing
    "HIGH_DISCOUNT_THRESHOLD",
    "PENNY_THRESHOLD",
    "PennyPricingStatus",
    "check_penny_pricing",
    "check_penny_pricing_for_drug",
    "filter_top_opportunities",
    "get_penny_pricing_summary",
]
