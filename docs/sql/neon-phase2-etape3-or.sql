-- Garage SaaS - Phase 2, étape 3 : ordres de réparation
-- (équivalent de la migration Alembic e5a9c2d7f184)
-- À coller en entier dans l'éditeur SQL de Neon, puis cliquer sur "Run".
-- À exécuter UNE SEULE FOIS, après les fichiers précédents (phase1, étape 1, étape 2 devis).

BEGIN;

CREATE TABLE ordres_reparation (
    numero VARCHAR(40) NOT NULL,
    client_id UUID NOT NULL,
    vehicule_id UUID NOT NULL,
    statut VARCHAR(20) NOT NULL,
    urgent BOOLEAN NOT NULL,
    motif VARCHAR(255) NOT NULL,
    symptomes TEXT,
    kilometrage_entree INTEGER,
    niveau_carburant INTEGER,
    etat_arrivee TEXT,
    diagnostic TEXT,
    travaux_effectues TEXT,
    mecanicien_id UUID,
    date_entree TIMESTAMP WITH TIME ZONE NOT NULL,
    date_sortie_prevue TIMESTAMP WITH TIME ZONE,
    date_livraison TIMESTAMP WITH TIME ZONE,
    signature_nom VARCHAR(120),
    signature_date TIMESTAMP WITH TIME ZONE,
    signature_ip VARCHAR(45),
    cree_par_id UUID,
    id UUID NOT NULL,
    garage_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT ordres_reparation_pkey PRIMARY KEY (id),
    CONSTRAINT ordres_reparation_client_id_fkey FOREIGN KEY (client_id) REFERENCES clients (id),
    CONSTRAINT ordres_reparation_cree_par_id_fkey FOREIGN KEY (cree_par_id) REFERENCES users (id) ON DELETE SET NULL,
    CONSTRAINT ordres_reparation_garage_id_fkey FOREIGN KEY (garage_id) REFERENCES garages (id) ON DELETE CASCADE,
    CONSTRAINT ordres_reparation_mecanicien_id_fkey FOREIGN KEY (mecanicien_id) REFERENCES users (id) ON DELETE SET NULL,
    CONSTRAINT ordres_reparation_vehicule_id_fkey FOREIGN KEY (vehicule_id) REFERENCES vehicules (id)
);
CREATE INDEX ix_ordres_reparation_client_id ON ordres_reparation (client_id);
CREATE INDEX ix_ordres_reparation_garage_id ON ordres_reparation (garage_id);
CREATE INDEX ix_ordres_reparation_vehicule_id ON ordres_reparation (vehicule_id);
CREATE INDEX ix_or_garage_statut ON ordres_reparation (garage_id, statut);
CREATE UNIQUE INDEX uq_or_garage_numero ON ordres_reparation (garage_id, numero);

CREATE TABLE or_statut_historique (
    or_id UUID NOT NULL,
    ancien_statut VARCHAR(20),
    nouveau_statut VARCHAR(20) NOT NULL,
    user_id UUID,
    commentaire VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    id UUID NOT NULL,
    garage_id UUID NOT NULL,
    CONSTRAINT or_statut_historique_pkey PRIMARY KEY (id),
    CONSTRAINT or_statut_historique_garage_id_fkey FOREIGN KEY (garage_id) REFERENCES garages (id) ON DELETE CASCADE,
    CONSTRAINT or_statut_historique_or_id_fkey FOREIGN KEY (or_id) REFERENCES ordres_reparation (id) ON DELETE CASCADE,
    CONSTRAINT or_statut_historique_user_id_fkey FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX ix_or_statut_historique_garage_id ON or_statut_historique (garage_id);
CREATE INDEX ix_or_statut_historique_or_id ON or_statut_historique (or_id);

-- Lien devis -> ordre de réparation (facultatif)
ALTER TABLE devis ADD COLUMN or_id UUID;
ALTER TABLE devis ADD CONSTRAINT devis_or_id_fkey FOREIGN KEY (or_id) REFERENCES ordres_reparation (id);
CREATE INDEX ix_devis_or_id ON devis (or_id);

-- Marque la migration comme appliquée
UPDATE alembic_version SET version_num = 'e5a9c2d7f184' WHERE version_num = 'd4f8b1a6c093';

COMMIT;
