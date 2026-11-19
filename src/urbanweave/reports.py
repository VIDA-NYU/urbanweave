"""Reports: what a step did, as plain data.

A report is a nested dict of JSON-compatible values with a readable ``str``. Match and aggregation
reports compose: :func:`urbanweave.aggregate` returns a frame whose report holds the match report
and one entry per reduction (:func:`report_of`).

IDs appear as counts plus a bounded sample (:data:`SAMPLE_SIZE` IDs by default). Pass
``full_ids=True`` where offered to get every ID instead, for diagnostics on large runs.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import numpy as np
import pandas as pd

#: The number of example IDs a report keeps for each list of IDs.
SAMPLE_SIZE = 10

REPORT_ATTR = "urbanweave_report"


def plain(value):
    """*value* as JSON-compatible Python data (NumPy scalars and arrays converted)."""
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, np.ndarray, pd.Index)):
        return [plain(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        f = float(value)
        return None if np.isnan(f) else f
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def id_list(ids, *, full: bool = False) -> dict:
    """``{"count": n, "sample": [...]}``, or every ID under ``"ids"`` when *full*."""
    ids = list(ids)
    out = {"count": len(ids)}
    if full:
        out["ids"] = plain(ids)
    else:
        out["sample"] = plain(ids[:SAMPLE_SIZE])
    return out


class Report(dict):
    """A report: a dict with a readable summary as its ``str``."""

    def to_json(self, **kwargs) -> str:
        return json.dumps(plain(self), **kwargs)

    def __str__(self) -> str:
        return summarize(self)


def summarize(report: Mapping, indent: str = "") -> str:
    lines = []
    for key, value in report.items():
        if isinstance(value, Mapping):
            if set(value) <= {"count", "sample", "ids"} and "count" in value:
                sample = value.get("sample", value.get("ids", []))
                more = f" (e.g. {', '.join(map(str, sample))})" if sample else ""
                lines.append(f"{indent}{key}: {value['count']}{more}")
            else:
                lines.append(f"{indent}{key}:")
                lines.append(summarize(value, indent + "  "))
        elif isinstance(value, list) and value and isinstance(value[0], Mapping):
            lines.append(f"{indent}{key}:")
            for item in value:
                lines.append(summarize(item, indent + "  - ").replace("\n" + indent + "  - ", "\n" + indent + "    "))
        else:
            lines.append(f"{indent}{key}: {plain(value)}")
    return "\n".join(line for line in lines if line)


def report_of(frame) -> Report | None:
    """The report urbanweave attached to a result frame, or None."""
    return getattr(frame, "attrs", {}).get(REPORT_ATTR)
