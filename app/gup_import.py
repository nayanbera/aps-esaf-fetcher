"""GUP PDF folder import — see folder_import.FolderImporter for the mechanics."""

from __future__ import annotations

import logging

from . import db, instruments
from .folder_import import FolderImporter
from .gup_pdf_parser import parse_gup_pdf

log = logging.getLogger(__name__)


def build_gup_data(result: dict, pdf_path: str) -> dict:
    ex = result["extracted"]
    etr = instruments.flatten_etr(result.get("etr", []))
    # the requested beamlines are the Resource column of the ETR table; the text fallback is only for PDFs without one
    beamlines = ", ".join(dict.fromkeys(r["resource"] for r in etr if r["resource"])) or ", ".join(result.get("beamlines", []))
    return {
        "gup_id":           ex.get("gup_id", "").strip(),
        "title":            ex.get("title", ""),
        "pi_name":          ex.get("pi_name", ""),
        "pi_institution":   ex.get("pi_institution", ""),
        "run_cycle":        ex.get("run_cycle", ""),
        "proposal_call":    ex.get("proposal_call", ""),
        "proposal_type":    ex.get("proposal_type", ""),
        "primary_area":     ex.get("primary_area", ""),
        "additional_areas": ex.get("additional_areas", ""),
        "review_panel":     ex.get("review_panel", ""),
        "co_pi":            ex.get("co_pi", ""),
        "co_proposers":     ex.get("co_proposers", ""),
        "keywords":         ex.get("keywords", ""),
        "abstract":         ex.get("abstract", ""),
        "beamlines":        beamlines,
        "status":           ex.get("status", ""),
        "submitted_at":     ex.get("submitted_at", ""),
        "pdf_path":         pdf_path,
        "raw_fields":       ex,
        "funding_sources":  result.get("funding_sources", []),
        "etr":              etr,
    }


def funding_labels(funding_sources: list[dict]) -> list[str]:
    """'Agency — grant (NN%)' strings, the form stored on an ESAF."""
    labels = []
    for fs in funding_sources:
        parts = [fs.get("agency", "").strip()]
        if fs.get("grant_number"):
            parts.append(fs["grant_number"].strip())
        label = " — ".join(p for p in parts if p)
        if fs.get("percentage"):
            label += f" ({fs['percentage']}%)"
        if label:
            labels.append(label)
    return labels


def update_gup_techniques(gup_ids: set[str] | None = None, apply: bool = True) -> dict:
    """The GUP's own technique from its 15-ID instrument (its proposal run cycle's rows first); a technique set by
    hand is kept.  -> {set: [(gup_id, technique)], same: n, differs: [(gup_id, current, suggested)], unclear: n}"""
    out = {"set": [], "same": 0, "differs": [], "unclear": 0}
    for row in db.list_gups(limit=1_000_000):
        gid = row["gup_id"]
        if gup_ids is not None and gid not in gup_ids:
            continue
        gup = db.get_gup(gid) or {}
        if not gup.get("etr"):
            continue
        tech, _why = instruments.suggest("", gup["etr"], cycle=gup.get("run_cycle", ""))
        if not tech:
            out["unclear"] += 1
            continue
        cur = (gup.get("technique") or "").strip()
        if cur == tech:
            out["same"] += 1
        elif not cur or gup.get("technique_source") == "instrument":
            out["set"].append((gid, tech))
            if apply:
                db.set_gup_technique(gid, tech, "instrument")
        else:
            out["differs"].append((gid, cur, tech))
    return out


def update_techniques(gup_ids: set[str] | None = None, apply: bool = True) -> dict:
    """Set each ESAF's technique from its GUP's 15-ID instrument (see instruments.py).

    Only ESAFs with no technique, or one set by this rule before, are changed; a technique set by hand is left
    and reported under 'differs'.  gup_ids limits it to the ESAFs of those GUPs.
    -> {set: [(esaf_id, technique)], same: n, differs: [(esaf_id, current, suggested)], unclear: n}"""
    out = {"set": [], "same": 0, "differs": [], "unclear": 0, "gups": update_gup_techniques(gup_ids, apply)}
    etr_by_gup: dict[str, list] = {}
    for row in db.list_esaf_gup_rows():
        gid = (row.get("gup_id") or "").strip()
        if not gid or (gup_ids is not None and gid not in gup_ids) or (row.get("title") or "").endswith("(imported)"):
            continue
        if gid not in etr_by_gup:
            etr_by_gup[gid] = (db.get_gup(gid) or {}).get("etr") or []
        if not etr_by_gup[gid]:
            continue
        esaf = db.get_esaf(row["esaf_id"]) or {}
        tech, _why = instruments.suggest(esaf.get("start_date", ""), etr_by_gup[gid])
        if not tech:
            out["unclear"] += 1
            continue
        cur = (esaf.get("technique") or "").strip()
        if cur == tech:
            out["same"] += 1
        elif not cur or esaf.get("technique_source") == "instrument":
            out["set"].append((row["esaf_id"], tech))
            if apply:
                db.set_esaf_technique(row["esaf_id"], tech, "instrument")
        else:
            out["differs"].append((row["esaf_id"], cur, tech))
    return out


def fill_funding_from_gups(apply: bool = False) -> dict:
    """ESAFs linked to a GUP that have NO funding get that GUP's funding (ESAFs with funding are never changed).

    -> {have, restore: [(esaf_id, gup_id)], labels: {gup_id: [...]}, no_gup_data: {gup_id: [esaf_id]}, no_link: [esaf_id]}"""
    labels: dict[str, list[str]] = {}
    out = {"have": 0, "restore": [], "labels": labels, "no_gup_data": {}, "no_link": []}
    for row in db.list_esaf_gup_rows():
        if (row.get("title") or "").endswith("(imported)"):
            continue
        eid, gid = row["esaf_id"], (row.get("gup_id") or "").strip()
        if (db.get_esaf(eid) or {}).get("funding_sources"):
            out["have"] += 1
        elif not gid:
            out["no_link"].append(eid)
        else:
            if gid not in labels:
                labels[gid] = funding_labels((db.get_gup(gid) or {}).get("funding_sources") or [])
            if labels[gid]:
                out["restore"].append((eid, gid))
            else:
                out["no_gup_data"].setdefault(gid, []).append(eid)
    if apply:
        for eid, gid in out["restore"]:
            db.set_esaf_funding(eid, labels[gid])
    return out


def propagate_funding(gup_id: str, funding_sources: list[dict]) -> None:
    labels = funding_labels(funding_sources)
    if labels:
        count = db.propagate_gup_funding(gup_id, labels)
        if count:
            log.info("Propagated %d funding source(s) to %d ESAF(s) for GUP %s",
                     len(labels), count, gup_id)


def _process(pdf_path: str, now: str) -> str:
    result = parse_gup_pdf(pdf_path)
    data = build_gup_data(result, pdf_path)
    if not data["gup_id"]:
        return "ignored", "no GUP ID found in PDF"
    action = db.upsert_gup(data, now)
    propagate_funding(data["gup_id"], data["funding_sources"])
    update_techniques({data["gup_id"]})
    return action


importer = FolderImporter(
    "gup", _process, managed_subdir="gups",
    skipped_label="skipped (no GUP ID)",
)
load_settings = importer.load_settings
configure = importer.configure
import_folder = importer.import_folder
format_result = importer.format_result
start_scheduler = importer.start_scheduler
stop_scheduler = importer.stop_scheduler
is_managed_pdf = importer.is_managed_pdf
