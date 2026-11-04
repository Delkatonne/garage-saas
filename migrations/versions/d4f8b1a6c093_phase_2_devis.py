"""phase 2 etape 2 : devis, lignes de devis, sequences de numerotation

Revision ID: d4f8b1a6c093
Revises: c7d2a9e4b153
Create Date: 2026-11-02 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4f8b1a6c093'
down_revision = 'c7d2a9e4b153'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sequences_documents',
    sa.Column('type', sa.String(length=10), nullable=False),
    sa.Column('annee', sa.Integer(), nullable=False),
    sa.Column('dernier_numero', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('garage_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['garage_id'], ['garages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sequences_documents_garage_id'), 'sequences_documents', ['garage_id'], unique=False)
    op.create_index('uq_sequences_garage_type_annee', 'sequences_documents', ['garage_id', 'type', 'annee'], unique=True)

    op.create_table('devis',
    sa.Column('numero', sa.String(length=40), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('devis_parent_id', sa.Uuid(), nullable=True),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('vehicule_id', sa.Uuid(), nullable=True),
    sa.Column('statut', sa.String(length=20), nullable=False),
    sa.Column('date_emission', sa.DateTime(timezone=True), nullable=True),
    sa.Column('date_validite', sa.DateTime(timezone=True), nullable=True),
    sa.Column('devise', sa.String(length=3), nullable=False),
    sa.Column('devise_decimales', sa.Integer(), nullable=False),
    sa.Column('tva_active', sa.Boolean(), nullable=False),
    sa.Column('tva_taux', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('sous_total_ht', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('remise_globale', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('total_ht', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('total_tva', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('total_ttc', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('conditions', sa.Text(), nullable=True),
    sa.Column('token_public_hash', sa.String(length=64), nullable=True),
    sa.Column('accepte_le', sa.DateTime(timezone=True), nullable=True),
    sa.Column('acceptation_nom', sa.String(length=120), nullable=True),
    sa.Column('acceptation_mode', sa.String(length=20), nullable=True),
    sa.Column('acceptation_ip', sa.String(length=45), nullable=True),
    sa.Column('refuse_le', sa.DateTime(timezone=True), nullable=True),
    sa.Column('refus_motif', sa.String(length=255), nullable=True),
    sa.Column('cree_par_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('garage_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ),
    sa.ForeignKeyConstraint(['cree_par_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['devis_parent_id'], ['devis.id'], ),
    sa.ForeignKeyConstraint(['garage_id'], ['garages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicule_id'], ['vehicules.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_devis_client_id'), 'devis', ['client_id'], unique=False)
    op.create_index(op.f('ix_devis_garage_id'), 'devis', ['garage_id'], unique=False)
    op.create_index(op.f('ix_devis_vehicule_id'), 'devis', ['vehicule_id'], unique=False)
    op.create_index('ix_devis_garage_statut', 'devis', ['garage_id', 'statut'], unique=False)
    op.create_index('uq_devis_garage_numero', 'devis', ['garage_id', 'numero'], unique=True)
    op.create_index('uq_devis_token', 'devis', ['token_public_hash'], unique=True)

    op.create_table('devis_lignes',
    sa.Column('devis_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('designation', sa.String(length=200), nullable=False),
    sa.Column('unite', sa.String(length=20), nullable=True),
    sa.Column('quantite', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('prix_unitaire', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('remise_pct', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('total_ht', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('garage_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['devis_id'], ['devis.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['garage_id'], ['garages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_devis_lignes_devis_id'), 'devis_lignes', ['devis_id'], unique=False)
    op.create_index(op.f('ix_devis_lignes_garage_id'), 'devis_lignes', ['garage_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_devis_lignes_garage_id'), table_name='devis_lignes')
    op.drop_index(op.f('ix_devis_lignes_devis_id'), table_name='devis_lignes')
    op.drop_table('devis_lignes')
    op.drop_index('uq_devis_token', table_name='devis')
    op.drop_index('uq_devis_garage_numero', table_name='devis')
    op.drop_index('ix_devis_garage_statut', table_name='devis')
    op.drop_index(op.f('ix_devis_vehicule_id'), table_name='devis')
    op.drop_index(op.f('ix_devis_garage_id'), table_name='devis')
    op.drop_index(op.f('ix_devis_client_id'), table_name='devis')
    op.drop_table('devis')
    op.drop_index('uq_sequences_garage_type_annee', table_name='sequences_documents')
    op.drop_index(op.f('ix_sequences_documents_garage_id'), table_name='sequences_documents')
    op.drop_table('sequences_documents')
