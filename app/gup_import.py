"""Folder import of GUP PDFs — manual and scheduled.

PDFs found in a watched folder are parsed in place; the database stores the
original path rather than a copy.  A manifest of (mtime, size) per file lets
scheduled runs skip PDFs that have not changed since the last import.
"""

from __future__ import annotations

import html
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from . import config, db
from .gup_pdf_parser import parse_gup_pdf

log = logging.getLogger(__name__)

_JOB_ID = "gup_folder_import"
_scheduler: BackgroundScheduler | None = None
_run_lock = threading.Lock()
_settings_lock = threading.Lock()

_DEFAULTS = {
    "folder":       "",
    "recursive":    True,
    "interval_hrs": 0,       # 0 = scheduled import disabled
    "last_run":     "",
    "last_summary": "",
    "manifest":     {},      # {pdf path: [mtime_ns, size]}
}


# ---------------------------------------------------------------------------
# Settings persistence (JSON file in PDF_DIR)
# ---------------------------------------------------------------------------

def _settings_path() -> Path:
    p = Path(config.PDF_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p / "gup_import.json"


def load_settings() -> dict:
    with _settings_lock:
        try:
            saved = json.loads(_settings_path().read_text())
        except (OSError, ValueError):
            saved = {}
    return {**_DEFAULTS, **saved}


def _save_settings(settings: dict) -> None:
    with _settings_lock:
        tmp = _settings_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, indent=2))
        tmp.replace(_settings_path())


# ---------------------------------------------------------------------------
# Parsing -> DB record
# ---------------------------------------------------------------------------

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


def is_managed_pdf(pdf_path: str) -> bool:
    """True if the PDF lives in our own upload dir (safe to delete with the GUP)."""
    try:
        Path(pdf_path).resolve().relative_to((Path(config.PDF_DIR) / "gups").resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Folder import
# ---------------------------------------------------------------------------

def find_pdfs(folder: Path, recursive: bool) -> list[Path]:
    it = folder.rglob("*") if recursive else folder.glob("*")
    return sorted(p for p in it if p.is_file() and p.suffix.lower() == ".pdf")


def import_folder(folder: str, recursive: bool = True, force: bool = False) -> dict:
    """Import every GUP PDF under *folder*.

    Unchanged files (same mtime and size as the last run) are skipped unless
    *force* is set.  Returns counts plus a list of per-file errors.
    """
    root = Path(folder).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")

    if not _run_lock.acquire(blocking=False):
        raise RuntimeError("A GUP import is already running")
    try:
        settings = load_settings()
        old = settings["manifest"] if settings["folder"] == str(root) else {}
        manifest: dict = {}
        pdfs = find_pdfs(root, recursive)
        counts = {"found": len(pdfs), "added": 0, "updated": 0,
                  "unchanged": 0, "skipped": 0}
        errors: list[str] = []
        now = datetime.now(timezone.utc).isoformat()

        for pdf in pdfs:
            key = str(pdf)
            try:
                st = pdf.stat()
                sig = [st.st_mtime_ns, st.st_size]
                if not force and old.get(key) == sig:
                    manifest[key] = sig
                    counts["unchanged"] += 1
                    continue
                result = parse_gup_pdf(key)
                data = build_gup_data(result, key)
                if not data["gup_id"]:
                    counts["skipped"] += 1
                    manifest[key] = sig  # not a GUP; don't re-parse every day
                    continue
                action = db.upsert_gup(data, now)
                propagate_funding(data["gup_id"], data["funding_sources"])
                counts["added" if action == "added" else "updated"] += 1
                manifest[key] = sig
            except Exception as exc:
                errors.append(f"{pdf.relative_to(root)}: {exc}")
                log.exception("Error importing GUP PDF %s", pdf)

        counts["errors"] = errors
        summary = (f"{counts['found']} PDFs: {counts['added']} added, "
                   f"{counts['updated']} updated, {counts['unchanged']} unchanged, "
                   f"{counts['skipped']} skipped, {len(errors)} errors")
        # Re-read so a settings change made during the run isn't clobbered;
        # only record the manifest if the watched folder is still this one.
        latest = load_settings()
        if latest["folder"] == str(root):
            latest.update(manifest=manifest, last_run=now, last_summary=summary)
            _save_settings(latest)
        log.info("GUP folder import of %s — %s", root, summary)
        counts["summary"] = summary
        return counts
    finally:
        _run_lock.release()


def format_result(counts: dict) -> str:
    """HTML alert for an import result."""
    msg = html.escape(counts["summary"])
    errors = counts.get("errors") or []
    if errors:
        items = "".join(f"<li>{html.escape(e)}</li>" for e in errors)
        return f'<div class="alert alert-warning">{msg}<br>Errors:<ul>{items}</ul></div>'
    return f'<div class="alert alert-success">{msg}</div>'


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

def _scheduled_run() -> None:
    s = load_settings()
    if not s["folder"]:
        return
    try:
        import_folder(s["folder"], s["recursive"])
    except Exception:
        log.exception("Scheduled GUP import failed")


def configure(folder: str, recursive: bool, interval_hrs: int) -> None:
    """Persist the watched-folder settings and (re)start the schedule."""
    folder = str(Path(folder).expanduser())
    s = load_settings()
    if folder != s["folder"]:
        s["manifest"] = {}  # new folder — re-import everything
    s.update(folder=folder, recursive=recursive, interval_hrs=max(0, interval_hrs))
    _save_settings(s)
    _apply_schedule(s)


def _apply_schedule(s: dict) -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
    if s["interval_hrs"] <= 0 or not s["folder"]:
        return
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(_scheduled_run, "interval", hours=s["interval_hrs"],
                       id=_JOB_ID, max_instances=1, coalesce=True)
    _scheduler.start()
    log.info("GUP folder import scheduled every %d h for %s",
             s["interval_hrs"], s["folder"])


def start_scheduler() -> None:
    _apply_schedule(load_settings())


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
