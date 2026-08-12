"""PDF parser for APS GUP (General User Proposal) documents.

Tuned to the "Proposal NNNNNN / (Status) Date / Title" format produced
by the APS proposal system.  Funding sources and ETR beamlines are
extracted from embedded tables when available, with text-regex fallbacks.
"""

from __future__ import annotations

import io
import re
from typing import Union


def parse_gup_pdf(pdf_path_or_bytes: Union[str, bytes]) -> dict:
    """Parse an APS GUP PDF.

    Returns:
        {
            "extracted":        {field: value, ...},
            "confidence":       {field: float, ...},
            "funding_sources":  [{"agency", "details", "grant_number", "percentage"}, ...],
            "beamlines":        [str, ...],
            "raw_text":         str,
        }
    """
    import pdfplumber

    if isinstance(pdf_path_or_bytes, (bytes, bytearray)):
        pdf_obj = pdfplumber.open(io.BytesIO(pdf_path_or_bytes))
    else:
        pdf_obj = pdfplumber.open(pdf_path_or_bytes)

    try:
        pages_text: list[str] = []
        pages = list(pdf_obj.pages)
        for page in pages:
            t = page.extract_text()
            pages_text.append(t or "")
        raw_text = "\n".join(pages_text)

        funding_rows: list[dict] = []
        beamlines: list[str] = []

        for page in pages:
            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue
                _try_funding_table(table, funding_rows)
                _try_etr_table(table, beamlines)
    finally:
        pdf_obj.close()

    confidence: dict[str, float] = {}
    extracted: dict[str, str] = {}

    # GUP ID — "Proposal 1021836" on its own line
    m = re.search(r"^Proposal\s+(\d{5,7})\s*$", raw_text, re.MULTILINE)
    if m:
        extracted["gup_id"] = m.group(1)
        confidence["gup_id"] = 1.0
    else:
        m = re.search(r"Proposal\s+(?:Number|ID|No\.?)?\s*[:\-]?\s*(\d{5,7})", raw_text, re.IGNORECASE)
        if m:
            extracted["gup_id"] = m.group(1)
            confidence["gup_id"] = 0.9
        else:
            confidence["gup_id"] = 0.0

    # Status + submission date — "(Submitted for Review) 06/17/2026 16:38:25"
    m = re.search(r"\(([^)]+)\)\s*(\d{2}/\d{2}/\d{4})", raw_text)
    if m:
        extracted["status"] = m.group(1).strip()
        extracted["submitted_at"] = m.group(2).strip()
        confidence["status"] = 1.0
    else:
        confidence["status"] = 0.0

    # Title — first non-empty line after the "(Status) Date" line
    m = re.search(r"\([^)]+\)\s*\d{2}/\d{2}/\d{4}[^\n]*\n([^\n]+)", raw_text)
    if m:
        candidate = m.group(1).strip()
        if len(candidate) > 10 and not candidate.isupper():
            extracted["title"] = candidate
            confidence["title"] = 0.9
        else:
            confidence["title"] = 0.0
    else:
        confidence["title"] = 0.0

    # Run cycle — "2026-3 Standard General User Proposals"
    m = re.search(r"(\d{4}-\d+)\s+(?:Standard\s+)?General\s+User", raw_text, re.IGNORECASE)
    if m:
        extracted["run_cycle"] = m.group(1)
        confidence["run_cycle"] = 1.0
    else:
        confidence["run_cycle"] = 0.0

    # Principal Investigator — next line after "Principal Investigator\n"
    m = re.search(r"Principal\s+Investigator\s*\n([^\n]+)", raw_text)
    if m:
        pi_line = m.group(1).strip()
        if "," in pi_line:
            parts = pi_line.split(",", 1)
            extracted["pi_name"] = parts[0].strip()
            extracted["pi_institution"] = parts[1].strip()
        else:
            extracted["pi_name"] = pi_line
        confidence["pi_name"] = 0.95
    else:
        confidence["pi_name"] = 0.0

    # Primary area of research
    m = re.search(r"Primary\s+Area\s+of\s+Research\s*\n([^\n]+)", raw_text)
    if m:
        area = m.group(1).strip()
        # Two-column layout sometimes merges the next label onto the same line
        area = re.split(r"\s{3,}", area)[0].strip()
        extracted["primary_area"] = area
        confidence["primary_area"] = 0.9

    # Keywords — between "Keywords\n" and "Review Panel" or "Abstract"
    m = re.search(
        r"Keywords?\s*\n(.+?)(?=Review Panel|Abstract\b)",
        raw_text, re.DOTALL | re.IGNORECASE,
    )
    if m:
        kw = re.sub(r"\s+", " ", m.group(1)).strip()
        extracted["keywords"] = kw
        confidence["keywords"] = 0.8

    # Abstract — between "Abstract\n" heading and "Funding Sources" or "ETR"
    m = re.search(
        r"\bAbstract\b\s*\n(.+?)(?=Funding Sources|Experiment Time Requests|\bETR\b)",
        raw_text, re.DOTALL | re.IGNORECASE,
    )
    if m:
        abstract = re.sub(r"\s+", " ", m.group(1)).strip()
        extracted["abstract"] = abstract
        confidence["abstract"] = 0.9

    # Proposal type
    m = re.search(r"\bType\b\s*\n([^\n]+)", raw_text)
    if m:
        extracted["proposal_type"] = m.group(1).strip()
        confidence["proposal_type"] = 0.8

    # Text fallbacks if table parsing found nothing
    if not funding_rows:
        funding_rows = _parse_funding_from_text(raw_text)
    if not beamlines:
        beamlines = _parse_beamlines_from_text(raw_text)

    return {
        "extracted": extracted,
        "confidence": confidence,
        "funding_sources": funding_rows,
        "beamlines": beamlines,
        "raw_text": raw_text,
    }


# ---------------------------------------------------------------------------
# Table parsing helpers
# ---------------------------------------------------------------------------

_ETR_SKIP = re.compile(
    r"experiment\s+time\s+request|lifetime\s+shift|run\s+cycle\s+resource"
    r"|number\s+of\s+shifts|\bETR\b",
    re.IGNORECASE,
)

# Matches a grant/award number at the end of a merged source cell, e.g.:
# "R01 HL136734", "CBET 2309886", "EFRI E3P2132178", "2215190"
_GRANT_PAT = re.compile(
    r"\s+((?:[A-Z][A-Z0-9]{0,4}\s+)?[A-Z]*\d{5,}\w*)\s*$"
)


def _split_merged_source_cell(text: str) -> tuple:
    """Parse 'Agency [grant] [pct]' when pdfplumber collapses all columns into one cell."""
    text = text.strip()
    pct = 0
    pct_m = re.search(r"\s+(\d{1,3})\s*$", text)
    if pct_m:
        v = int(pct_m.group(1))
        if v <= 100:
            pct = v
            text = text[: pct_m.start()].strip()
    grn = ""
    grn_m = _GRANT_PAT.search(text)
    if grn_m:
        grn = grn_m.group(1).strip()
        text = text[: grn_m.start()].strip()
    return text, grn, pct


def _try_funding_table(table: list, funding_rows: list[dict]) -> None:
    """Detect and parse a Funding Sources table, appending rows to funding_rows."""
    for i, row in enumerate(table):
        cells = [c or "" for c in row]
        row_text = " ".join(cells).lower()
        # Use word boundary so "Resource" in ETR headers doesn't match "source".
        if re.search(r"\bsource\b", row_text) and "percentage" in row_text:
            h = [c.lower().strip() for c in cells]
            src_i = next((j for j, x in enumerate(h) if "source" in x), 0)
            det_i = next((j for j, x in enumerate(h) if "detail" in x), -1)
            grn_i = next((j for j, x in enumerate(h) if "grant" in x), -1)
            pct_i = next((j for j, x in enumerate(h) if "percent" in x), -1)
            for data_row in table[i + 1:]:
                dc = [c or "" for c in data_row]
                if not any(dc):
                    continue
                src = dc[src_i].strip() if src_i < len(dc) else ""
                det = dc[det_i].strip() if det_i >= 0 and det_i < len(dc) else ""
                grn = dc[grn_i].strip() if grn_i >= 0 and grn_i < len(dc) else ""
                pct_raw = dc[pct_i].strip() if pct_i >= 0 and pct_i < len(dc) else ""
                if src and not _ETR_SKIP.search(src):
                    # pdfplumber sometimes collapses all columns into the first cell.
                    # Detect this when grant and percentage columns are both empty.
                    if not grn and not pct_raw:
                        src, grn, pct = _split_merged_source_cell(src)
                    else:
                        try:
                            pct = int(re.sub(r"[^\d]", "", pct_raw) or "0")
                        except ValueError:
                            pct = 0
                    if pct > 100:
                        continue  # nonsensical percentage — ETR or parse artifact
                    if src:
                        funding_rows.append({
                            "agency": src, "details": det,
                            "grant_number": grn, "percentage": pct,
                        })
            return


def _try_etr_table(table: list, beamlines: list[str]) -> None:
    """Detect and parse an ETR table, appending beamline names to beamlines."""
    for i, row in enumerate(table):
        cells = [c or "" for c in row]
        row_text = " ".join(cells).lower()
        if "resource" in row_text and ("run cycle" in row_text or "instrument" in row_text):
            h = [c.lower().strip() for c in cells]
            res_i = next((j for j, x in enumerate(h) if "resource" in x), -1)
            if res_i >= 0:
                for etr_row in table[i + 1:]:
                    ec = [c or "" for c in etr_row]
                    if res_i < len(ec) and ec[res_i].strip():
                        bl = ec[res_i].strip()
                        if bl and bl not in beamlines:
                            beamlines.append(bl)
            return


# ---------------------------------------------------------------------------
# Text-regex fallbacks
# ---------------------------------------------------------------------------

def _parse_funding_from_text(raw_text: str) -> list[dict]:
    rows: list[dict] = []
    m = re.search(
        r"Source\s+Details?\s+Grant\s+Percentage\s*\n(.+?)(?=Experiment Time Requests|\bETR\b|$)",
        raw_text, re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return rows
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line:
            continue
        pct_m = re.search(r"\b(\d{1,3})\s*$", line)
        if not pct_m:
            continue
        pct = int(pct_m.group(1))
        rest = line[: pct_m.start()].strip()
        grn_m = re.search(r"\b([A-Z]\d{2}[\s\-]\w+|\w+[-/]\w+[-/]\w+)\s*$", rest)
        grant = grn_m.group(1).strip() if grn_m else ""
        agency = rest[: grn_m.start()].strip() if grn_m else rest
        if agency:
            rows.append({"agency": agency, "details": "", "grant_number": grant, "percentage": pct})
    return rows


def _parse_beamlines_from_text(raw_text: str) -> list[str]:
    beamlines: list[str] = []
    for line in raw_text.splitlines():
        for bl in re.findall(r"\b(\d{1,2}-(?:ID|BM|XSD|XFD|LOM|EXP)[A-Z,\-]*)\b", line):
            if bl not in beamlines:
                beamlines.append(bl)
    return beamlines
