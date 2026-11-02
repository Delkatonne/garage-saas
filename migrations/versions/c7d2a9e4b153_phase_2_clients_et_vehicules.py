"""phase 2 etape 1 : clients et vehicules

Revision ID: c7d2a9e4b153
Revises: 86df1e0c850e
Create Date: 2026-11-01 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7d2a9e4b153'
down_revision = '86df1e0c850e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('clients',
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('nom', sa.String(length=120), nullable=True),
    sa.Column('prenom', sa.String(length=120), nullable=True),
    sa.Column('raison_sociale', sa.String(length=160), nullable=True),
    sa.Column('telephone', sa.String(length=30), nullable=True),
    sa.Column('whatsapp', sa.String(length=30), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('adresse', sa.String(length=255), nullable=True),
    sa.Column('ifu', sa.String(length=50), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('actif', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('garage_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['garage_id'], ['garages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_clients_garage_id'), 'clients', ['garage_id'], unique=False)
    op.create_index('ix_clients_garage_telephone', 'clients', ['garage_id', 'telephone'], unique=False)
    op.create_index('ix_clients_garage_nom', 'clients', ['garage_id', 'nom'], unique=False)

    op.create_table('vehicules',
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('marque', sa.String(length=80), nullable=False),
    sa.Column('modele', sa.String(length=80), nullable=False),
    sa.Column('version', sa.String(length=80), nullable=True),
    sa.Column('immatriculation', sa.String(length=20), nullable=True),
    sa.Column('immatriculation_cle', sa.String(length=20), nullable=True),
    sa.Column('vin', sa.String(length=30), nullable=True),
    sa.Column('annee', sa.Integer(), nullable=True),
    sa.Column('couleur', sa.String(length=40), nullable=True),
    sa.Column('carburant', sa.String(length=20), nullable=True),
    sa.Column('cylindree_cc', sa.Integer(), nullable=True),
    sa.Column('kilometrage_actuel', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('actif', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('garage_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['garage_id'], ['garages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vehicules_garage_id'), 'vehicules', ['garage_id'], unique=False)
    op.create_index('uq_vehicules_garage_immat', 'vehicules', ['garage_id', 'immatriculation_cle'], unique=True)
    op.create_index('uq_vehicules_garage_vin', 'vehicules', ['garage_id', 'vin'], unique=True,
                    postgresql_where=sa.text('vin IS NOT NULL'), sqlite_where=sa.text('vin IS NOT NULL'))

    op.create_table('vehicule_proprietaires',
    sa.Column('vehicule_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('date_debut', sa.DateTime(timezone=True), nullable=False),
    sa.Column('date_fin', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('garage_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ),
    sa.ForeignKeyConstraint(['garage_id'], ['garages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicule_id'], ['vehicules.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vehicule_proprietaires_client_id'), 'vehicule_proprietaires', ['client_id'], unique=False)
    op.create_index(op.f('ix_vehicule_proprietaires_garage_id'), 'vehicule_proprietaires', ['garage_id'], unique=False)
    op.create_index(op.f('ix_vehicule_proprietaires_vehicule_id'), 'vehicule_proprietaires', ['vehicule_id'], unique=False)
    op.create_index('uq_vehicule_proprietaire_ouvert', 'vehicule_proprietaires', ['vehicule_id'], unique=True,
                    postgresql_where=sa.text('date_fin IS NULL'), sqlite_where=sa.text('date_fin IS NULL'))


def downgrade():
    op.drop_index('uq_vehicule_proprietaire_ouvert', table_name='vehicule_proprietaires',
                  postgresql_where=sa.text('date_fin IS NULL'), sqlite_where=sa.text('date_fin IS NULL'))
    op.drop_index(op.f('ix_vehicule_proprietaires_vehicule_id'), table_name='vehicule_proprietaires')
    op.drop_index(op.f('ix_vehicule_proprietaires_garage_id'), table_name='vehicule_proprietaires')
    op.drop_index(op.f('ix_vehicule_proprietaires_client_id'), table_name='vehicule_proprietaires')
    op.drop_table('vehicule_proprietaires')
    op.drop_index('uq_vehicules_garage_vin', table_name='vehicules',
                  postgresql_where=sa.text('vin IS NOT NULL'), sqlite_where=sa.text('vin IS NOT NULL'))
    op.drop_index('uq_vehicules_garage_immat', table_name='vehicules')
    op.drop_index(op.f('ix_vehicules_garage_id'), table_name='vehicules')
    op.drop_table('vehicules')
    op.drop_index('ix_clients_garage_nom', table_name='clients')
    op.drop_index('ix_clients_garage_telephone', table_name='clients')
    op.drop_index(op.f('ix_clients_garage_id'), table_name='clients')
    op.drop_table('clients')
