"""Pydantic v2 models shared across all backends."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class ESAFUser(BaseModel):
    badge: str = ""
    first_name: str = ""
    last_name: str = ""
    institution: str = ""
    email: str = ""
    role: str = "user"
    raw_json: dict = Field(default_factory=dict)


class ESAFRecord(BaseModel):
    esaf_id: str
    title: str = ""
    description: str = ""
    sector: str = ""
    beamline: str = ""
    year: int = 0
    status: str = ""
    start_date: str = ""
    end_date: str = ""
    doi: str = ""
    pi_badge: str = ""
    pi_name: str = ""
    raw_json: dict = Field(default_factory=dict)
    notes: str = ""
    custom_fields: dict = Field(default_factory=dict)
    last_synced: str = ""
    created_at: str = ""
    updated_at: str = ""
    users: list[ESAFUser] = Field(default_factory=list)
    funding_sources: list[str] = Field(default_factory=list)
    user_count: int = 0          # populated by list_esafs(), not stored


class SyncLog(BaseModel):
    id: int = 0
    synced_at: str = ""
    beamlines: str = ""
    years: str = ""
    records_added: int = 0
    records_updated: int = 0
    error: Optional[str] = None


class FieldDefinition(BaseModel):
    name: str
    label: str
    field_type: str = "text"
    options: list[str] = Field(default_factory=list)
    created_at: str = ""
