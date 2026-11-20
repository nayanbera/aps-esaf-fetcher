"""GUP instruments (Experiment Time Request table) and the ESAF technique they imply.

Only the 15-ID instruments matter here.  Add a row to INSTRUMENT_TECHNIQUE to map another instrument.
"""

from __future__ import annotations

import re

from .esaf_matching import run_cycle

# (station, start of the instrument name, ESAF technique)
INSTRUMENT_TECHNIQUE = [
    ("15-ID-D", "Crystallography", "Xtal"),
    ("15-ID-C", "Liquid interface", "Surf"),
    ("15-ID-D", "Anomalous Small Angle X-ray Scattering", "ASWAXS"),
]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def technique_of(instrument: str) -> str:
    """'15-ID-D Crystallography' -> 'Xtal'; '' for any other instrument."""
    ins = _norm(instrument)
    for station, name, tech in INSTRUMENT_TECHNIQUE:
        if ins.startswith(_norm(f"{station} {name}")):
            return tech
    return ""


def flatten_etr(rows: list[dict]) -> list[dict]:
    """Parser output (one row per ETR, several instruments each) -> one row per instrument, the form stored on a GUP."""
    out = []
    for r in rows or []:
        res = r.get("resources") or []
        for i, e in enumerate(r.get("entries") or []):
            out.append({"etr": r.get("etr", ""), "run_cycle": r.get("run_cycle", ""),
                        "resource": res[i] if len(res) == len(r["entries"]) else ", ".join(res),
                        "instrument": e.get("instrument", ""), "technique": e.get("technique", ""),
                        "requested": r.get("requested", ""), "minimum": r.get("minimum", ""),
                        "lifetime": r.get("lifetime", "")})
    return out


def suggest(start_date: str, etr: list[dict], cycle: str = "") -> tuple[str, str]:
    """Technique an ESAF should have from its GUP's instruments -> (technique or '', why).

    The ETR rows of the ESAF's own run cycle count first; without any, all the GUP's 15-ID rows."""
    mapped = [(r, technique_of(r.get("instrument", ""))) for r in etr or []]
    mapped = [(r, t) for r, t in mapped if t]
    if not mapped:
        return "", "no 15-ID instrument on the GUP"
    cyc = cycle or run_cycle(start_date)
    same = [t for r, t in mapped if cyc and r.get("run_cycle") == cyc]
    pool = same or [t for _r, t in mapped]
    techs = set(pool)
    if len(techs) == 1:
        return techs.pop(), (f"instrument requested for {cyc}" if same else "the GUP's 15-ID instrument")
    return "", "the GUP lists several different 15-ID instruments" + (f" for {cyc}" if same else "")
