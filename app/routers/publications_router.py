"""Publications and facility awards."""

from __future__ import annotations

import html
import re
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from .. import db, publications as pubs, report
from ..templates_env import templates

router = APIRouter()


def _result(counts: dict, problems: list[str]) -> HTMLResponse:
    parts = [f"{counts['added']} added", f"{counts['updated']} updated",
             f"{counts['duplicate']} already listed", f"{len(problems)} problems"]
    body = html.escape(", ".join(parts))
    if problems:
        li = "".join(f"<li>{html.escape(p)}</li>" for p in problems[:25])
        more = f"<li>… and {len(problems) - 25} more</li>" if len(problems) > 25 else ""
        body += f"<ul class='mb-0 mt-1'>{li}{more}</ul>"
    return HTMLResponse(f'<div class="alert alert-{"warning" if problems else "success"} mb-2">{body}</div>')


def _run_items(items: list[tuple[str, callable]], source: str, fulltext: bool = False) -> HTMLResponse:
    """items: (label, thunk returning (meta, extra_text)); processed sequentially."""
    counts = {"added": 0, "updated": 0, "duplicate": 0}
    problems: list[str] = []
    for label, thunk in items:
        try:
            meta, extra = thunk()
            action, _ = pubs.ingest(meta, source, True, extra, fulltext)
            counts[action] += 1
        except Exception as exc:          # one bad item must not stop the batch
            problems.append(f"{label}: {exc}")
    return _result(counts, problems)


# ---------------------------------------------------------------------------
# Publications page
# ---------------------------------------------------------------------------

def _row(p: dict, awards: list[dict]) -> dict:
    d = pubs.effective_date(p.get("pub_date") or p.get("year"))
    p = dict(p)
    p["_date"] = d
    p["_py"] = report.project_year_of(d) if d else None
    p["_fac_pub"] = ", ".join(pubs.active_awards(awards, d))
    return p


@router.get("/publications", response_class=HTMLResponse)
def publications_page(request: Request, py: str = ""):
    awards = pubs.facility_awards()
    rows = [_row(p, awards) for p in db.list_records(pubs.PUBS)]
    rows.sort(key=lambda p: (p["_date"] is None, p["_date"] and -p["_date"].toordinal() or 0, p.get("title", "")))
    py_sel = int(py) if py.isdigit() else None
    if py_sel:
        rows = [p for p in rows if p["_py"] == py_sel]
    now_py = report.project_year_of(datetime.now().date())
    return templates.TemplateResponse("publications.html", {
        "request": request, "pubs": rows, "py_sel": py_sel,
        "report_years": list(range(1, now_py + 1)), "report_default": max(1, now_py - 1),
        "n_awards": len(awards),
    })


@router.post("/publications/add-dois", response_class=HTMLResponse)
async def add_dois(text: str = Form(""), fulltext: str = Form("")):
    dois = pubs.find_dois(text)
    if not dois:
        return HTMLResponse('<div class="alert alert-warning mb-2">No DOIs found in the text.</div>')
    items = [(d, (lambda d=d: ({"doi": d, "title": "", "authors": "", "year": "", "pub_date": "",
                                "url": "", "type": "", "venue": "", "notes": "", "abstract": ""}, "")))
             for d in dois]
    return await run_in_threadpool(_run_items, items, "doi", bool(fulltext))


@router.post("/publications/search", response_class=HTMLResponse)
async def search_publications(request: Request, q: str = Form(""), mode: str = Form("keyword"),
                              source: list[str] = Form([]), from_date: str = Form("")):
    q = q.strip()
    if not q:
        return HTMLResponse('<div class="alert alert-warning mb-2">Enter something to search for.</div>')
    if mode not in pubs.SEARCH_MODES:
        mode = "keyword"
    from_date = from_date.strip()
    if from_date and not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", from_date):
        return HTMLResponse('<div class="alert alert-warning mb-2">"From" must look like 2025 or 2025-09-01.</div>')
    if re.fullmatch(r"\d{4}-\d{2}", from_date):
        from_date += "-01"
    elif re.fullmatch(r"\d{4}", from_date):
        from_date += "-01-01"
    results, problems = await run_in_threadpool(pubs.search_literature, mode, q,
                                                source or ["openalex", "crossref"], from_date)
    known = {norm for p in db.list_records(pubs.PUBS) if (norm := pubs.norm_doi(p.get("doi", "")))}
    for h in results:
        h["known"] = h["doi"] in known
    return templates.TemplateResponse("partials/pub_search_results.html", {
        "request": request, "results": results, "problems": problems})


@router.post("/publications/add-selected", response_class=HTMLResponse)
async def add_selected(doi: list[str] = Form([]), fulltext: str = Form("")):
    dois = [d for d in dict.fromkeys(pubs.norm_doi(d) for d in doi) if d]
    if not dois:
        return HTMLResponse('<div class="alert alert-warning mb-2">Tick at least one paper.</div>')
    items = [(d, (lambda d=d: ({"doi": d, "title": "", "authors": "", "year": "", "pub_date": "",
                                "url": "", "type": "", "venue": "", "notes": "", "abstract": ""}, "")))
             for d in dois]
    return await run_in_threadpool(_run_items, items, "search", bool(fulltext))


@router.post("/publications/link-esafs", response_class=HTMLResponse)
async def link_esafs_all():
    n = await run_in_threadpool(pubs.relink_all)
    return HTMLResponse(f'<div class="alert alert-success mb-2">ESAF / Team IDs added to {n} publication(s) '
                        f'from their stored acknowledgments.</div>')


@router.post("/publications/read-acks", response_class=HTMLResponse)
async def read_acks_all():
    res = await run_in_threadpool(pubs.read_acknowledgments_all)
    body = (f'{res["read"]} paper(s) read, {res["linked"]} of them now linked to an ESAF')
    cls = "success"
    if res["failed"]:
        cls = "warning"
        li = "".join(f"<li>{html.escape(f)}</li>" for f in res["failed"][:25])
        more = f"<li>… and {len(res['failed']) - 25} more</li>" if len(res["failed"]) > 25 else ""
        body += f", {len(res['failed'])} not accessible:<ul class='mb-0 mt-1'>{li}{more}</ul>"
    return HTMLResponse(f'<div class="alert alert-{cls} mb-2">{body}</div>')


@router.post("/publications/import-file", response_class=HTMLResponse)
async def import_reference_file(files: list[UploadFile] = File(...), fulltext: str = Form("")):
    items = []
    problems = []
    for f in files:
        data = await f.read()
        try:
            refs = pubs.parse_reference_file(f.filename or "", data)
        except Exception as exc:
            problems.append(f"{f.filename}: {exc}")
            continue
        items += [(r.get("title") or r.get("doi") or f.filename, (lambda r=r: (r, ""))) for r in refs]
    res = await run_in_threadpool(_run_items, items, "endnote", bool(fulltext))
    if problems:
        extra = "".join(f"<div class='alert alert-warning mb-2'>{html.escape(p)}</div>" for p in problems)
        return HTMLResponse(extra + res.body.decode())
    return res


@router.post("/publications/import-pdf", response_class=HTMLResponse)
async def import_pdf(files: list[UploadFile] = File(...)):
    blobs = [(f.filename or "file.pdf", await f.read()) for f in files]

    def work():
        items = []
        for name, data in blobs:
            def thunk(name=name, data=data):
                text = pubs.read_pdf_text(data)
                dois = pubs.find_dois(text[:6000])          # the article's own DOI is near the top
                if not dois:
                    raise ValueError("no DOI found in the PDF")
                meta = {"doi": dois[0], "title": "", "authors": "", "year": "", "pub_date": "",
                        "url": "", "type": "", "venue": "", "notes": "", "abstract": ""}
                meta["link_text"] = text                 # ESAF DOIs may sit outside the acknowledgments
                return meta, pubs.ack_section(text)
            items.append((name, thunk))
        return _run_items(items, "pdf")

    return await run_in_threadpool(work)


@router.get("/publications/report.xlsx")
async def publications_report(py: int):
    if py < 1 or py > 50:
        raise HTTPException(422, "Invalid project year")
    content = await run_in_threadpool(pubs.build_report_workbook, py)
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="Publication Reporting_YR{py}.xlsx"'},
    )


# ---------------------------------------------------------------------------
# Facility awards (number + validity dates)
# ---------------------------------------------------------------------------

@router.get("/facility-awards", response_class=HTMLResponse)
def facility_awards_page(request: Request):
    return templates.TemplateResponse("facility_awards.html", {
        "request": request, "awards": pubs.facility_awards()})


@router.post("/facility-awards")
def add_facility_award(number: str = Form(...), label: str = Form(""),
                       start_date: str = Form(""), end_date: str = Form("")):
    number = pubs.canon_award(number)
    if not number:
        raise HTTPException(422, "Award number is required")
    db.save_record(pubs.AWARDS, pubs.new_id(), {
        "number": number, "label": label.strip(),
        "start_date": start_date.strip(), "end_date": end_date.strip()})
    return RedirectResponse("/facility-awards", status_code=303)


@router.post("/facility-awards/{aid}")
def update_facility_award(aid: str, number: str = Form(...), label: str = Form(""),
                          start_date: str = Form(""), end_date: str = Form("")):
    if not db.get_record(pubs.AWARDS, aid):
        raise HTTPException(404)
    db.save_record(pubs.AWARDS, aid, {
        "number": pubs.canon_award(number), "label": label.strip(),
        "start_date": start_date.strip(), "end_date": end_date.strip()})
    return RedirectResponse("/facility-awards", status_code=303)


@router.post("/facility-awards/{aid}/delete")
def delete_facility_award(aid: str):
    db.delete_record(pubs.AWARDS, aid)
    return RedirectResponse("/facility-awards", status_code=303)


# ---------------------------------------------------------------------------
# Single publication
# ---------------------------------------------------------------------------

_FIELDS = ("doi", "title", "authors", "year", "pub_date", "url", "type", "venue",
           "team_ids", "esaf_ids", "facility_ack", "nsf_awards", "other_awards", "notes")


@router.get("/publications/{pid}/edit", response_class=HTMLResponse)
def publication_edit(request: Request, pid: str, saved: str = "", why: str = ""):
    p = db.get_record(pubs.PUBS, pid)
    if not p:
        raise HTTPException(404)
    awards = pubs.facility_awards()
    row = _row(p, awards)
    collected: list[str] = []
    for eid in re.split(r"[,;\s]+", p.get("esaf_ids") or ""):
        esaf = db.get_esaf(eid) if eid else None
        if esaf:
            collected += [a for a in pubs.active_awards(awards, pubs._iso(esaf.get("start_date")))
                          if a not in collected]
    return templates.TemplateResponse("publication_edit.html", {
        "request": request, "p": row, "fac_collected": ", ".join(collected),
        "saved": saved == "1", "read": saved == "read",
        "unreachable": saved == "unreachable", "why": why, "msg": ""})


@router.post("/publications/{pid}")
def publication_save(pid: str, doi: str = Form(""), title: str = Form(""), authors: str = Form(""),
                     year: str = Form(""), pub_date: str = Form(""), url: str = Form(""),
                     type: str = Form(""), venue: str = Form(""), team_ids: str = Form(""),
                     esaf_ids: str = Form(""), facility_ack: str = Form(""),
                     nsf_awards: str = Form(""), other_awards: str = Form(""), notes: str = Form("")):
    p = db.get_record(pubs.PUBS, pid)
    if not p:
        raise HTTPException(404)
    vals = dict(doi=pubs.norm_doi(doi), title=title, authors=authors, year=year.strip(),
                pub_date=pub_date.strip(), url=url.strip(), type=type.strip(), venue=venue.strip(),
                team_ids=", ".join(t for t in re.split(r"[,;\s]+", team_ids.upper()) if t),
                esaf_ids=", ".join(t for t in re.split(r"[,;\s]+", esaf_ids) if t),
                facility_ack=", ".join(pubs.canon_award(t) for t in re.split(r"[,;\s]+", facility_ack) if t),
                nsf_awards=nsf_awards.strip(), other_awards=other_awards.strip(), notes=notes)
    if not vals["pub_date"] and vals["year"]:
        vals["pub_date"] = vals["year"]
    db.save_record(pubs.PUBS, pid, {**p, **vals})
    return RedirectResponse(f"/publications/{pid}/edit?saved=1", status_code=303)


@router.post("/publications/{pid}/refresh")
async def publication_refresh(pid: str):
    """Re-read the metadata from Crossref (keeps award fields the user already filled in)."""
    p = db.get_record(pubs.PUBS, pid)
    if not p or not p.get("doi"):
        raise HTTPException(404)
    try:
        cr = await run_in_threadpool(pubs.fetch_crossref, p["doi"])
    except Exception as exc:
        raise HTTPException(502, f"Crossref lookup failed: {exc}")
    fund = pubs.classify_funders(cr.get("funders", []), [a["number"] for a in pubs.facility_awards()])
    merged = {**p, **{k: v for k, v in cr.items() if k != "funders" and v}}
    merged["facility_ack"] = pubs._union(p.get("facility_ack"), fund["facility_ack"], ",")
    merged["nsf_awards"] = pubs._union(p.get("nsf_awards"), fund["nsf_awards"], ";")
    merged["other_awards"] = p.get("other_awards") or fund["other_awards"]
    db.save_record(pubs.PUBS, pid, merged)
    return RedirectResponse(f"/publications/{pid}/edit?saved=1", status_code=303)


@router.post("/publications/{pid}/read-online")
async def publication_read_online(pid: str):
    p = db.get_record(pubs.PUBS, pid)
    if not p or not p.get("doi"):
        raise HTTPException(404)
    ok, why = await run_in_threadpool(pubs.read_online, p)
    q = "read" if ok else "unreachable&why=" + quote(why)
    return RedirectResponse(f"/publications/{pid}/edit?saved={q}", status_code=303)


@router.post("/publications/{pid}/delete")
def publication_delete(pid: str):
    db.delete_record(pubs.PUBS, pid)
    return RedirectResponse("/publications", status_code=303)
