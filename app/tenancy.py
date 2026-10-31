"""Isolation multi-garages : filtrage AUTOMATIQUE et FAIL-CLOSED.

Principe
--------
* `g.garage_id` est posé uniquement à partir de l'utilisateur authentifié (base de
  données + JWT), JAMAIS à partir d'une donnée fournie par le client.
* Pendant une requête HTTP, chaque SELECT / UPDATE / DELETE touchant une table
  `TenantMixin` reçoit automatiquement `WHERE garage_id = :garage_id`.
* Sans garage authentifié, les tables métier apparaissent VIDES (deny par défaut).
  Les rares endroits qui ont besoin d'un accès global (connexion, jetons, back-office)
  l'indiquent explicitement avec `with unscoped():`.
* À l'écriture, un objet d'un autre garage (ou sans contexte) est refusé avant le flush.
* Hors requête HTTP (CLI, migrations, tests unitaires) aucun filtre n'est appliqué.
"""
from contextlib import contextmanager

import sqlalchemy as sa
from flask import g, has_request_context
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, with_loader_criteria

from .models.base import TenantMixin


class TenantViolation(Exception):
    """Tentative d'accès ou d'écriture hors du garage courant."""


def set_garage(garage_id):
    g.garage_id = garage_id


def current_garage_id():
    return g.get("garage_id") if has_request_context() else None


@contextmanager
def unscoped():
    """Désactive le filtrage tenant pour un bloc précis (à utiliser avec parcimonie)."""
    if not has_request_context():
        yield
        return
    previous = g.get("_unscoped", False)
    g._unscoped = True
    try:
        yield
    finally:
        g._unscoped = previous


def _mode():
    if not has_request_context() or g.get("_unscoped", False):
        return "off", None
    gid = g.get("garage_id")
    return ("tenant", gid) if gid else ("deny", None)


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_filter(state):
    if not (state.is_select or state.is_update or state.is_delete):
        return
    mode, gid = _mode()
    if mode == "off":
        return
    if mode == "deny":
        criteria = lambda cls: sa.false()  # noqa: E731
    else:
        criteria = lambda cls: cls.garage_id == gid  # noqa: E731
    state.statement = state.statement.options(
        with_loader_criteria(
            TenantMixin,
            criteria,
            include_aliases=True,
            propagate_to_loaders=state.is_select,
        )
    )


@event.listens_for(Session, "before_flush")
def _guard_writes(session, flush_context, instances):
    mode, gid = _mode()
    if mode == "off":
        return
    for obj in list(session.new):
        if isinstance(obj, TenantMixin):
            if mode == "deny":
                raise TenantViolation("Écriture de données métier sans garage authentifié.")
            if obj.garage_id is None:
                obj.garage_id = gid
            elif obj.garage_id != gid:
                raise TenantViolation("Écriture dans un autre garage refusée.")
    for obj in list(session.dirty) + list(session.deleted):
        if isinstance(obj, TenantMixin):
            if mode == "deny" or obj.garage_id != gid:
                raise TenantViolation("Modification d'un objet d'un autre garage refusée.")
            if inspect(obj).attrs.garage_id.history.has_changes():
                raise TenantViolation("Le garage_id ne peut pas être modifié.")
