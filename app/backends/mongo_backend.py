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
        self._field_defs().create_index([("name", ASCENDING)], unique=True)
        self._domain_overrides().create_index([("domain", ASCENDING)], unique=True)
        self._pi_groups().create_index([("name", ASCENDING)], unique=True)

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

    def list_pi_groups(self) -> list[str]:
        return sorted(
            d["name"] for d in self._pi_groups().find({}, {"name": 1})
        )

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
