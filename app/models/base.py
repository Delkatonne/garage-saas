"""Briques communes des modèles.

RÈGLE D'OR : toute table métier hérite de `TenantMixin` (colonne `garage_id`
obligatoire). Le filtrage par garage est ensuite appliqué automatiquement à
chaque requête (voir app/tenancy.py).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Uuid
from sqlalchemy.orm import declared_attr

from app.extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt):
    """SQLite renvoie des datetimes naïfs : on les considère comme UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class UUIDPk:
    id = db.Column(Uuid, primary_key=True, default=uuid.uuid4)


class Timestamps:
    created_at = db.Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class TenantMixin:
    @declared_attr
    def garage_id(cls):
        return db.Column(
            Uuid, ForeignKey("garages.id", ondelete="CASCADE"), nullable=False, index=True
        )
