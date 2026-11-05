"""Group free-text funding labels by agency and sub-group for the Statistics page.

Labels come from GUP PDFs and the APS API, e.g.
"National Science Foundation (NSF) NSF/CHE-2335833 (100%)".  Each is mapped to
an agency (NSF, DOE, ...) and, where recognisable, a sub-group — the NSF
division (DMR, CHE, ...) or the DOE office (BES, ...).
"""

from __future__ import annotations

import re

_NSF_DIVISIONS = (
    "DMR|CHE|PHY|OIA|DMS|CBET|CMMI|ECCS|EAR|MCB|DBI|OAC|CCF|IIS|AST|DGE|EEC|"
    "OCE|OPP|BIO|MPS|ENG|GEO|CISE|EDU|TIP|EFMA|ECCS|DUE|HRD|IOS|MCB|SES"
)
_NSF_DIV_RE = re.compile(rf"(?<![A-Za-z])({_NSF_DIVISIONS})(?![A-Za-z])")
_NSF_DIV_NUM_RE = re.compile(r"(?<![A-Za-z])([A-Z]{3,4})\s*-\s*\d{6,7}")

_DOE_OFFICES = (
    ("BES", re.compile(r"\bBES\b|Basic Energy Sciences", re.I)),
    ("HEP", re.compile(r"\bHEP\b|High Energy Physics", re.I)),
    ("NP",  re.compile(r"Nuclear Physics")),
    ("BER", re.compile(r"\bBER\b|Biological and Environmental", re.I)),
    ("ASCR", re.compile(r"\bASCR\b|Advanced Scientific Computing", re.I)),
    ("FES", re.compile(r"\bFES\b|Fusion Energy", re.I)),
    ("EERE", re.compile(r"\bEERE\b|Energy Efficiency", re.I)),
    ("LDRD", re.compile(r"\bLDRD\b")),
)

OTHER = "Other"


def classify(label: str) -> tuple[str, str]:
    """Return (agency, subgroup) for one funding label; subgroup may be ''."""
    s = " ".join((label or "").split())
    low = s.lower()
    if (low.startswith("foreign") or "deutsche forschung" in low or "nserc" in low
            or re.search(r"\bDFG\b", s)):
        return "Foreign agencies", ""
    if low.startswith("other"):
        return OTHER, ""
    if re.search(r"National Science Foundation|\bNSF\b", s):
        m = _NSF_DIV_NUM_RE.search(s)
        if m and re.fullmatch(_NSF_DIVISIONS, m.group(1)):
            return "NSF", m.group(1)
        m = _NSF_DIV_RE.search(s)
        return "NSF", (m.group(1) if m else "Division not given")
    if re.match(r"DOE\b", s) or "Department of Energy" in s:
        for name, rx in _DOE_OFFICES:
            if rx.search(s):
                return "DOE", name
        return "DOE", "Office not given"
    if re.search(r"Department of Defense|\bDOD\b", s):
        return "DOD", ""
    if re.search(r"National Institutes? of Health|\bNIH\b", s):
        return "NIH", ""
    if re.search(r"\bNASA\b", s):
        return "NASA", ""
    return OTHER, ""


def group_funding(pairs: list[dict]) -> list[dict]:
    """Group {source, esaf_id} pairs → [{agency, count, subgroups:[{name, count, labels}]}].

    Counts are distinct ESAFs, so an ESAF listing two NSF grants counts once
    under NSF.  Groups and subgroups are sorted by count, "other" buckets last.
    """
    tree: dict[str, dict[str, dict]] = {}
    for p in pairs:
        agency, sub = classify(p["source"])
        node = tree.setdefault(agency, {}).setdefault(sub, {"esafs": set(), "labels": {}})
        node["esafs"].add(p["esaf_id"])
        node["labels"].setdefault(p["source"], set()).add(p["esaf_id"])

    groups = []
    for agency, subs in tree.items():
        all_esafs = set().union(*(n["esafs"] for n in subs.values()))
        sublist = [{
            "name": name,
            "count": len(n["esafs"]),
            "labels": sorted(((l, len(e)) for l, e in n["labels"].items()),
                             key=lambda x: -x[1]),
        } for name, n in subs.items()]
        sublist.sort(key=lambda x: (x["name"].endswith("not given"), -x["count"], x["name"]))
        groups.append({"agency": agency, "count": len(all_esafs), "subgroups": sublist})
    groups.sort(key=lambda g: (g["agency"] == OTHER, -g["count"], g["agency"]))
    return groups
