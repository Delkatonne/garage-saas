"""phase 2 etape 3 : ordres de reparation et lien devis -> ordre

Revision ID: e5a9c2d7f184
Revises: d4f8b1a6c093
Create Date: 2026-11-03 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5a9c2d7f184'
down_revision = 'd4f8b1a6c093'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ordres_reparation',
    sa.Column('numero', sa.String(length=40), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('vehicule_id', sa.Uuid(), nullable=False),
    sa.Column('statut', sa.String(length=20), nullable=False),
    sa.Column('urgent', sa.Boolean(), nullable=False),
    sa.Column('motif', sa.String(length=255), nullable=False),
    sa.Column('symptomes', sa.Text(), nullable=True),
    sa.Column('kilometrage_entree', sa.Integer(), nullable=True),
    sa.Column('niveau_carburant', sa.Integer(), nullable=True),
    sa.Column('etat_arrivee', sa.Text(), nullable=True),
    sa.Column('diagnostic', sa.Text(), nullable=True),
    sa.Column('travaux_effectues', sa.Text(), nullable=True),
    sa.Column('mecanicien_id', sa.Uuid(), nullable=True),
    sa.Column('date_entree', sa.DateTime(timezone=True), nullable=False),
    sa.Column('date_sortie_prevue', sa.DateTime(timezone=True), nullable=True),
    sa.Column('date_livraison', sa.DateTime(timezone=True), nullable=True),
    sa.Column('signature_nom', sa.String(length=120), nullable=True),
    sa.Column('signature_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('signature_ip', sa.String(length=45), nullable=True),
    sa.Column('cree_par_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('garage_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ),
    sa.ForeignKeyConstraint(['cree_par_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['garage_id'], ['garages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['mecanicien_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vehicule_id'], ['vehicules.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ordres_reparation_client_id'), 'ordres_reparation', ['client_id'], unique=False)
    op.create_index(op.f('ix_ordres_reparation_garage_id'), 'ordres_reparation', ['garage_id'], unique=False)
    op.create_index(op.f('ix_ordres_reparation_vehicule_id'), 'ordres_reparation', ['vehicule_id'], unique=False)
    op.create_index('ix_or_garage_statut', 'ordres_reparation', ['garage_id', 'statut'], unique=False)
    op.create_index('uq_or_garage_numero', 'ordres_reparation', ['garage_id', 'numero'], unique=True)

    op.create_table('or_statut_historique',
    sa.Column('or_id', sa.Uuid(), nullable=False),
    sa.Column('ancien_statut', sa.String(length=20), nullable=True),
    sa.Column('nouveau_statut', sa.String(length=20), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('commentaire', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('garage_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['garage_id'], ['garages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['or_id'], ['ordres_reparation.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_or_statut_historique_garage_id'), 'or_statut_historique', ['garage_id'], unique=False)
    op.create_index(op.f('ix_or_statut_historique_or_id'), 'or_statut_historique', ['or_id'], unique=False)

    op.add_column('devis', sa.Column('or_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('devis_or_id_fkey', 'devis', 'ordres_reparation', ['or_id'], ['id'])
    op.create_index(op.f('ix_devis_or_id'), 'devis', ['or_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_devis_or_id'), table_name='devis')
    op.drop_constraint('devis_or_id_fkey', 'devis', type_='foreignkey')
    op.drop_column('devis', 'or_id')
    op.drop_index(op.f('ix_or_statut_historique_or_id'), table_name='or_statut_historique')
    op.drop_index(op.f('ix_or_statut_historique_garage_id'), table_name='or_statut_historique')
    op.drop_table('or_statut_historique')
    op.drop_index('uq_or_garage_numero', table_name='ordres_reparation')
    op.drop_index('ix_or_garage_statut', table_name='ordres_reparation')
    op.drop_index(op.f('ix_ordres_reparation_vehicule_id'), table_name='ordres_reparation')
    op.drop_index(op.f('ix_ordres_reparation_garage_id'), table_name='ordres_reparation')
    op.drop_index(op.f('ix_ordres_reparation_client_id'), table_name='ordres_reparation')
    op.drop_table('ordres_reparation')
