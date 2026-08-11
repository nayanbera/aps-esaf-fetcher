"""MongoDB backend. ESAFs stored as documents with embedded users."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.collection import Collection

from ..repository import ESAFRepository


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MongoESAFRepository(ESAFRepository):

    def __init__(self, uri: str, db_name: str):
        self._client = MongoClient(uri)
        self._db_name = db_name

    def _esafs(self) -> Collection:
        return self._client[self._db_name]["esafs"]

    def _sync_log(self) -> Collection:
        return self._client[self._db_name]["sync_log"]

    def _field_defs(self) -> Collection:
        return self._client[self._db_name]["custom_field_definitions"]

    def _domain_overrides(self) -> Collection:
        return self._client[self._db_name]["domain_overrides"]

    def _pi_groups(self) -> Collection:
        return self._client[self._db_name]["pi_groups"]

    @staticmethod
    def _clean(doc: dict) -> dict:
        doc.pop("_id", None)
        return doc

    # ------------------------------------------------------------------
    # Schema / indexes
    # ------------------------------------------------------------------

    def init_db(self) -> None:
        self._esafs().create_index([("esaf_id", ASCENDING)], unique=True)
        self._esafs().create_index([("year", DESCENDING)])
        self._esafs().create_index([("beamline", ASCENDING)])
        self._esafs().create_index([("status", ASCENDING)])
        self._esafs().create_index([("users.badge", ASCENDING)])
        self._esafs().create_index([("gup_id", ASCENDING)])
        self._field_defs().create_index([("name", ASCENDING)], unique=True)
        self._domain_overrides().create_index([("domain", ASCENDING)], unique=True)
        self._pi_groups().create_index([("name", ASCENDING)], unique=True)
        self._gups().create_index([("gup_id", ASCENDING)], unique=True)
        self._gups().create_index([("run_cycle", DESCENDING)])

    # ------------------------------------------------------------------
    # ESAFs
    # ------------------------------------------------------------------

    def list_esafs(
        self,
        year: Optional[int] = None,
        beamline: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        query: dict = {}
        if year:
            query["year"] = year
        if beamline:
            query["beamline"] = {"$regex": beamline, "$options": "i"}
        if status:
            query["status"] = status
        if search:
            query["$or"] = [
                {"title":       {"$regex": search, "$options": "i"}},
                {"pi_name":     {"$regex": search, "$options": "i"}},
                {"description": {"$regex": search, "$options": "i"}},
                {"esaf_id":     {"$regex": search, "$options": "i"}},
            ]

        cursor = (
            self._esafs()
            .find(query, {"_id": 0, "raw_json": 0})
            .sort([("year", DESCENDING), ("esaf_id", DESCENDING)])
            .skip(offset)
            .limit(limit)
        )
        results = []
        for doc in cursor:
            doc["user_count"] = len(doc.pop("users", []))
            results.append(doc)
        return results

    def get_esaf(self, esaf_id: str) -> Optional[dict]:
        doc = self._esafs().find_one({"esaf_id": esaf_id})
        return self._clean(doc) if doc else None

    def count_esafs(
        self,
        year: Optional[int] = None,
        beamline: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> int:
        query: dict = {}
        if year:
            query["year"] = year
        if beamline:
            query["beamline"] = {"$regex": beamline, "$options": "i"}
        if status:
            query["status"] = status
        if search:
            query["$or"] = [
                {"title":       {"$regex": search, "$options": "i"}},
                {"pi_name":     {"$regex": search, "$options": "i"}},
                {"description": {"$regex": search, "$options": "i"}},
                {"esaf_id":     {"$regex": search, "$options": "i"}},
            ]
        return self._esafs().count_documents(query)

    def get_filter_options(self) -> dict:
        years     = sorted(self._esafs().distinct("year"), reverse=True)
        beamlines = sorted(b for b in self._esafs().distinct("beamline") if b)
        statuses  = sorted(s for s in self._esafs().distinct("status")   if s)
        return {"years": years, "beamlines": beamlines, "statuses": statuses}

    def update_esaf_fields(
        self, esaf_id: str, notes: str, custom_fields: dict, pi_group: str = ""
    ) -> bool:
        result = self._esafs().update_one(
            {"esaf_id": esaf_id},
            {"$set": {
                "notes": notes,
                "custom_fields": custom_fields,
                "pi_group": pi_group,
                "updated_at": _now_iso(),
            }},
        )
        if pi_group.strip():
            self._pi_groups().update_one(
                {"name": pi_group.strip()},
                {"$setOnInsert": {"name": pi_group.strip()}},
                upsert=True,
            )
        return result.matched_count > 0

    def list_pi_groups(self) -> list[dict]:
        docs = self._pi_groups().find({}, {"_id": 0}).sort("name", ASCENDING)
        return [
            {k: d.get(k, "") for k in
             ("name", "pi_name", "pi_email", "institution", "country", "state",
              "orcid_id", "created_at")}
            for d in docs
        ]

    def upsert_pi_group(
        self, name: str, pi_name: str = "", pi_email: str = "",
        institution: str = "", country: str = "", state: str = "", orcid_id: str = ""
    ) -> None:
        self._pi_groups().update_one(
            {"name": name},
            {"$set": {"pi_name": pi_name, "pi_email": pi_email,
                      "institution": institution, "country": country,
                      "state": state, "orcid_id": orcid_id}},
            upsert=True,
        )

    def delete_pi_group(self, name: str) -> bool:
        return self._pi_groups().delete_one({"name": name}).deleted_count > 0

    def propagate_pi_group_by_pi_name(
        self, group_name: str, pi_name: str, institution: str = ""
    ) -> int:
        import re as _re
        if not pi_name.strip():
            return 0
        tokens = [t for t in _re.split(r"[\s,\.]+", pi_name.strip()) if len(t) >= 2]
        if not tokens:
            return 0
        query: dict = {
            "$or": [{"pi_group": {"$in": ["", None]}}, {"pi_group": {"$exists": False}}],
            "$and": [
                {"pi_name": {"$regex": _re.escape(t), "$options": "i"}} for t in tokens
            ],
        }
        if institution.strip():
            inst_words = [w for w in institution.strip().split() if len(w) >= 4]
            if inst_words:
                query["pi_institution"] = {
                    "$regex": _re.escape(inst_words[0]), "$options": "i"
                }
        result = self._esafs().update_many(
            query,
            {"$set": {"pi_group": group_name, "updated_at": _now_iso()}},
        )
        return result.modified_count

    def clear_pi_group_assignments(self, group_name: str) -> int:
        result = self._esafs().update_many(
            {"pi_group": group_name},
            {"$set": {"pi_group": "", "updated_at": _now_iso()}},
        )
        return result.modified_count

    def list_users_for_lookup(self, q: str = "") -> list[dict]:
        filt = {}
        if q:
            filt = {"$or": [
                {"first_name": {"$regex": q, "$options": "i"}},
                {"last_name":  {"$regex": q, "$options": "i"}},
                {"email":      {"$regex": q, "$options": "i"}},
            ]}
        pipeline = [
            {"$unwind": "$users"},
            {"$replaceRoot": {"newRoot": "$users"}},
            *(([{"$match": filt}]) if filt else []),
            {"$group": {"_id": "$badge",
                        "badge":       {"$first": "$badge"},
                        "first_name":  {"$first": "$first_name"},
                        "last_name":   {"$first": "$last_name"},
                        "institution": {"$first": "$institution"},
                        "country":     {"$first": "$country"},
                        "state":       {"$first": "$state"},
                        "email":       {"$first": "$email"},
                        "orcid_id":    {"$first": "$orcid_id"}}},
            {"$sort": {"last_name": 1, "first_name": 1}},
            {"$limit": 50 if q else 500},
        ]
        return [
            {k: d.get(k, "") for k in
             ("badge", "first_name", "last_name", "institution",
              "country", "state", "email", "orcid_id")}
            for d in self._esafs().aggregate(pipeline)
        ]

    def upsert_esaf(self, data: dict, now: str) -> str:
        esaf_id = data["esaf_id"]
        existing = self._esafs().find_one(
            {"esaf_id": esaf_id},
            {"notes": 1, "custom_fields": 1, "pi_group": 1, "created_at": 1, "users": 1},
        )

        doc = {
            "esaf_id":        esaf_id,
            "title":          data["title"],
            "description":    data["description"],
            "sector":         data["sector"],
            "beamline":       data["beamline"],
            "year":           data["year"],
            "status":         data["status"],
            "start_date":     data["start_date"],
            "end_date":       data["end_date"],
            "doi":            data.get("doi", ""),
            "pi_badge":        data["pi_badge"],
            "pi_name":         data["pi_name"],
            "pi_institution":  data.get("pi_institution", ""),
            "raw_json":       data["raw_json"],
            "users":          data.get("users", []),
            "funding_sources": data.get("funding_sources", []),
            "last_synced":    now,
            "updated_at":     now,
        }

        if existing:
            doc["notes"]         = existing.get("notes", "")
            doc["custom_fields"] = existing.get("custom_fields", {})
            doc["pi_group"]      = existing.get("pi_group", "")
            doc["created_at"]    = existing.get("created_at", now)
            # Preserve orcid_id / institution set by previous enrichment
            existing_users = {u.get("badge", ""): u for u in (existing.get("users") or [])}
            for u in doc.get("users", []):
                prev = existing_users.get(u.get("badge", ""), {})
                if not u.get("orcid_id") and prev.get("orcid_id"):
                    u["orcid_id"] = prev["orcid_id"]
                if not u.get("institution") and prev.get("institution"):
                    u["institution"] = prev["institution"]
                if not u.get("country") and prev.get("country"):
                    u["country"] = prev["country"]
                if not u.get("state") and prev.get("state"):
                    u["state"] = prev["state"]
            self._esafs().replace_one({"esaf_id": esaf_id}, doc)
            return "updated"
        else:
            doc["notes"]         = ""
            doc["custom_fields"] = {}
            doc["pi_group"]      = ""
            doc["created_at"]    = now
            self._esafs().insert_one(doc)
            return "added"

    # ------------------------------------------------------------------
    # Sync log
    # ------------------------------------------------------------------

    def log_sync(
        self,
        beamlines: str,
        years: str,
        added: int,
        updated: int,
        error: Optional[str] = None,
    ) -> None:
        self._sync_log().insert_one({
            "synced_at":       _now_iso(),
            "beamlines":       beamlines,
            "years":           years,
            "records_added":   added,
            "records_updated": updated,
            "error":           error,
        })

    def get_last_sync(self) -> Optional[dict]:
        doc = self._sync_log().find_one(sort=[("_id", DESCENDING)])
        return self._clean(doc) if doc else None

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        total_esafs = self._esafs().count_documents({})

        by_year = list(self._esafs().aggregate([
            {"$group": {"_id": "$year", "count": {"$sum": 1}}},
            {"$sort":  {"_id": -1}},
            {"$project": {"year": "$_id", "count": 1, "_id": 0}},
        ]))

        tu = list(self._esafs().aggregate([
            {"$project": {"n": {"$size": {"$ifNull": ["$users", []]}}}},
            {"$group": {"_id": None, "total": {"$sum": "$n"}}},
        ]))
        total_users = tu[0]["total"] if tu else 0

        uu = list(self._esafs().aggregate([
            {"$unwind": {"path": "$users", "preserveNullAndEmptyArrays": False}},
            {"$group": {"_id": "$users.badge"}},
            {"$count": "count"},
        ]))
        unique_users = uu[0]["count"] if uu else 0

        by_beamline = list(self._esafs().aggregate([
            {"$group": {"_id": "$beamline", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$project": {"beamline": "$_id", "count": 1, "_id": 0}},
        ]))

        by_status = list(self._esafs().aggregate([
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$project": {"status": "$_id", "count": 1, "_id": 0}},
        ]))

        by_institution = list(self._esafs().aggregate([
            {"$unwind": {"path": "$users", "preserveNullAndEmptyArrays": False}},
            {"$match": {"users.institution": {"$nin": [None, ""]}}},
            {"$group": {
                "_id": "$users.institution",
                "unique_users": {"$addToSet": "$users.badge"},
                "esaf_slots":   {"$sum": 1},
            }},
            {"$project": {
                "institution":  "$_id",
                "unique_users": {"$size": "$unique_users"},
                "esaf_slots":   1,
                "_id": 0,
            }},
            {"$sort": {"unique_users": -1}},
            {"$limit": 30},
        ]))

        by_funding = list(self._esafs().aggregate([
            {"$unwind": {"path": "$funding_sources", "preserveNullAndEmptyArrays": False}},
            {"$group": {"_id": "$funding_sources", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$project": {"source": "$_id", "count": 1, "_id": 0}},
        ]))

        top_users = list(self._esafs().aggregate([
            {"$unwind": {"path": "$users", "preserveNullAndEmptyArrays": False}},
            {"$group": {
                "_id":         "$users.badge",
                "name":        {"$first": {"$concat": ["$users.first_name", " ", "$users.last_name"]}},
                "institution": {"$first": "$users.institution"},
                "experiments": {"$sum": 1},
            }},
            {"$sort": {"experiments": -1}},
            {"$limit": 20},
            {"$project": {"name": 1, "institution": 1, "experiments": 1, "_id": 0}},
        ]))

        return {
            "total_esafs":    total_esafs,
            "total_users":    total_users,
            "unique_users":   unique_users,
            "by_year":        by_year,
            "by_beamline":    by_beamline,
            "by_status":      by_status,
            "by_institution": by_institution,
            "by_funding":     by_funding,
            "top_users":      top_users,
        }

    # ------------------------------------------------------------------
    # Custom field definitions
    # ------------------------------------------------------------------

    def list_field_definitions(self) -> list[dict]:
        return [
            self._clean(d)
            for d in self._field_defs().find().sort("name", ASCENDING)
        ]

    def upsert_field_definition(
        self, name: str, label: str, field_type: str, options: list[str]
    ) -> None:
        self._field_defs().update_one(
            {"name": name},
            {"$set": {"name": name, "label": label, "field_type": field_type, "options": options}},
            upsert=True,
        )

    def delete_field_definition(self, name: str) -> bool:
        return self._field_defs().delete_one({"name": name}).deleted_count > 0

    # ------------------------------------------------------------------
    # Domain affiliation overrides
    # ------------------------------------------------------------------

    def list_domain_overrides(self) -> list[dict]:
        return [
            self._clean(d)
            for d in self._domain_overrides().find().sort("domain", ASCENDING)
        ]

    def set_domain_override(
        self, domain: str, institution: str, country: str, state: str
    ) -> None:
        self._domain_overrides().update_one(
            {"domain": domain},
            {"$set": {
                "domain": domain,
                "institution": institution,
                "country": country,
                "state": state,
            }},
            upsert=True,
        )

    def delete_domain_override(self, domain: str) -> bool:
        return self._domain_overrides().delete_one({"domain": domain}).deleted_count > 0

    def apply_domain_override(
        self, domain: str, institution: str, country: str, state: str
    ) -> int:
        import re
        result = self._esafs().update_many(
            {"users.email": {"$regex": f"@{re.escape(domain)}$", "$options": "i"}},
            {"$set": {
                "users.$[u].institution": institution,
                "users.$[u].country":     country,
                "users.$[u].state":       state,
            }},
            array_filters=[{"u.email": {"$regex": f"@{re.escape(domain)}$", "$options": "i"}}],
        )
        return result.modified_count

    # ------------------------------------------------------------------
    # GUPs
    # ------------------------------------------------------------------

    def _gups(self):
        return self._client[self._db_name]["gups"]

    def list_gups(
        self,
        search: Optional[str] = None,
        run_cycle: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        query: dict = {}
        if run_cycle:
            query["run_cycle"] = run_cycle
        if search:
            query["$or"] = [
                {"title":   {"$regex": search, "$options": "i"}},
                {"pi_name": {"$regex": search, "$options": "i"}},
                {"gup_id":  {"$regex": search, "$options": "i"}},
            ]
        docs = (
            self._gups()
            .find(query, {"_id": 0})
            .sort([("run_cycle", DESCENDING), ("gup_id", DESCENDING)])
            .skip(offset)
            .limit(limit)
        )
        result = []
        for d in docs:
            d["linked_esaf_count"] = self._esafs().count_documents({"gup_id": d["gup_id"]})
            result.append(d)
        return result

    def get_gup(self, gup_id: str) -> Optional[dict]:
        doc = self._gups().find_one({"gup_id": gup_id}, {"_id": 0})
        if doc is None:
            return None
        doc["linked_esaf_count"] = self._esafs().count_documents({"gup_id": gup_id})
        return doc

    def count_gups(
        self,
        search: Optional[str] = None,
        run_cycle: Optional[str] = None,
    ) -> int:
        query: dict = {}
        if run_cycle:
            query["run_cycle"] = run_cycle
        if search:
            query["$or"] = [
                {"title":   {"$regex": search, "$options": "i"}},
                {"pi_name": {"$regex": search, "$options": "i"}},
                {"gup_id":  {"$regex": search, "$options": "i"}},
            ]
        return self._gups().count_documents(query)

    def upsert_gup(self, data: dict, now: str) -> str:
        gup_id = data["gup_id"]
        existing = self._gups().find_one({"gup_id": gup_id})
        doc = {
            "gup_id":        gup_id,
            "title":         data.get("title", ""),
            "pi_name":       data.get("pi_name", ""),
            "pi_institution": data.get("pi_institution", ""),
            "run_cycle":     data.get("run_cycle", ""),
            "proposal_type": data.get("proposal_type", ""),
            "primary_area":  data.get("primary_area", ""),
            "keywords":      data.get("keywords", ""),
            "abstract":      data.get("abstract", ""),
            "beamlines":     data.get("beamlines", ""),
            "status":        data.get("status", ""),
            "submitted_at":  data.get("submitted_at", ""),
            "pdf_path":      data.get("pdf_path", ""),
            "raw_fields":    data.get("raw_fields", {}),
            "funding_sources": data.get("funding_sources", []),
            "updated_at":    now,
        }
        if existing:
            doc["notes"]      = existing.get("notes", "")
            doc["created_at"] = existing.get("created_at", now)
            self._gups().replace_one({"gup_id": gup_id}, doc)
            return "updated"
        else:
            doc["notes"]      = ""
            doc["created_at"] = now
            self._gups().insert_one(doc)
            return "added"

    def delete_gup(self, gup_id: str) -> bool:
        return self._gups().delete_one({"gup_id": gup_id}).deleted_count > 0

    def get_esafs_for_gup(self, gup_id: str) -> list[dict]:
        docs = self._esafs().find(
            {"gup_id": gup_id},
            {"_id": 0, "esaf_id": 1, "title": 1, "beamline": 1,
             "year": 1, "status": 1, "start_date": 1, "end_date": 1, "pi_name": 1},
        ).sort("start_date", ASCENDING)
        return list(docs)

    def update_esaf_pdf(self, esaf_id: str, gup_id: str, pdf_path: str) -> None:
        self._esafs().update_one(
            {"esaf_id": esaf_id},
            {"$set": {"gup_id": gup_id, "pdf_path": pdf_path, "updated_at": _now_iso()}},
        )

    def propagate_gup_funding(self, gup_id: str, funding_strings: list[str]) -> int:
        result = self._esafs().update_many(
            {"gup_id": gup_id},
            {"$set": {"funding_sources": funding_strings, "updated_at": _now_iso()}},
        )
        return result.modified_count

    def get_gup_run_cycles(self) -> list[str]:
        cycles = sorted(
            (c for c in self._gups().distinct("run_cycle") if c),
            reverse=True,
        )
        return cycles

    def list_distinct_institutions(self) -> list[str]:
        db = self._client[self._db_name]
        from_users = db["users"].distinct("institution")
        from_esafs = self._esafs().distinct("pi_institution")
        from_groups = self._pi_groups().distinct("institution")
        return sorted(set(
            i for i in (from_users + from_esafs + from_groups) if i
        ))
