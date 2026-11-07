"""phase 2 etape 4 : factures, paiements, recus, avoirs

Revision ID: f6b3d8e1a275
Revises: e5a9c2d7f184
Create Date: 2026-11-04 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f6b3d8e1a275'
down_revision = 'e5a9c2d7f184'
branch_labels = None
depends_on = None


def _num(precision, scale):
    return sa.Numeric(precision=precision, scale=scale)


def upgrade():
    op.create_table('factures',
    sa.Column('numero', sa.String(length=40), nullable=True),
    sa.Column('or_id', sa.Uuid(), nullable=True),
    sa.Column('devis_id', sa.Uuid(), nullable=True),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('vehicule_id', sa.Uuid(), nullable=True),
    sa.Column('statut', sa.String(length=20), nullable=False),
    sa.Column('emise_le', sa.DateTime(timezone=True), nullable=True),
    sa.Column('echeance', sa.DateTime(timezone=True), nullable=True),
    sa.Column('devise', sa.String(length=3), nullable=False),
    sa.Column('devise_decimales', sa.Integer(), nullable=False),
    sa.Column('tva_active', sa.Boolean(), nullable=False),
    sa.Column('tva_taux', _num(5, 2), nullable=False),
    sa.Column('sous_total_ht', _num(14, 3), nullable=False),
    sa.Column('remise_globale', _num(14, 3), nullable=False),
    sa.Column('total_ht', _num(14, 3), nullable=False),
    sa.Column('total_tva', _num(14, 3), nullable=False),
    sa.Column('total_ttc', _num(14, 3), nullable=False),
    sa.Column('conditions', sa.Text(), nullable=True),
    sa.Column('snapshot', sa.JSON(), nullable=True),
    sa.Column('hash_integrite', sa.String(length=64), nullable=True),
    sa.Column('annulee_le', sa.DateTime(timezone=True), nullable=True),
    sa.Column('motif_annulation', sa.String(length=255), nullable=True),
    sa.Column('cree_par_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('garage_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ),
    sa.ForeignKeyConstraint(['cree_par_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['devis_id'], ['devis.id'], ),
    sa.ForeignKeyConstraint(['garage_id'], ['garages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['or_id'], ['ordres_reparation.id'], ),
    sa.ForeignKeyConstraint(['vehicule_id'], ['vehicules.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_factures_client_id'), 'factures', ['client_id'], unique=False)
    op.create_index(op.f('ix_factures_devis_id'), 'factures', ['devis_id'], unique=False)
    op.create_index(op.f('ix_factures_garage_id'), 'factures', ['garage_id'], unique=False)
    op.create_index(op.f('ix_factures_or_id'), 'factures', ['or_id'], unique=False)
    op.create_index(op.f('ix_factures_vehicule_id'), 'factures', ['vehicule_id'], unique=False)
    op.create_index('ix_factures_garage_statut', 'factures', ['garage_id', 'statut'], unique=False)
    op.create_index('uq_factures_garage_numero', 'factures', ['garage_id', 'numero'], unique=True)

    op.create_table('facture_lignes',
    sa.Column('facture_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('designation', sa.String(length=200), nullable=False),
    sa.Column('unite', sa.String(length=20), nullable=True),
    sa.Column('quantite', _num(10, 2), nullable=False),
    sa.Column('prix_unitaire', _num(14, 3), nullable=False),
    sa.Column('remise_pct', _num(5, 2), nullable=False),
    sa.Column('total_ht', _num(14, 3), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('garage_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['facture_id'], ['factures.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['garage_id'], ['garages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_facture_lignes_facture_id'), 'facture_lignes', ['facture_id'], unique=False)
    op.create_index(op.f('ix_facture_lignes_garage_id'), 'facture_lignes', ['garage_id'], unique=False)

    op.create_table('paiements',
    sa.Column('facture_id', sa.Uuid(), nullable=True),
    sa.Column('or_id', sa.Uuid(), nullable=True),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('montant', _num(14, 3), nullable=False),
    sa.Column('devise', sa.String(length=3), nullable=False),
    sa.Column('moyen', sa.String(length=20), nullable=False),
    sa.Column('reference_transaction', sa.String(length=100), nullable=True),
    sa.Column('date_paiement', sa.DateTime(timezone=True), nullable=False),
    sa.Column('encaisse_par_id', sa.Uuid(), nullable=True),
    sa.Column('statut', sa.String(length=10), nullable=False),
    sa.Column('motif_annulation', sa.String(length=255), nullable=True),
    sa.Column('annule_le', sa.DateTime(timezone=True), nullable=True),
    sa.Column('idempotency_key', sa.String(length=80), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('garage_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ),
    sa.ForeignKeyConstraint(['encaisse_par_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['facture_id'], ['factures.id'], ),
    sa.ForeignKeyConstraint(['garage_id'], ['garages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['or_id'], ['ordres_reparation.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_paiements_client_id'), 'paiements', ['client_id'], unique=False)
    op.create_index(op.f('ix_paiements_facture_id'), 'paiements', ['facture_id'], unique=False)
    op.create_index(op.f('ix_paiements_garage_id'), 'paiements', ['garage_id'], unique=False)
    op.create_index(op.f('ix_paiements_or_id'), 'paiements', ['or_id'], unique=False)
    op.create_index('ix_paiements_garage_date', 'paiements', ['garage_id', 'date_paiement'], unique=False)
    op.create_index('uq_paiements_garage_idem', 'paiements', ['garage_id', 'idempotency_key'], unique=True)

    op.create_table('recus',
    sa.Column('numero', sa.String(length=40), nullable=False),
    sa.Column('paiement_id', sa.Uuid(), nullable=False),
    sa.Column('solde_restant', _num(14, 3), nullable=True),
    sa.Column('snapshot', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('garage_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['garage_id'], ['garages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['paiement_id'], ['paiements.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_recus_garage_id'), 'recus', ['garage_id'], unique=False)
    op.create_index('uq_recus_garage_numero', 'recus', ['garage_id', 'numero'], unique=True)
    op.create_index('uq_recus_paiement', 'recus', ['paiement_id'], unique=True)

    op.create_table('avoirs',
    sa.Column('numero', sa.String(length=40), nullable=False),
    sa.Column('facture_id', sa.Uuid(), nullable=False),
    sa.Column('motif', sa.String(length=255), nullable=False),
    sa.Column('devise', sa.String(length=3), nullable=False),
    sa.Column('total_ht', _num(14, 3), nullable=False),
    sa.Column('total_tva', _num(14, 3), nullable=False),
    sa.Column('total_ttc', _num(14, 3), nullable=False),
    sa.Column('emis_le', sa.DateTime(timezone=True), nullable=False),
    sa.Column('cree_par_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('garage_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['cree_par_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['facture_id'], ['factures.id'], ),
    sa.ForeignKeyConstraint(['garage_id'], ['garages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_avoirs_garage_id'), 'avoirs', ['garage_id'], unique=False)
    op.create_index('uq_avoirs_garage_numero', 'avoirs', ['garage_id', 'numero'], unique=True)
    op.create_index('uq_avoirs_facture', 'avoirs', ['facture_id'], unique=True)


def downgrade():
    op.drop_table('avoirs')
    op.drop_table('recus')
    op.drop_table('paiements')
    op.drop_table('facture_lignes')
    op.drop_table('factures')
