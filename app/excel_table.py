"""Read a table from an Excel sheet whose header row is not on row 1.

Reports exported from APS tools put a title and a date above the header and leave
column A empty; the header row is found by looking for a known column name.
"""

from __future__ import annotations

import datetime as dt

HEADER_KEYS = {"experiment id", "esaf_id", "badge"}


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, dt.datetime):
        return v.isoformat(sep=" ", timespec="seconds") if (v.hour or v.minute or v.second) else v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def rows_to_records(rows: list[tuple]) -> list[dict]:
    """First row (within the top 30) holding a known key column is the header;
    columns with a blank header are dropped; fully blank data rows are skipped."""
    start = next((i for i, r in enumerate(rows[:30])
                  if HEADER_KEYS & {_cell(c).lower() for c in r}), 0)
    if start >= len(rows):
        return []
    headers = [_cell(c) for c in rows[start]]
    keep = [i for i, h in enumerate(headers) if h]
    out = []
    for row in rows[start + 1:]:
        rec = {headers[i]: _cell(row[i]) if i < len(row) else "" for i in keep}
        # skip blank rows and footers such as "Total uniques users count:"
        eid = next((v for k, v in rec.items() if k.lower() in ("experiment id", "esaf_id")), None)
        if any(rec.values()) and (eid is None or eid.isdigit()):
            out.append(rec)
    return out
