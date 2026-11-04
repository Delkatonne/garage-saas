-- Garage SaaS - Phase 2, étape 2 : devis
-- (équivalent de la migration Alembic d4f8b1a6c093)
-- À coller en entier dans l'éditeur SQL de Neon, puis cliquer sur "Run".
-- À exécuter UNE SEULE FOIS, après neon-phase1.sql et neon-phase2-etape1.sql.

BEGIN;

-- Compteurs de numérotation (DEV-2026-0001...) : un par garage, type et année
CREATE TABLE sequences_documents (
    type VARCHAR(10) NOT NULL,
    annee INTEGER NOT NULL,
    dernier_numero INTEGER NOT NULL,
    id UUID NOT NULL,
    garage_id UUID NOT NULL,
    CONSTRAINT sequences_documents_pkey PRIMARY KEY (id),
    CONSTRAINT sequences_documents_garage_id_fkey FOREIGN KEY (garage_id) REFERENCES garages (id) ON DELETE CASCADE
);
CREATE INDEX ix_sequences_documents_garage_id ON sequences_documents (garage_id);
CREATE UNIQUE INDEX uq_sequences_garage_type_annee ON sequences_documents (garage_id, type, annee);

CREATE TABLE devis (
    numero VARCHAR(40),
    version INTEGER NOT NULL,
    devis_parent_id UUID,
    client_id UUID NOT NULL,
    vehicule_id UUID,
    statut VARCHAR(20) NOT NULL,
    date_emission TIMESTAMP WITH TIME ZONE,
    date_validite TIMESTAMP WITH TIME ZONE,
    devise VARCHAR(3) NOT NULL,
    devise_decimales INTEGER NOT NULL,
    tva_active BOOLEAN NOT NULL,
    tva_taux NUMERIC(5, 2) NOT NULL,
    sous_total_ht NUMERIC(14, 3) NOT NULL,
    remise_globale NUMERIC(14, 3) NOT NULL,
    total_ht NUMERIC(14, 3) NOT NULL,
    total_tva NUMERIC(14, 3) NOT NULL,
    total_ttc NUMERIC(14, 3) NOT NULL,
    conditions TEXT,
    token_public_hash VARCHAR(64),
    accepte_le TIMESTAMP WITH TIME ZONE,
    acceptation_nom VARCHAR(120),
    acceptation_mode VARCHAR(20),
    acceptation_ip VARCHAR(45),
    refuse_le TIMESTAMP WITH TIME ZONE,
    refus_motif VARCHAR(255),
    cree_par_id UUID,
    id UUID NOT NULL,
    garage_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT devis_pkey PRIMARY KEY (id),
    CONSTRAINT devis_client_id_fkey FOREIGN KEY (client_id) REFERENCES clients (id),
    CONSTRAINT devis_cree_par_id_fkey FOREIGN KEY (cree_par_id) REFERENCES users (id) ON DELETE SET NULL,
    CONSTRAINT devis_devis_parent_id_fkey FOREIGN KEY (devis_parent_id) REFERENCES devis (id),
    CONSTRAINT devis_garage_id_fkey FOREIGN KEY (garage_id) REFERENCES garages (id) ON DELETE CASCADE,
    CONSTRAINT devis_vehicule_id_fkey FOREIGN KEY (vehicule_id) REFERENCES vehicules (id)
);
CREATE INDEX ix_devis_client_id ON devis (client_id);
CREATE INDEX ix_devis_garage_id ON devis (garage_id);
CREATE INDEX ix_devis_vehicule_id ON devis (vehicule_id);
CREATE INDEX ix_devis_garage_statut ON devis (garage_id, statut);
CREATE UNIQUE INDEX uq_devis_garage_numero ON devis (garage_id, numero);
CREATE UNIQUE INDEX uq_devis_token ON devis (token_public_hash);

CREATE TABLE devis_lignes (
    devis_id UUID NOT NULL,
    position INTEGER NOT NULL,
    type VARCHAR(20) NOT NULL,
    designation VARCHAR(200) NOT NULL,
    unite VARCHAR(20),
    quantite NUMERIC(10, 2) NOT NULL,
    prix_unitaire NUMERIC(14, 3) NOT NULL,
    remise_pct NUMERIC(5, 2) NOT NULL,
    total_ht NUMERIC(14, 3) NOT NULL,
    id UUID NOT NULL,
    garage_id UUID NOT NULL,
    CONSTRAINT devis_lignes_pkey PRIMARY KEY (id),
    CONSTRAINT devis_lignes_devis_id_fkey FOREIGN KEY (devis_id) REFERENCES devis (id) ON DELETE CASCADE,
    CONSTRAINT devis_lignes_garage_id_fkey FOREIGN KEY (garage_id) REFERENCES garages (id) ON DELETE CASCADE
);
CREATE INDEX ix_devis_lignes_devis_id ON devis_lignes (devis_id);
CREATE INDEX ix_devis_lignes_garage_id ON devis_lignes (garage_id);

-- Marque la migration comme appliquée
UPDATE alembic_version SET version_num = 'd4f8b1a6c093' WHERE version_num = 'c7d2a9e4b153';

COMMIT;
