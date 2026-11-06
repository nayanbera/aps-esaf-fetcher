"""Publication tracking: import (EndNote files, DOIs, PDFs), award detection, Excel report.

Publications and facility awards are stored as generic records (db.list_records).
The report mirrors "Publication Reporting_YR*.xlsx"; project years run Sep 1 – Aug 31.
"""

from __future__ import annotations

import io
import logging
import re
import time
import unicodedata
import uuid
from urllib.parse import unquote
import xml.etree.ElementTree as ET
from datetime import date

import requests
from openpyxl import Workbook

from . import db, report
from .funding_groups import _NSF_DIVISIONS
from .pi_id_import import _same_person, _tokens

log = logging.getLogger(__name__)

PUBS, AWARDS = "publications", "facility_awards"
_CROSSREF = "https://api.crossref.org/works/"
_UA = {"User-Agent": "aps-esaf-fetcher (publication tracking)"}

# ---------------------------------------------------------------------------
# DOIs
# ---------------------------------------------------------------------------

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.I)


def norm_doi(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", s, flags=re.I)
    return s.rstrip(".,;)]}>\"'").lower()


def find_dois(text: str) -> list[str]:
    """Distinct DOIs in free text (a DOI list, a pasted alert e-mail, URLs ...)."""
    seen: dict[str, None] = {}
    for m in _DOI_RE.findall(unquote(text or "")):
        d = norm_doi(re.split(r"[&?#]\w+=", m)[0])      # drop URL query strings
        if d:
            seen.setdefault(d)
    return list(seen)


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def effective_date(pub_date: str) -> date | None:
    """YYYY-MM-DD, YYYY-MM (-> 1st) or YYYY (-> 1 July)."""
    m = re.match(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", str(pub_date or ""))
    if not m:
        return None
    y = int(m[1])
    if m[2]:
        return date(y, min(max(int(m[2]), 1), 12), min(max(int(m[3] or 1), 1), 28))
    return date(y, 7, 1)


def _iso(s: str) -> date | None:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(s or ""))
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


# ---------------------------------------------------------------------------
# Awards
# ---------------------------------------------------------------------------

_DASH = "‐‑‒–—―−-"


def canon_award(s: str) -> str:
    """'CHE 1834750' / 'che‑1834750' -> 'CHE-1834750' (other text is returned stripped)."""
    t = re.sub(f"[{_DASH}]", "-", s or "").strip()
    m = re.fullmatch(r"([A-Za-z]{2,5})[\s-]*(\d{5,8})", t)
    return f"{m[1].upper()}-{m[2]}" if m else t


def facility_awards() -> list[dict]:
    rows = db.list_records(AWARDS)
    rows.sort(key=lambda a: (a.get("start_date") or "", a.get("number") or ""))
    return rows


def active_awards(awards: list[dict], d: date | None) -> list[str]:
    if d is None:
        return []
    out = []
    for a in awards:
        start, end = _iso(a.get("start_date")), _iso(a.get("end_date"))
        if (start is None or d >= start) and (end is None or d <= end):
            out.append(canon_award(a["number"]))
    return out


def _award_regex(number: str) -> re.Pattern:
    m = re.fullmatch(r"([A-Z]+)-(\d+)", canon_award(number))
    if not m:
        return re.compile(re.escape(number), re.I)
    return re.compile(rf"(?<![A-Za-z]){m[1]}[\s{_DASH}]*{m[2]}(?!\d)", re.I)


_NSF_CODE_RE = re.compile(
    rf"(?<![A-Za-z])((?:{_NSF_DIVISIONS}|EFRI))[\s{_DASH}]*(\d{{6,7}})(?!\d)")


def analyze_text(text: str, facility_numbers: list[str]) -> dict:
    """Facility awards and NSF award codes mentioned in *text*."""
    fac = [canon_award(n) for n in facility_numbers]
    found_fac = [n for n in fac if _award_regex(n).search(text or "")]
    nsf = []
    for m in _NSF_CODE_RE.finditer(text or ""):
        code = f"{m[1]}-{m[2]}"
        if code not in fac and code not in nsf:
            nsf.append(code)
    return {"facility_ack": found_fac, "nsf": nsf}


def ack_section(text: str, limit: int = 2500) -> str:
    text = text or ""
    ms = list(re.finditer(r"acknowledg(?:e)?ments?", text, re.I))      # the heading is near the end
    if not ms:
        ms = list(re.finditer(r"\bfunding\b", text, re.I))
    return text[ms[-1].start(): ms[-1].start() + limit] if ms else ""


# ---------------------------------------------------------------------------
# Crossref
# ---------------------------------------------------------------------------

_TYPES = {
    "journal-article": "Journal Article", "book-chapter": "Book Chapter",
    "proceedings-article": "Conference Paper", "book": "Book",
    "posted-content": "Preprint", "dissertation": "Thesis", "report": "Report",
}


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def _date_parts(item: dict) -> str:
    for key in ("published", "published-online", "published-print", "issued"):
        parts = (item.get(key) or {}).get("date-parts") or [[]]
        p = parts[0]
        if p and p[0]:
            return "-".join([f"{p[0]:04d}"] + [f"{x:02d}" for x in p[1:3]])
    return ""


def fetch_crossref(doi: str) -> dict:
    """Metadata for one DOI from Crossref.  Raises LookupError when not found."""
    r = requests.get(_CROSSREF + requests.utils.quote(doi, safe="/"), headers=_UA, timeout=20)
    if r.status_code == 404:
        raise LookupError(f"DOI {doi} not found in Crossref")
    r.raise_for_status()
    return parse_crossref(r.json()["message"])


def parse_crossref(item: dict) -> dict:
    authors = []
    for a in item.get("author", []):
        if a.get("family"):
            authors.append(f'{a["family"]}, {a.get("given", "")}'.strip(", "))
        elif a.get("name"):
            authors.append(a["name"])
    pub_date = _date_parts(item)
    return {
        "doi": norm_doi(item.get("DOI", "")),
        "title": _strip_tags((item.get("title") or [""])[0]),
        "authors": "; ".join(authors),
        "year": pub_date[:4],
        "pub_date": pub_date,
        "url": (item.get("resource", {}).get("primary", {}) or {}).get("URL") or item.get("URL", ""),
        "type": _TYPES.get(item.get("type", ""), (item.get("type") or "").replace("-", " ").title()),
        "venue": _strip_tags((item.get("container-title") or [item.get("publisher", "")])[0]),
        "funders": [{"name": f.get("name", ""), "awards": f.get("award", []) or []}
                    for f in item.get("funder", [])],
    }


def classify_funders(funders: list[dict], facility_numbers: list[str]) -> dict:
    """Crossref funder list -> facility_ack / nsf_awards / other_awards strings."""
    fac = [canon_award(n) for n in facility_numbers]
    facility, nsf, other = [], [], []
    for f in funders:
        name = f.get("name", "")
        awards = [canon_award(a) for a in f.get("awards", [])]
        facility += [a for a in awards if a in fac and a not in facility]
        rest = [a for a in awards if a not in fac]
        if re.search(r"National Science Foundation|\bNSF\b", name):
            nsf += [a for a in rest if a not in nsf]
        elif name:
            other.append(f"{name} ({', '.join(rest)})" if rest else name)
    return {"facility_ack": ", ".join(facility), "nsf_awards": "; ".join(nsf),
            "other_awards": "; ".join(other)}


# ---------------------------------------------------------------------------
# Reference-manager files (EndNote exports): RIS, EndNote XML, BibTeX, Refer
# ---------------------------------------------------------------------------

_RIS_TYPES = {"JOUR": "Journal Article", "JFULL": "Journal Article", "EJOUR": "Journal Article",
              "BOOK": "Book", "CHAP": "Book Chapter", "CONF": "Conference Paper",
              "CPAPER": "Conference Paper", "RPRT": "Report", "THES": "Thesis",
              "UNPB": "Preprint", "GEN": "Other"}
_BIB_TYPES = {"article": "Journal Article", "book": "Book", "incollection": "Book Chapter",
              "inbook": "Book Chapter", "inproceedings": "Conference Paper",
              "conference": "Conference Paper", "phdthesis": "Thesis", "mastersthesis": "Thesis",
              "techreport": "Report", "unpublished": "Preprint", "misc": "Other"}


def _flip(name: str) -> str:
    """'Yu-Sheng Chen' -> 'Chen, Yu-Sheng'; 'Chen, Yu-Sheng' unchanged."""
    name = re.sub(r"\s+", " ", name or "").strip()
    if "," in name or " " not in name:
        return name
    parts = name.split(" ")
    return f'{parts[-1]}, {" ".join(parts[:-1])}'


def _ref_date(*values: str) -> tuple[str, str]:
    """-> (year, pub_date) from RIS/Refer style values like '2026/03/01/' or '2026'."""
    for v in values:
        m = re.search(r"(\d{4})(?:[/\-](\d{1,2}))?(?:[/\-](\d{1,2}))?", v or "")
        if m:
            parts = [f"{int(m[1]):04d}"] + [f"{int(x):02d}" for x in (m[2], m[3]) if x]
            return m[1], "-".join(parts)
    return "", ""


def _record(**kw) -> dict:
    base = {"title": "", "authors": "", "year": "", "pub_date": "", "doi": "", "url": "",
            "type": "", "venue": "", "notes": "", "abstract": ""}
    base.update(kw)
    base["doi"] = norm_doi(base["doi"])
    if not base["doi"]:
        found = find_dois(base["url"]) or find_dois(base["notes"])
        base["doi"] = found[0] if found else ""
    return base


def parse_ris(text: str) -> list[dict]:
    out, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])\s{2}-\s?(.*)$", line)
        if not m:
            if cur is not None and line.strip() and cur.get("_last"):
                cur[cur["_last"]][-1] += " " + line.strip()      # wrapped continuation
            continue
        tag, val = m[1], m[2].strip()
        if tag == "TY":
            cur = {"TY": [val]}
        elif tag == "ER":
            if cur is not None:
                out.append(cur)
            cur = None
        elif cur is not None:
            cur.setdefault(tag, []).append(val)
            cur["_last"] = tag
    if cur:
        out.append(cur)

    def first(d, *tags):
        for t in tags:
            if d.get(t):
                return d[t][0]
        return ""

    recs = []
    for d in out:
        year, pub = _ref_date(first(d, "DA"), first(d, "PY", "Y1"))
        recs.append(_record(
            title=first(d, "TI", "T1"), authors="; ".join(d.get("AU", []) + d.get("A1", [])),
            year=year, pub_date=pub, doi=first(d, "DO", "DI"), url=first(d, "UR", "L1", "L2"),
            type=_RIS_TYPES.get(d["TY"][0], d["TY"][0]),
            venue=first(d, "JO", "JF", "T2", "JA", "J2", "BT"),
            notes=" ".join(d.get("N1", [])), abstract=first(d, "AB", "N2")))
    return recs


def parse_endnote_xml(text: str) -> list[dict]:
    root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    recs = []

    def val(rec, path):
        el = rec.find(path)
        return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""

    for rec in root.iter("record"):
        authors = [re.sub(r"\s+", " ", "".join(a.itertext())).strip()
                   for a in rec.findall("./contributors/authors/author")]
        year, pub = _ref_date(val(rec, "./dates/pub-dates/date"), val(rec, "./dates/year"))
        if year and (not pub or len(pub) < 4):
            pub = year
        ref_type = rec.find("ref-type")
        urls = [val(rec, "./urls/related-urls/url")] + [
            re.sub(r"\s+", " ", "".join(u.itertext())).strip()
            for u in rec.findall("./urls/related-urls/url")]
        recs.append(_record(
            title=val(rec, "./titles/title"), authors="; ".join(_flip(a) for a in authors),
            year=year, pub_date=pub, doi=val(rec, "./electronic-resource-num"),
            url=next((u for u in urls if u), ""),
            type=(ref_type.get("name") if ref_type is not None else "") or "",
            venue=val(rec, "./periodical/full-title") or val(rec, "./titles/secondary-title"),
            notes=val(rec, "./notes"), abstract=val(rec, "./abstract")))
    return recs


def _bib_entries(text: str):
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,]*),", text):
        kind, i = m[1].lower(), m.end()
        # find the matching closing brace of the entry
        k = text.find("{", m.start())
        depth, j = 0, k
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield kind, text[i:j]


def _bib_fields(body: str) -> dict:
    fields, i = {}, 0
    while True:
        m = re.compile(r"\s*(\w+)\s*=\s*").search(body, i)
        if not m:
            return fields
        i = m.end()
        if i >= len(body):
            return fields
        if body[i] == "{":
            depth, j = 0, i
            while j < len(body):
                depth += body[j] == "{"
                depth -= body[j] == "}"
                if depth == 0:
                    break
                j += 1
            value, i = body[i + 1:j], j + 1
        elif body[i] == '"':
            j = body.find('"', i + 1)
            value, i = body[i + 1:j], j + 1
        else:
            m2 = re.compile(r"[^,\s]+").match(body, i)
            value, i = (m2[0] if m2 else ""), (m2.end() if m2 else i + 1)
        fields[m[1].lower()] = re.sub(r"\s+", " ", value.replace("{", "").replace("}", "")).strip()


def parse_bibtex(text: str) -> list[dict]:
    recs = []
    for kind, body in _bib_entries(text):
        f = _bib_fields(body)
        authors = "; ".join(_flip(a) for a in re.split(r"\s+and\s+", f.get("author", "")) if a.strip())
        year, pub = _ref_date(f"{f.get('year', '')}-{_month(f.get('month', ''))}" if f.get("month")
                              else f.get("year", ""))
        recs.append(_record(
            title=f.get("title", ""), authors=authors, year=year, pub_date=pub,
            doi=f.get("doi", ""), url=f.get("url", ""), type=_BIB_TYPES.get(kind, kind.title()),
            venue=f.get("journal") or f.get("booktitle") or f.get("publisher", ""),
            notes=f.get("note", ""), abstract=f.get("abstract", "")))
    return recs


def _month(m: str) -> str:
    names = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    m = m.strip().lower()[:3]
    return str(names.index(m) + 1) if m in names else (m if m.isdigit() else "")


def parse_refer(text: str) -> list[dict]:
    recs = []
    for block in re.split(r"\n\s*\n", text.strip()):
        d: dict[str, list[str]] = {}
        for line in block.splitlines():
            m = re.match(r"^%(\S)\s+(.*)$", line)
            if m:
                d.setdefault(m[1], []).append(m[2].strip())
        if not d:
            continue
        first = lambda *k: next((d[x][0] for x in k if d.get(x)), "")
        year, pub = _ref_date(first("D"))
        recs.append(_record(
            title=first("T"), authors="; ".join(_flip(a) for a in d.get("A", [])),
            year=year, pub_date=pub, doi=first("R"), url=first("U"), type=first("0"),
            venue=first("J", "B"), notes=" ".join(d.get("Z", [])), abstract=first("X")))
    return recs


def parse_reference_file(filename: str, data: bytes) -> list[dict]:
    """Parse an EndNote export (RIS / EndNote XML / BibTeX / Refer) into reference dicts."""
    text = data.decode("utf-8-sig", errors="replace")
    head = text.lstrip()[:400]
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if head.startswith("<") or ext == "xml":
        return parse_endnote_xml(text)
    if re.search(r"^TY\s{2}-", text, re.M) or ext == "ris":
        return parse_ris(text)
    if re.search(r"^@\w+\s*\{", text, re.M) or ext == "bib":
        return parse_bibtex(text)
    if re.search(r"^%0\s", text, re.M) or ext == "enw":
        return parse_refer(text)
    raise ValueError("Unrecognised file format — export from EndNote as RIS, EndNote XML, BibTeX or Refer (.enw)")


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def read_pdf_text(data: bytes) -> str:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


# ---------------------------------------------------------------------------
# Full text of a paper by DOI (open access copies, or whatever the server can reach)
# ---------------------------------------------------------------------------

_BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/124.0 Safari/537.36",
            "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8"}
_META_PDF_RE = re.compile(r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)', re.I)


def _html_text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", markup)
    return unescape_html(re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", markup))).strip()


def unescape_html(s: str) -> str:
    import html
    return html.unescape(s)


def _candidate_urls(doi: str) -> list[str]:
    urls: list[str] = []
    try:                                           # OpenAlex lists open-access copies
        r = requests.get(f"https://api.openalex.org/works/doi:{doi}", headers=_UA, timeout=20,
                         params={"select": "locations,best_oa_location"})
        if r.ok:
            j = r.json()
            locs = [j.get("best_oa_location")] + (j.get("locations") or [])
            urls += [l["pdf_url"] for l in locs if l and l.get("pdf_url")]
            urls += [l["landing_page_url"] for l in locs
                     if l and l.get("is_oa") and l.get("landing_page_url")]
    except requests.RequestException:
        pass
    urls.append("https://doi.org/" + doi)          # the publisher page (works on institutional networks)
    return list(dict.fromkeys(urls))


def fetch_fulltext(doi: str) -> tuple[str, str]:
    """Best-effort full text for a DOI.  Returns (text, where-from); ("", reason) if none reachable."""
    reason = "no accessible full text"
    tried: set[str] = set()
    queue = _candidate_urls(doi)
    while queue and len(tried) < 8:
        url = queue.pop(0)
        if url in tried:
            continue
        tried.add(url)
        try:
            r = requests.get(url, headers=_BROWSER, timeout=40, allow_redirects=True)
        except requests.RequestException as exc:
            reason = f"{type(exc).__name__}"
            continue
        if r.status_code >= 400:
            reason = f"HTTP {r.status_code} from {r.url.split('/')[2]}"
            continue
        ctype = r.headers.get("content-type", "").lower()
        if "pdf" in ctype or r.content[:5] == b"%PDF-":
            try:
                text = read_pdf_text(r.content)
            except Exception:
                reason = "unreadable PDF"
                continue
            if len(text) > 1500:
                return text, "PDF"
        else:
            m = _META_PDF_RE.search(r.text)
            if m:                                   # the page points at its own PDF
                from urllib.parse import urljoin
                queue.insert(0, urljoin(r.url, m.group(1)))
            text = _html_text(r.text)
            if len(text) > 4000 and re.search(r"acknowledg|funding|data availability", text, re.I):
                return text, "web page"
            reason = "only the abstract page is accessible"
    return "", reason


# ---------------------------------------------------------------------------
# Building and saving records
# ---------------------------------------------------------------------------

def suggest_teams(authors: str) -> str:
    """Team IDs of PI Groups whose PI appears among the authors."""
    groups = [g for g in db.list_pi_groups() if g.get("pi_id") and g.get("pi_name")]
    gt = {g["name"]: _tokens(g["pi_name"]) for g in groups}
    ids: list[str] = []
    for a in (authors or "").split(";"):
        tok = _tokens(a)
        for g in groups:
            if _same_person(gt[g["name"]], tok):
                ids += [i for i in re.split(r"[,;\s]+", g["pi_id"]) if i and i not in ids]
    return ", ".join(ids)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _key_title(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").lower()
    return re.sub(r"[^a-z0-9]+", "", t)


def find_existing(doi: str, title: str) -> dict | None:
    for p in db.list_records(PUBS):
        if doi and p.get("doi") == doi:
            return p
        if not doi and not p.get("doi") and title and _key_title(p.get("title")) == _key_title(title):
            return p
    return None


_APS_DOI_RE = re.compile(r"10\.46936/aps-(\d+)/", re.I)
_ESAF_NO_RE = re.compile(r"\bESAF(?:\s*(?:No\.?|number|ID|#))?[\s:#-]*(\d{4,8})\b", re.I)


def _split_ids(s: str) -> list[str]:
    return [t for t in re.split(r"[,;\s]+", s or "") if t]


def link_esafs(text: str) -> dict:
    """ESAFs cited in text, either by their DOI (the ESAF DOI users are asked to
    put in the acknowledgments) or as "ESAF 123456".  Also returns the Team IDs
    (PI IDs) of the PI Groups those ESAFs belong to, using the ESAF's technique
    to pick the right ID when the group has one per technique."""
    empty = {"esaf_ids": [], "team_ids": []}
    if not text:
        return empty
    esafs = db.list_esafs(limit=1_000_000)
    by_doi = {d: e for e in esafs if (d := norm_doi(e.get("doi") or ""))}
    by_id = {str(e["esaf_id"]): e for e in esafs}
    hits: list[dict] = []
    for d in find_dois(text):
        e = by_doi.get(d)
        if e is None:                              # APS beam-time DOIs are 10.46936/APS-<ESAF no.>/<OSTI no.>
            m = _APS_DOI_RE.match(d)
            e = by_id.get(m[1]) if m else None
        if e and e not in hits:
            hits.append(e)
    for m in _ESAF_NO_RE.findall(text):
        e = by_id.get(m)
        if e and e not in hits:
            hits.append(e)
    if not hits:
        return empty
    groups = {g["name"]: g for g in db.list_pi_groups()}
    teams: list[str] = []
    for e in hits:
        g = groups.get(e.get("pi_group") or "")
        if not g:
            continue
        ids = [i.upper() for i in _split_ids(g.get("pi_id", ""))]
        prefixes = {report.TECHNIQUES[t][0] for t in (e.get("technique") or "").split(",")
                    if t in report.TECHNIQUES}
        chosen = [i for i in ids if i.split("-")[0] in prefixes] or ids
        teams += [i for i in chosen if i not in teams]
    return {"esaf_ids": [str(e["esaf_id"]) for e in hits], "team_ids": teams}


def build_publication(meta: dict, source: str, fac_numbers: list[str],
                      extra_text: str = "") -> dict:
    """Reference/Crossref metadata -> a publication record, with awards pulled from
    Crossref funders and from any acknowledgment / note text."""
    fund = classify_funders(meta.get("funders", []), fac_numbers)
    text = " ".join(filter(None, [meta.get("notes", ""), extra_text]))
    found = analyze_text(text, fac_numbers)
    facility = list(dict.fromkeys(
        [a.strip() for a in fund["facility_ack"].split(",") if a.strip()] + found["facility_ack"]))
    nsf = list(dict.fromkeys(
        [a.strip() for a in fund["nsf_awards"].split(";") if a.strip()] + found["nsf"]))
    scan = " ".join(filter(None, [text, meta.get("link_text", ""),
                                  " ".join(a for f in meta.get("funders", []) for a in f.get("awards", []))]))
    linked = link_esafs(scan)
    team_ids = list(dict.fromkeys(linked["team_ids"] + _split_ids(suggest_teams(meta.get("authors", "")).replace(",", " "))))
    return {
        "doi": meta.get("doi", ""), "title": meta.get("title", ""),
        "authors": meta.get("authors", ""), "year": meta.get("year", ""),
        "pub_date": meta.get("pub_date", ""), "url": meta.get("url", ""),
        "type": meta.get("type", ""), "venue": meta.get("venue", ""),
        "team_ids": ", ".join(team_ids), "esaf_ids": ", ".join(linked["esaf_ids"]),
        "facility_ack": ", ".join(facility), "nsf_awards": "; ".join(nsf),
        "other_awards": fund["other_awards"], "ack_text": ack_section(extra_text)[:1500],
        "notes": "", "source": source,
    }


# ---------------------------------------------------------------------------
# Excel report
# ---------------------------------------------------------------------------

def project_year_publications(py: int) -> list[dict]:
    start, end = report.project_year_range(py)
    rows = []
    for p in db.list_records(PUBS):
        d = effective_date(p.get("pub_date") or p.get("year"))
        if d and start <= d <= end:
            rows.append((d, p))
    rows.sort(key=lambda x: (x[0], x[1].get("title", "")), reverse=True)
    return [p for _, p in rows]


def build_report_workbook(py: int) -> bytes:
    awards = facility_awards()
    rows = []
    for p in project_year_publications(py):
        d = effective_date(p.get("pub_date") or p.get("year"))
        collected: list[str] = []
        for eid in re.split(r"[,;\s]+", p.get("esaf_ids") or ""):
            esaf = db.get_esaf(eid) if eid else None
            if esaf:
                collected += [a for a in active_awards(awards, _iso(esaf.get("start_date")))
                              if a not in collected]
        rows.append([
            p.get("team_ids", ""), p.get("authors", ""), p.get("title", ""),
            int(p["year"]) if str(p.get("year", "")).isdigit() else p.get("year", ""),
            p.get("doi", ""), p.get("url", ""), p.get("type", ""), p.get("venue", ""),
            ", ".join(collected), ", ".join(active_awards(awards, d)),
            p.get("facility_ack", ""), p.get("nsf_awards", ""), p.get("other_awards", ""),
        ])
    wb = Workbook()
    report._sheet(wb, "Publications", [
        ("Team ID", "Team ID from users table", 11, True),
        ("Authors", "All authors", 50, False),
        ("Title", "Publication title", 50, False),
        ("Year", "Publication Year, e.g. ####", 8, True),
        ("DOI", "DOI", 28, False),
        ("URL", "Link to online publication", 40, False),
        ("Type", "Publication, book, chapter, conference", 16, True),
        ("Publication Name", "Name of journal, book, etc.", 30, False),
        ("Facility Award Number (at time of data collection)",
         "Facility award numbers at time of data collection (if known), e.g., CHE-######", 22, True),
        ("Facility Award Number (at time of publication)",
         "Facility award numbers active at the time of publication, e.g., CHE-#######", 22, True),
        ("Facility Award (acknowledged in publication)",
         "Facility award number acknowledged in publication. Ideally this would be same as column K.", 22, True),
        ("NSF Awards Supporting Science",
         "NSF Award numbers acknowledged in publication that support science, including division "
         "abbreviation, e.g., CHE-####### (exclude facility award numbers)", 28, False),
        ("Other Agencies Award Numbers",
         "All other agencies/funding sources acknowledged in publication, e.g. DOE (#########)", 40, False),
    ], [[(c if c != "" else None) for c in r] for r in rows], True)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Literature search (OpenAlex + Crossref)
# ---------------------------------------------------------------------------

_OPENALEX = "https://api.openalex.org/works"
SEARCH_MODES = {
    "keyword": "Title / abstract keywords",
    "fulltext": "Full text (acknowledgments)",
    "award": "Award number",
    "author": "Author name",
    "orcid": "Author ORCID",
}


def _openalex_params(mode: str, query: str, from_date: str) -> dict:
    flt = []
    params = {"per-page": "50", "sort": "publication_date:desc"}
    if mode == "keyword":
        params["search"] = query
    elif mode == "fulltext":
        flt.append("fulltext.search:" + query.replace(",", " "))
    elif mode == "award":
        flt.append("awards.funder_award_id:" + canon_award(query))
    elif mode == "author":
        flt.append("raw_author_name.search:" + query.replace(",", " "))
    elif mode == "orcid":
        flt.append("author.orcid:" + re.sub(r"^.*orcid\.org/", "", query.strip()))
    if from_date:
        flt.append("from_publication_date:" + from_date)
    if flt:
        params["filter"] = ",".join(flt)
    if mode == "keyword":
        params.pop("sort")                       # keep relevance order for keyword search
    return params


def search_openalex(mode: str, query: str, from_date: str = "") -> list[dict]:
    r = requests.get(_OPENALEX, headers=_UA, timeout=30,
                     params={**_openalex_params(mode, query, from_date),
                             "select": "doi,title,publication_date,publication_year,authorships,"
                                       "primary_location,cited_by_count,type"})
    r.raise_for_status()
    out = []
    for w in r.json().get("results", []):
        doi = norm_doi(w.get("doi") or "")
        if not doi:
            continue
        src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
        names = [(a.get("author") or {}).get("display_name", "") for a in w.get("authorships", [])]
        out.append({"doi": doi, "title": _strip_tags(w.get("title") or ""), "venue": src,
                    "date": w.get("publication_date") or str(w.get("publication_year") or ""),
                    "authors": "; ".join(n for n in names if n), "cited": w.get("cited_by_count") or 0,
                    "source": "OpenAlex"})
    return out


def search_crossref(mode: str, query: str, from_date: str = "") -> list[dict]:
    params = {"rows": "50", "select": "DOI,title,author,container-title,issued,published,is-referenced-by-count"}
    flt = []
    if mode == "keyword":
        params["query.bibliographic"] = query
    elif mode == "fulltext":
        params["query"] = query                  # Crossref has no full-text index; this matches metadata
    elif mode == "author":
        params["query.author"] = query
    elif mode == "award":
        flt.append("award.number:" + canon_award(query))
    elif mode == "orcid":
        flt.append("orcid:" + re.sub(r"^.*orcid\.org/", "", query.strip()))
    if from_date:
        flt.append("from-pub-date:" + from_date)
    if flt:
        params["filter"] = ",".join(flt)
    if mode in ("award", "orcid", "author"):
        params["sort"], params["order"] = "published", "desc"
    for attempt in range(3):                     # Crossref rate-limits bursts with 429
        r = requests.get("https://api.crossref.org/works", headers=_UA, timeout=30, params=params)
        if r.status_code != 429:
            break
        time.sleep(2 * (attempt + 1))
    r.raise_for_status()
    out = []
    for it in r.json()["message"].get("items", []):
        doi = norm_doi(it.get("DOI", ""))
        if not doi:
            continue
        names = [f'{a["family"]}, {a.get("given", "")}'.strip(", ") if a.get("family") else a.get("name", "")
                 for a in it.get("author", [])]
        out.append({"doi": doi, "title": _strip_tags((it.get("title") or [""])[0]),
                    "venue": _strip_tags((it.get("container-title") or [""])[0]),
                    "date": _date_parts(it), "authors": "; ".join(n for n in names if n),
                    "cited": it.get("is-referenced-by-count") or 0, "source": "Crossref"})
    return out


def search_literature(mode: str, query: str, sources: list[str], from_date: str = "") -> tuple[list[dict], list[str]]:
    """Merge results from the chosen sources by DOI.  Returns (results, problems)."""
    funcs = {"openalex": search_openalex, "crossref": search_crossref}
    merged: dict[str, dict] = {}
    problems: list[str] = []
    for src in sources:
        fn = funcs.get(src)
        if not fn:
            continue
        try:
            hits = fn(mode, query, from_date)
        except Exception as exc:
            problems.append(f"{src}: {exc}")
            continue
        for h in hits:
            cur = merged.get(h["doi"])
            if cur is None:
                merged[h["doi"]] = h
            else:
                cur["source"] += " + " + h["source"]
                for k in ("title", "venue", "date", "authors"):
                    cur[k] = cur[k] or h[k]
                cur["cited"] = max(cur["cited"], h["cited"])
    results = sorted(merged.values(), key=lambda h: h["date"], reverse=True)
    return results, problems


# ---------------------------------------------------------------------------
# Ingest (shared by DOI list, EndNote file and PDF imports)
# ---------------------------------------------------------------------------

def _union(a: str, b: str, sep: str) -> str:
    items = [x.strip() for x in (a or "").split(sep) if x.strip()]
    items += [x.strip() for x in (b or "").split(sep) if x.strip() and x.strip() not in items]
    return f"{sep} ".join(items) if sep != "," else ", ".join(items)


def ingest(meta: dict, source: str, enrich: bool = True, extra_text: str = "",
           fulltext: bool = False) -> tuple[str, dict]:
    """Add (or enrich) one publication.  Returns (action, record); action is
    "added", "updated" or "duplicate".  With *fulltext*, the paper itself is
    fetched by DOI and its acknowledgments are read."""
    fac_numbers = [a["number"] for a in facility_awards()]
    if enrich and meta.get("doi"):
        try:
            cr = fetch_crossref(meta["doi"])
        except LookupError:
            cr = None
        if cr:
            meta = {**meta, **{k: v for k, v in cr.items() if v}}      # Crossref wins where it has a value
    if fulltext and meta.get("doi") and not extra_text:
        text, _ = fetch_fulltext(meta["doi"])
        if text:
            meta = {**meta, "link_text": text}
            extra_text = ack_section(text)
    rec = build_publication(meta, source, fac_numbers, extra_text)
    existing = find_existing(rec["doi"], rec["title"])
    if existing is None:
        db.save_record(PUBS, new_id(), rec)
        return "added", rec
    if source == "pdf" or extra_text or meta.get("link_text"):         # a PDF / full text adds acknowledgment evidence to a known paper
        merged = dict(existing)
        merged["facility_ack"] = _union(existing.get("facility_ack"), rec["facility_ack"], ",")
        merged["nsf_awards"] = _union(existing.get("nsf_awards"), rec["nsf_awards"], ";")
        merged["ack_text"] = existing.get("ack_text") or rec["ack_text"]
        merged["esaf_ids"] = _union(existing.get("esaf_ids"), rec["esaf_ids"], ",")
        merged["team_ids"] = _union(existing.get("team_ids"), rec["team_ids"], ",")
        if merged != existing:
            db.save_record(PUBS, existing["id"], merged)
            return "updated", merged
    return "duplicate", existing


def read_online(p: dict) -> tuple[bool, str]:
    """Fetch one stored publication's full text and add the awards / ESAF / Team
    IDs found.  Returns (found-text, reason-if-not)."""
    text, how = fetch_fulltext(p["doi"])
    if not text:
        return False, how
    ingest({"doi": p["doi"], "title": p.get("title", ""), "authors": p.get("authors", ""),
            "link_text": text}, "fulltext", enrich=False, extra_text=ack_section(text))
    return True, how


def read_acknowledgments_all() -> dict:
    """Read the full text of every publication that has a DOI but no ESAF ID yet
    (whether or not an acknowledgment is already stored) and add what is found."""
    out = {"read": 0, "linked": 0, "failed": []}
    for p in db.list_records(PUBS):
        if not p.get("doi") or p.get("esaf_ids"):
            continue
        try:
            ok, why = read_online(p)
        except Exception as exc:
            out["failed"].append(f'{p["doi"]}: {exc}')
            continue
        if not ok:
            out["failed"].append(f'{p["doi"]}: {why}')
            continue
        out["read"] += 1
        if (db.get_record(PUBS, p["id"]) or {}).get("esaf_ids"):
            out["linked"] += 1
    return out


def relink_all() -> int:
    """Re-scan the stored acknowledgment/notes of every publication for ESAF
    references and add any ESAF / Team IDs found.  Returns how many changed."""
    changed = 0
    for p in db.list_records(PUBS):
        text = " ".join(filter(None, [p.get("ack_text"), p.get("notes"), p.get("nsf_awards"),
                                      p.get("other_awards"), p.get("facility_ack")]))
        linked = link_esafs(text)
        esaf = _union(p.get("esaf_ids"), ", ".join(linked["esaf_ids"]), ",")
        team = _union(p.get("team_ids"), ", ".join(linked["team_ids"]), ",")
        if esaf != (p.get("esaf_ids") or "") or team != (p.get("team_ids") or ""):
            db.save_record(PUBS, p["id"], {**p, "esaf_ids": esaf, "team_ids": team})
            changed += 1
    return changed
