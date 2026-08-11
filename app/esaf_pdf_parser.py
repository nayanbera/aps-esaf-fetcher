"""PDF parser for APS ESAF documents (Experiment Hazard Control Plan Reports).

Tuned to the "PEN: …  ESAF ID: …" page-header format produced by the APS system.
Returns a plain dict — does NOT depend on the Pydantic models so it can be used
before the DB is initialised.
"""

from __future__ import annotations

import io
import re
from typing import Union


_MONTHS: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _normalise_date(raw: str) -> str:
    raw = raw.strip()
    m = re.search(r"(\d{4})[/\-](\d{2})[/\-](\d{2})", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{1,2})-([A-Za-z]{3,})-(\d{2,4})", raw)
    if m:
        month_num = _MONTHS.get(m.group(2).lower())
        if month_num:
            year = int(m.group(3))
            if year < 100:
                year += 2000 if year < 50 else 1900
            return f"{year:04d}-{month_num:02d}-{int(m.group(1)):02d}"
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2})[,\s]+(\d{4})", raw)
    if m:
        month_num = _MONTHS.get(m.group(1).lower())
        if month_num:
            return f"{m.group(3)}-{month_num:02d}-{int(m.group(2)):02d}"
    return raw


def _pen_to_beamline(pen: str) -> str:
    """Convert '15-IDCD-2026-17' → '15-ID-CD', '12-BM-2026-3' → '12-BM'."""
    m = re.match(r"(\d+)-([A-Z\d]+)-\d{4}", pen.strip())
    if not m:
        return pen
    sector, branch = m.group(1), m.group(2)
    for prefix in ("ID", "BM", "XSD", "XFD", "LOM", "EXP"):
        if branch.startswith(prefix) and len(branch) > len(prefix):
            return f"{sector}-{prefix}-{branch[len(prefix):]}"
    return f"{sector}-{branch}"


def parse_esaf_pdf(pdf_path_or_bytes: Union[str, bytes]) -> dict:
    """Parse an APS ESAF PDF.

    Returns:
        {
            "extracted": {field: value, ...},
            "confidence": {field: float, ...},
            "raw_text": str,
        }

    Key extracted fields: esaf_id, title, start_date, end_date, beamline, gup_id, pi_last.
    """
    import pdfplumber

    if isinstance(pdf_path_or_bytes, (bytes, bytearray)):
        pdf = pdfplumber.open(io.BytesIO(pdf_path_or_bytes))
    else:
        pdf = pdfplumber.open(pdf_path_or_bytes)

    try:
        pages_text: list[str] = []
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                pages_text.append(t)
        raw_text = "\n".join(pages_text)
    finally:
        pdf.close()

    confidence: dict[str, float] = {}
    extracted: dict[str, str] = {}

    # ESAF ID
    m = re.search(r"ESAF\s+ID:\s*(\d+)", raw_text)
    if m:
        extracted["esaf_id"] = m.group(1)
        confidence["esaf_id"] = 1.0
    else:
        m = re.search(r"ESAF\s*(?:Number|No\.?|#)\s*[:\-]?\s*(\d+)", raw_text, re.IGNORECASE)
        if m:
            extracted["esaf_id"] = m.group(1)
            confidence["esaf_id"] = 0.9
        else:
            confidence["esaf_id"] = 0.0

    # Title
    m = re.search(r"^Title:\s*(.+)$", raw_text, re.MULTILINE)
    if m:
        extracted["title"] = m.group(1).strip()
        confidence["title"] = 1.0
    else:
        m = re.search(r"(?:Experiment\s+)?Title\s*[:\-]\s*(.+?)(?:\n|$)", raw_text, re.IGNORECASE)
        if m:
            extracted["title"] = m.group(1).strip()
            confidence["title"] = 0.8
        else:
            confidence["title"] = 0.0

    # Dates — primary: "ID Start Date: MM/DD/YYYY", fallback: "Start Date: DD-MON-YY"
    m = re.search(r"ID\s+Start\s+Date:\s*(\d{1,2}/\d{1,2}/\d{4})", raw_text)
    if m:
        extracted["start_date"] = _normalise_date(m.group(1))
        confidence["start_date"] = 1.0
    else:
        m = re.search(r"(?<![A-Za-z])Start\s+Date:\s*(\d{1,2}-[A-Za-z]{3}-\d{2,4})", raw_text)
        if m:
            extracted["start_date"] = _normalise_date(m.group(1))
            confidence["start_date"] = 0.7
        else:
            confidence["start_date"] = 0.0

    m = re.search(r"ID\s+End\s+Date:\s*(\d{1,2}/\d{1,2}/\d{4})", raw_text)
    if m:
        extracted["end_date"] = _normalise_date(m.group(1))
        confidence["end_date"] = 1.0
    else:
        m = re.search(r"(?<![A-Za-z])End\s+Date:\s*(\d{1,2}-[A-Za-z]{3}-\d{2,4})", raw_text)
        if m:
            extracted["end_date"] = _normalise_date(m.group(1))
            confidence["end_date"] = 0.7
        else:
            confidence["end_date"] = 0.0

    # Beamline from PEN
    m = re.search(r"PEN:\s*([\w\-]+)", raw_text)
    if m:
        pen = m.group(1).strip()
        extracted["beamline"] = _pen_to_beamline(pen)
        extracted["pen"] = pen
        confidence["beamline"] = 0.9
    else:
        confidence["beamline"] = 0.0

    # GUP ID — "GUP ID: 1018531"
    m = re.search(r"GUP\s+ID:\s*(\d+)", raw_text)
    if m:
        extracted["gup_id"] = m.group(1)
        confidence["gup_id"] = 1.0
    else:
        m = re.search(r"GUP\s*[:\-]?\s*(\d{4,})", raw_text)
        if m:
            extracted["gup_id"] = m.group(1)
            confidence["gup_id"] = 0.9
        else:
            confidence["gup_id"] = 0.0

    # Spokesperson last name (used to identify PI)
    m = re.search(r"Spokesperson:\s*(\S+)", raw_text)
    if m:
        extracted["pi_last"] = m.group(1).strip()

    return {
        "extracted": extracted,
        "confidence": confidence,
        "raw_text": raw_text,
    }
