"""ESAF PDF folder import — see folder_import.FolderImporter for the mechanics.

ESAF PDFs are matched to ESAFs already in the database (from the APS sync).
A PDF whose ESAF isn't there yet is skipped and retried on the next run.
"""

from __future__ import annotations

import logging

from . import db
from .esaf_pdf_parser import parse_esaf_pdf
from .folder_import import FolderImporter
from .gup_import import propagate_funding

log = logging.getLogger(__name__)


def _process(pdf_path: str, now: str) -> str:
    result = parse_esaf_pdf(pdf_path)
    ex = result["extracted"]
    esaf_id = ex.get("esaf_id", "").strip()
    if not esaf_id:
        return "ignored"
    if db.get_esaf(esaf_id) is None:
        return "skipped"
    gup_id = ex.get("gup_id", "").strip()
    db.update_esaf_pdf(esaf_id, gup_id, pdf_path)
    if gup_id:
        gup = db.get_gup(gup_id)
        if gup and gup.get("funding_sources"):
            propagate_funding(gup_id, gup["funding_sources"])
    return "updated"


importer = FolderImporter(
    "esaf", _process, managed_subdir="esafs",
    updated_label="matched", skipped_label="skipped (no ESAF ID, or ESAF not in database)",
    has_added=False,
)
load_settings = importer.load_settings
configure = importer.configure
import_folder = importer.import_folder
format_result = importer.format_result
start_scheduler = importer.start_scheduler
stop_scheduler = importer.stop_scheduler
is_managed_pdf = importer.is_managed_pdf
