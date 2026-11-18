"""Read-only inventory of QGIS projects."""

from .sources import SourceInfo, classify_source, redact

__all__ = ["SourceInfo", "classify_source", "redact"]
