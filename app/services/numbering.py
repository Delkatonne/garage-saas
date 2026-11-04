"""Numérotation légale sans trous : DEV-2026-0001, par garage, par type et par année."""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.extensions import db
from app.models import SequenceDocument


def next_number(kind: str, garage_id) -> str:
    """À appeler dans la transaction qui émet le document : le verrou de ligne (FOR UPDATE) est tenu jusqu'au commit,
    donc deux émissions simultanées ne peuvent jamais obtenir le même numéro, et un échec n'en "consomme" aucun."""
    year = datetime.now(timezone.utc).year
    dialect = db.session.get_bind().dialect.name
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    # Crée le compteur s'il n'existe pas (sans erreur si un autre l'a créé entre-temps)
    db.session.execute(
        insert(SequenceDocument.__table__)
        .values(id=uuid.uuid4(), garage_id=garage_id, type=kind, annee=year, dernier_numero=0)
        .on_conflict_do_nothing(index_elements=["garage_id", "type", "annee"])
    )
    row = db.session.scalar(
        sa.select(SequenceDocument)
        .where(SequenceDocument.garage_id == garage_id, SequenceDocument.type == kind, SequenceDocument.annee == year)
        .with_for_update()
    )
    row.dernier_numero += 1
    db.session.flush()
    return f"{kind}-{year}-{row.dernier_numero:04d}"
