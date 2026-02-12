"""340B Site-of-Care Optimization Engine.

Determines optimal treatment pathway (Retail vs Medical) for 340B drugs
by calculating Net Realizable Revenue.
"""

from optimizer_340b.config import Settings
from optimizer_340b.models import DosingProfile, Drug, MarginAnalysis

__version__ = "0.1.0"
__all__ = ["Settings", "Drug", "MarginAnalysis", "DosingProfile"]
