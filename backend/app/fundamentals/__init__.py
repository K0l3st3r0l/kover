from .flags import DetectedFlag, detect_metric_flags, detect_text_flags
from .metrics import FundamentalMetrics, compute_metrics, compute_ttm
from .normalizer import METRIC_ALIASES, facts_by_metric, normalize_company_facts
from .profiles import classify, is_supported
from .score import compute_financial_safety_score

__all__ = [
    "DetectedFlag", "detect_metric_flags", "detect_text_flags",
    "FundamentalMetrics", "compute_metrics", "compute_ttm",
    "METRIC_ALIASES", "facts_by_metric", "normalize_company_facts",
    "classify", "is_supported", "compute_financial_safety_score",
]
