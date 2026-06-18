"""Report layer: 户部口径 metrics + markdown/json report generation."""

from .metrics import PerformanceMetrics, compute_metrics
from .report import ReportGenerator

__all__ = ["PerformanceMetrics", "compute_metrics", "ReportGenerator"]
