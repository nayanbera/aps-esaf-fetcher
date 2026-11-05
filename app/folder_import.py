"""Generic watched-folder PDF importer — manual and scheduled.

PDFs under a watched folder are parsed in place and never modified: the
database stores the original path rather than a copy.  A manifest of
(mtime, size) per file lets scheduled runs skip PDFs unchanged since the
last import.  Used for both GUP and ESAF PDFs; each kind supplies a
``process`` callback that handles one file.
"""

from __future__ import annotations

import html
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler

from . import config

log = logging.getLogger(__name__)

# What a ``process`` callback returns for one PDF:
#   "added" / "updated" — stored in the DB
#   "ignored"           — not a PDF of this kind; remembered, never re-parsed
#   "skipped"           — could not be used *yet* (e.g. ESAF not synced); retried next run
# It may instead return (outcome, reason); the reason is shown next to skipped files.
_MAX_LISTED = 25

_DEFAULTS = {
    "folder":       "",
    "recursive":    True,
    "interval_hrs": 0,       # 0 = scheduled import disabled
    "last_run":     "",
    "last_summary": "",
    "manifest":     {},      # {pdf path: [mtime_ns, size]}
}


class FolderImporter:
    def __init__(
        self,
        name: str,
        process: Callable[[str, str], "str | tuple[str, str]"],
        managed_subdir: str,
        updated_label: str = "updated",
        skipped_label: str = "skipped",
        has_added: bool = True,
        after_import: "Callable[[], tuple[str, list[str]]] | None" = None,
    ):
        self.name = name
        self._process = process
        self._managed_subdir = managed_subdir
        self._updated_label = updated_label
        self._skipped_label = skipped_label
        self._has_added = has_added
        self._after_import = after_import
        self._job_id = f"{name}_folder_import"
        self._scheduler: BackgroundScheduler | None = None
        self._run_lock = threading.Lock()
        self._settings_lock = threading.Lock()

    # -- settings ----------------------------------------------------------

    def _settings_path(self) -> Path:
        p = Path(config.PDF_DIR)
        p.mkdir(parents=True, exist_ok=True)
        return p / f"{self.name}_import.json"

    def load_settings(self) -> dict:
        with self._settings_lock:
            try:
                saved = json.loads(self._settings_path().read_text())
            except (OSError, ValueError):
                saved = {}
        return {**_DEFAULTS, **saved}

    def _save_settings(self, settings: dict) -> None:
        with self._settings_lock:
            path = self._settings_path()
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(settings, indent=2))
            tmp.replace(path)

    # -- helpers -----------------------------------------------------------

    def is_managed_pdf(self, pdf_path: str) -> bool:
        """True if the PDF lives in our own upload dir (safe to delete with its record)."""
        try:
            Path(pdf_path).resolve().relative_to(
                (Path(config.PDF_DIR) / self._managed_subdir).resolve())
            return True
        except ValueError:
            return False

    def _check_not_managed(self, folder: str) -> None:
        if self.is_managed_pdf(str(Path(folder).expanduser() / "x.pdf")):
            raise ValueError(
                "That folder is the app's own PDF storage; choose your source folder instead")

    @staticmethod
    def find_pdfs(folder: Path, recursive: bool) -> list[Path]:
        it = folder.rglob("*") if recursive else folder.glob("*")
        return sorted(p for p in it if p.is_file() and p.suffix.lower() == ".pdf")

    # -- import ------------------------------------------------------------

    def import_folder(self, folder: str, recursive: bool = True, force: bool = False) -> dict:
        """Import every PDF under *folder*.  Source files are only ever read."""
        root = Path(folder).expanduser()
        if not root.is_dir():
            raise FileNotFoundError(f"Folder not found: {folder}")
        self._check_not_managed(str(root))

        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError(f"A {self.name.upper()} import is already running")
        try:
            settings = self.load_settings()
            old = settings["manifest"] if settings["folder"] == str(root) else {}
            manifest: dict = {}
            pdfs = self.find_pdfs(root, recursive)
            counts = {"found": len(pdfs), "added": 0, "updated": 0,
                      "unchanged": 0, "skipped": 0}
            errors: list[str] = []
            skipped_files: list[str] = []
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
                    outcome = self._process(key, now)
                    reason = ""
                    if isinstance(outcome, tuple):
                        outcome, reason = outcome
                    if outcome in ("added", "updated"):
                        counts[outcome] += 1
                        manifest[key] = sig
                    else:
                        counts["skipped"] += 1
                        rel = str(pdf.relative_to(root))
                        skipped_files.append(f"{rel} — {reason}" if reason else rel)
                        if outcome == "ignored":
                            manifest[key] = sig
                except Exception as exc:
                    errors.append(f"{pdf.relative_to(root)}: {exc}")
                    log.exception("Error importing %s PDF %s", self.name, pdf)

            counts["errors"] = errors
            counts["skipped_files"] = skipped_files
            parts = [f"{counts['found']} PDFs:"]
            if self._has_added:
                parts.append(f"{counts['added']} added,")
            parts.append(f"{counts['updated']} {self._updated_label},")
            parts.append(f"{counts['unchanged']} unchanged,")
            parts.append(f"{counts['skipped']} {self._skipped_label},")
            parts.append(f"{len(errors)} errors")
            summary = " ".join(parts)
            counts["notes"] = []
            if self._after_import:
                try:
                    short, details = self._after_import()
                    if short:
                        summary += f" · {short}"
                    counts["notes"] = details
                except Exception:
                    log.exception("Post-import step failed for %s", self.name)

            # Re-read so a settings change made during the run isn't clobbered;
            # only record the manifest if the watched folder is still this one.
            latest = self.load_settings()
            if latest["folder"] == str(root):
                latest.update(manifest=manifest, last_run=now, last_summary=summary)
                self._save_settings(latest)
            log.info("%s folder import of %s — %s", self.name.upper(), root, summary)
            counts["summary"] = summary
            return counts
        finally:
            self._run_lock.release()

    @staticmethod
    def format_result(counts: dict) -> str:
        """HTML alert for an import result."""
        def listing(title: str, items: list[str]) -> str:
            if not items:
                return ""
            li = "".join(f"<li>{html.escape(i)}</li>" for i in items[:_MAX_LISTED])
            more = f"<li>… and {len(items) - _MAX_LISTED} more</li>" if len(items) > _MAX_LISTED else ""
            return f"<br>{title}<ul class='mb-0'>{li}{more}</ul>"

        errors = counts.get("errors") or []
        body = (html.escape(counts["summary"])
                + listing("", counts.get("notes") or [])
                + listing("Errors:", errors)
                + listing("Skipped files:", counts.get("skipped_files") or []))
        return f'<div class="alert alert-{"warning" if errors else "success"}">{body}</div>'

    # -- schedule ----------------------------------------------------------

    def _scheduled_run(self) -> None:
        s = self.load_settings()
        if not s["folder"]:
            return
        try:
            self.import_folder(s["folder"], s["recursive"])
        except Exception:
            log.exception("Scheduled %s import failed", self.name.upper())

    def configure(self, folder: str, recursive: bool, interval_hrs: int) -> None:
        """Persist the watched-folder settings and (re)start the schedule."""
        folder = str(Path(folder).expanduser())
        self._check_not_managed(folder)
        s = self.load_settings()
        if folder != s["folder"]:
            s["manifest"] = {}  # new folder — re-import everything
        s.update(folder=folder, recursive=recursive, interval_hrs=max(0, interval_hrs))
        self._save_settings(s)
        self._apply_schedule(s)

    def _apply_schedule(self, s: dict) -> None:
        self.stop_scheduler()
        if s["interval_hrs"] <= 0 or not s["folder"]:
            return
        self._scheduler = BackgroundScheduler(daemon=True)
        self._scheduler.add_job(self._scheduled_run, "interval", hours=s["interval_hrs"],
                                id=self._job_id, max_instances=1, coalesce=True)
        self._scheduler.start()
        log.info("%s folder import scheduled every %d h for %s",
                 self.name.upper(), s["interval_hrs"], s["folder"])

    def start_scheduler(self) -> None:
        self._apply_schedule(self.load_settings())

    def stop_scheduler(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._scheduler = None
