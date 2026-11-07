-- Garage SaaS - Phase 2, étape 4 : factures, paiements, reçus, avoirs
-- (équivalent de la migration Alembic f6b3d8e1a275)
-- À coller en entier dans l'éditeur SQL de Neon, puis cliquer sur "Run".
-- À exécuter UNE SEULE FOIS, après les fichiers précédents (phase1, étape 1, devis, ordres de réparation).

BEGIN;

CREATE TABLE factures (
    numero VARCHAR(40),
    or_id UUID,
    devis_id UUID,
    client_id UUID NOT NULL,
    vehicule_id UUID,
    statut VARCHAR(20) NOT NULL,
    emise_le TIMESTAMP WITH TIME ZONE,
    echeance TIMESTAMP WITH TIME ZONE,
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
    snapshot JSON,
    hash_integrite VARCHAR(64),
    annulee_le TIMESTAMP WITH TIME ZONE,
    motif_annulation VARCHAR(255),
    cree_par_id UUID,
    id UUID NOT NULL,
    garage_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT factures_pkey PRIMARY KEY (id),
    CONSTRAINT factures_client_id_fkey FOREIGN KEY (client_id) REFERENCES clients (id),
    CONSTRAINT factures_cree_par_id_fkey FOREIGN KEY (cree_par_id) REFERENCES users (id) ON DELETE SET NULL,
    CONSTRAINT factures_devis_id_fkey FOREIGN KEY (devis_id) REFERENCES devis (id),
    CONSTRAINT factures_garage_id_fkey FOREIGN KEY (garage_id) REFERENCES garages (id) ON DELETE CASCADE,
    CONSTRAINT factures_or_id_fkey FOREIGN KEY (or_id) REFERENCES ordres_reparation (id),
    CONSTRAINT factures_vehicule_id_fkey FOREIGN KEY (vehicule_id) REFERENCES vehicules (id)
);
CREATE INDEX ix_factures_client_id ON factures (client_id);
CREATE INDEX ix_factures_devis_id ON factures (devis_id);
CREATE INDEX ix_factures_garage_id ON factures (garage_id);
CREATE INDEX ix_factures_or_id ON factures (or_id);
CREATE INDEX ix_factures_vehicule_id ON factures (vehicule_id);
CREATE INDEX ix_factures_garage_statut ON factures (garage_id, statut);
CREATE UNIQUE INDEX uq_factures_garage_numero ON factures (garage_id, numero);

CREATE TABLE facture_lignes (
    facture_id UUID NOT NULL,
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
    CONSTRAINT facture_lignes_pkey PRIMARY KEY (id),
    CONSTRAINT facture_lignes_facture_id_fkey FOREIGN KEY (facture_id) REFERENCES factures (id) ON DELETE CASCADE,
    CONSTRAINT facture_lignes_garage_id_fkey FOREIGN KEY (garage_id) REFERENCES garages (id) ON DELETE CASCADE
);
CREATE INDEX ix_facture_lignes_facture_id ON facture_lignes (facture_id);
CREATE INDEX ix_facture_lignes_garage_id ON facture_lignes (garage_id);

CREATE TABLE paiements (
    facture_id UUID,
    or_id UUID,
    client_id UUID NOT NULL,
    montant NUMERIC(14, 3) NOT NULL,
    devise VARCHAR(3) NOT NULL,
    moyen VARCHAR(20) NOT NULL,
    reference_transaction VARCHAR(100),
    date_paiement TIMESTAMP WITH TIME ZONE NOT NULL,
    encaisse_par_id UUID,
    statut VARCHAR(10) NOT NULL,
    motif_annulation VARCHAR(255),
    annule_le TIMESTAMP WITH TIME ZONE,
    idempotency_key VARCHAR(80),
    id UUID NOT NULL,
    garage_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT paiements_pkey PRIMARY KEY (id),
    CONSTRAINT paiements_client_id_fkey FOREIGN KEY (client_id) REFERENCES clients (id),
    CONSTRAINT paiements_encaisse_par_id_fkey FOREIGN KEY (encaisse_par_id) REFERENCES users (id) ON DELETE SET NULL,
    CONSTRAINT paiements_facture_id_fkey FOREIGN KEY (facture_id) REFERENCES factures (id),
    CONSTRAINT paiements_garage_id_fkey FOREIGN KEY (garage_id) REFERENCES garages (id) ON DELETE CASCADE,
    CONSTRAINT paiements_or_id_fkey FOREIGN KEY (or_id) REFERENCES ordres_reparation (id)
);
CREATE INDEX ix_paiements_client_id ON paiements (client_id);
CREATE INDEX ix_paiements_facture_id ON paiements (facture_id);
CREATE INDEX ix_paiements_garage_id ON paiements (garage_id);
CREATE INDEX ix_paiements_or_id ON paiements (or_id);
CREATE INDEX ix_paiements_garage_date ON paiements (garage_id, date_paiement);
CREATE UNIQUE INDEX uq_paiements_garage_idem ON paiements (garage_id, idempotency_key);

CREATE TABLE recus (
    numero VARCHAR(40) NOT NULL,
    paiement_id UUID NOT NULL,
    solde_restant NUMERIC(14, 3),
    snapshot JSON NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    id UUID NOT NULL,
    garage_id UUID NOT NULL,
    CONSTRAINT recus_pkey PRIMARY KEY (id),
    CONSTRAINT recus_garage_id_fkey FOREIGN KEY (garage_id) REFERENCES garages (id) ON DELETE CASCADE,
    CONSTRAINT recus_paiement_id_fkey FOREIGN KEY (paiement_id) REFERENCES paiements (id)
);
CREATE INDEX ix_recus_garage_id ON recus (garage_id);
CREATE UNIQUE INDEX uq_recus_garage_numero ON recus (garage_id, numero);
CREATE UNIQUE INDEX uq_recus_paiement ON recus (paiement_id);

CREATE TABLE avoirs (
    numero VARCHAR(40) NOT NULL,
    facture_id UUID NOT NULL,
    motif VARCHAR(255) NOT NULL,
    devise VARCHAR(3) NOT NULL,
    total_ht NUMERIC(14, 3) NOT NULL,
    total_tva NUMERIC(14, 3) NOT NULL,
    total_ttc NUMERIC(14, 3) NOT NULL,
    emis_le TIMESTAMP WITH TIME ZONE NOT NULL,
    cree_par_id UUID,
    id UUID NOT NULL,
    garage_id UUID NOT NULL,
    CONSTRAINT avoirs_pkey PRIMARY KEY (id),
    CONSTRAINT avoirs_cree_par_id_fkey FOREIGN KEY (cree_par_id) REFERENCES users (id) ON DELETE SET NULL,
    CONSTRAINT avoirs_facture_id_fkey FOREIGN KEY (facture_id) REFERENCES factures (id),
    CONSTRAINT avoirs_garage_id_fkey FOREIGN KEY (garage_id) REFERENCES garages (id) ON DELETE CASCADE
);
CREATE INDEX ix_avoirs_garage_id ON avoirs (garage_id);
CREATE UNIQUE INDEX uq_avoirs_garage_numero ON avoirs (garage_id, numero);
CREATE UNIQUE INDEX uq_avoirs_facture ON avoirs (facture_id);

-- Marque la migration comme appliquée
UPDATE alembic_version SET version_num = 'f6b3d8e1a275' WHERE version_num = 'e5a9c2d7f184';

COMMIT;
