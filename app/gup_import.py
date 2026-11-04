"""GUP PDF folder import — see folder_import.FolderImporter for the mechanics."""

from __future__ import annotations

import logging

from . import db
from .folder_import import FolderImporter
from .gup_pdf_parser import parse_gup_pdf

log = logging.getLogger(__name__)


def build_gup_data(result: dict, pdf_path: str) -> dict:
    ex = result["extracted"]
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
        "beamlines":        ", ".join(result.get("beamlines", [])),
        "status":           ex.get("status", ""),
        "submitted_at":     ex.get("submitted_at", ""),
        "pdf_path":         pdf_path,
        "raw_fields":       ex,
        "funding_sources":  result.get("funding_sources", []),
    }


def propagate_funding(gup_id: str, funding_sources: list[dict]) -> None:
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
    if labels:
        count = db.propagate_gup_funding(gup_id, labels)
        if count:
            log.info("Propagated %d funding source(s) to %d ESAF(s) for GUP %s",
                     len(labels), count, gup_id)


def _process(pdf_path: str, now: str) -> str:
    result = parse_gup_pdf(pdf_path)
    data = build_gup_data(result, pdf_path)
    if not data["gup_id"]:
        return "ignored"
    action = db.upsert_gup(data, now)
    propagate_funding(data["gup_id"], data["funding_sources"])
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
