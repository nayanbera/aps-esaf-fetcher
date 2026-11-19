"""Unique users = a badge at one institution (SQLite and MongoDB share this rule).

A "slot" is one user on one ESAF:
    {badge, name, institution, country, email, level, esaf_id, start, end, technique, subject}
`level` is the career stage recorded on that ESAF, `institution` the affiliation on that ESAF.
The same badge under a different institution is a different unique user.
"""

from __future__ import annotations

import re
import unicodedata

from . import geo

_STOP = {"the", "of", "at", "in", "for", "and"}


def inst_key(name: str) -> str:
    """Institution name reduced to a comparison key ("The University of Chicago" ==
    "University of Chicago", "Univ of Illinois at Chicago" == "Univ of Illinois Chicago")."""
    t = unicodedata.normalize("NFKD", name or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return " ".join(w for w in re.split(r"[^a-z0-9]+", t) if w and w not in _STOP)


def main_keys(slots: list[dict]) -> dict[str, str]:
    """badge -> key of the institution the badge has most ESAFs at (blank-institution slots join it)."""
    counts: dict[str, dict[str, int]] = {}
    for s in slots:
        k = inst_key(s.get("institution", ""))
        if k:
            c = counts.setdefault(s["badge"], {})
            c[k] = c.get(k, 0) + 1
    return {b: max(c, key=c.get) for b, c in counts.items()}


def slot_key(slot: dict, mains: dict[str, str]) -> str:
    return inst_key(slot.get("institution", "")) or mains.get(slot["badge"], "")


def latest_level(slots: list[dict]) -> str:
    """Career stage from the most recent ESAF that has one."""
    got = [((s.get("start") or ""), s["level"].strip()) for s in slots if (s.get("level") or "").strip()]
    return max(got)[1] if got else ""


def stage_history(slots: list[dict]) -> list[str]:
    """Career stages in time order, consecutive repeats collapsed: ['Post-doc', 'Faculty / professional staff']."""
    out: list[str] = []
    for s in sorted(slots, key=lambda x: x.get("start") or ""):
        lv = (s.get("level") or "").strip()
        if lv and (not out or out[-1] != lv):
            out.append(lv)
    return out


def merge(slots: list[dict]) -> list[dict]:
    """One row per unique user (badge + institution), sorted by name."""
    mains = main_keys(slots)
    groups: dict[tuple, list[dict]] = {}
    for s in slots:
        groups.setdefault((s["badge"], slot_key(s, mains)), []).append(s)
    out = []
    for (badge, _k), g in groups.items():
        insts: dict[str, int] = {}
        for s in g:
            if (s.get("institution") or "").strip():
                insts[s["institution"].strip()] = insts.get(s["institution"].strip(), 0) + 1
        starts = [s["start"] for s in g if s.get("start")]
        ends = [s["end"] for s in g if s.get("end")]
        out.append({
            "badge": badge,
            "name": next((s["name"] for s in g if (s.get("name") or "").strip()), ""),
            "institution": max(insts, key=insts.get) if insts else "",
            "country": max((s.get("country") or "" for s in g), default=""),
            "state": max((s.get("state") or "" for s in g), default=""),
            "email": max((s.get("email") or "" for s in g), default=""),
            "employment_level": latest_level(g),
            "stage_history": stage_history(g),
            "techniques": sorted({s["technique"] for s in g if s.get("technique")}),
            "research_subjects": sorted({x.strip() for s in g if s.get("subject") for x in s["subject"].split(",") if x.strip()}),
            "esaf_count": len({s["esaf_id"] for s in g}),
            "first_experiment": min(starts) if starts else None,
            "last_experiment": max(ends) if ends else None,
        })
    out.sort(key=lambda r: (r["name"] or "").lower())
    return out


def stats(slots: list[dict]) -> dict:
    """unique_users, by_employment and top_users for the Statistics page."""
    users = merge(slots)
    mains = main_keys(slots)
    by_level: dict[str, dict] = {}
    for u in users:
        lv = u["employment_level"].strip() or "Unknown"
        by_level.setdefault(lv, {"employment_level": lv, "unique_users": 0, "esaf_slots": 0})["unique_users"] += 1
    for s in slots:                                        # slots keep the stage they had on that ESAF
        lv = (s.get("level") or "").strip() or "Unknown"
        by_level.setdefault(lv, {"employment_level": lv, "unique_users": 0, "esaf_slots": 0})["esaf_slots"] += 1
    top = sorted(users, key=lambda u: -u["esaf_count"])[:20]
    countries: dict[str, int] = {}
    states: dict[str, int] = {}
    no_country = us_no_state = 0
    for u in users:
        st = geo.us_state(u.get("state", ""))
        c3 = geo.iso3(u.get("country", "")) or ("USA" if st else "")   # a US state with no country = a US user
        if not c3:
            no_country += 1
            continue
        countries[c3] = countries.get(c3, 0) + 1
        if c3 == "USA":
            if st:
                states[st] = states.get(st, 0) + 1
            else:
                us_no_state += 1
    return {
        "unique_users": len(users),
        "by_country": sorted(({"iso3": c, "country": geo.country_name(c), "unique_users": n}
                              for c, n in countries.items()), key=lambda r: (-r["unique_users"], r["country"])),
        "users_no_country": no_country,
        "by_state": sorted(({"state": s, "name": geo.US_STATES[s], "unique_users": n}
                            for s, n in states.items()), key=lambda r: (-r["unique_users"], r["name"])),
        "us_users_no_state": us_no_state,
        "by_employment": sorted(by_level.values(), key=lambda r: -r["unique_users"]),
        "top_users": [{"name": u["name"], "institution": u["institution"], "experiments": u["esaf_count"]} for u in top],
    }


def in_scope(slot: dict, badge: str, want_key: str, mains: dict[str, str], since: str = "") -> bool:
    """Does this slot belong to the unique user (badge, institution key) from `since` on?"""
    if slot["badge"] != badge:
        return False
    if (want_key or mains.get(badge, "")) != slot_key(slot, mains):
        return False
    return not since or (slot.get("start") or "") >= since


def plan_career(slots: list[dict], updates: list[dict], since: str = "") -> list[dict]:
    """For each update {badge, institution, employment_level}: the unique user's ESAFs from `since`
    on, the stages they hold now, and the ESAFs ('targets') whose stage must change."""
    mains = main_keys(slots)
    out = []
    for u in updates:
        scope = [s for s in slots if in_scope(s, u["badge"], inst_key(u.get("institution", "")), mains, since)]
        new = u["employment_level"].strip()
        low = lambda x: (x or "").strip().lower()
        blank = sum(1 for s in scope if not low(s.get("level")))
        changed = sum(1 for s in scope if low(s.get("level")) and low(s["level"]) != new.lower())
        out.append({**u, "esafs": len(scope), "blank": blank, "changed": changed,
                    "old": sorted({s["level"].strip() for s in scope if low(s.get("level"))}),
                    "targets": [s["esaf_id"] for s in scope if low(s.get("level")) != new.lower()]})
    return out


def plan_backfill(slots: list[dict]) -> list[dict]:
    """Blank career stages that can be filled safely: the same person's nearest known stage before
    and after (any ESAF, any institution) is identical.  -> [{esaf_id, badge, level, start}]"""
    by_badge: dict[str, list[dict]] = {}
    for s in slots:
        if s.get("start"):
            by_badge.setdefault(s["badge"], []).append(s)
    out = []
    for badge, ss in by_badge.items():
        known = sorted((s["start"], s["level"].strip()) for s in ss if (s.get("level") or "").strip())
        if not known:
            continue
        for s in ss:
            if (s.get("level") or "").strip():
                continue
            before = [lv for st, lv in known if st <= s["start"]]
            after = [lv for st, lv in known if st >= s["start"]]
            if before and after and before[-1].lower() == after[0].lower():
                out.append({"esaf_id": s["esaf_id"], "badge": badge, "level": before[-1], "start": s["start"]})
    return out
