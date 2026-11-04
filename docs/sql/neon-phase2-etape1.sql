-- Garage SaaS - Phase 2, étape 1 : clients et véhicules
-- (équivalent de la migration Alembic c7d2a9e4b153)
-- À coller en entier dans l'éditeur SQL de Neon, puis cliquer sur "Run".
-- À exécuter UNE SEULE FOIS, après neon-phase1.sql.

BEGIN;

CREATE TABLE clients (
    type VARCHAR(20) NOT NULL,
    nom VARCHAR(120),
    prenom VARCHAR(120),
    raison_sociale VARCHAR(160),
    telephone VARCHAR(30),
    whatsapp VARCHAR(30),
    email VARCHAR(255),
    adresse VARCHAR(255),
    ifu VARCHAR(50),
    notes TEXT,
    actif BOOLEAN NOT NULL,
    id UUID NOT NULL,
    garage_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT clients_pkey PRIMARY KEY (id),
    CONSTRAINT clients_garage_id_fkey FOREIGN KEY (garage_id) REFERENCES garages (id) ON DELETE CASCADE
);
CREATE INDEX ix_clients_garage_id ON clients (garage_id);
CREATE INDEX ix_clients_garage_telephone ON clients (garage_id, telephone);
CREATE INDEX ix_clients_garage_nom ON clients (garage_id, nom);

CREATE TABLE vehicules (
    type VARCHAR(20) NOT NULL,
    marque VARCHAR(80) NOT NULL,
    modele VARCHAR(80) NOT NULL,
    version VARCHAR(80),
    immatriculation VARCHAR(20),
    immatriculation_cle VARCHAR(20),
    vin VARCHAR(30),
    annee INTEGER,
    couleur VARCHAR(40),
    carburant VARCHAR(20),
    cylindree_cc INTEGER,
    kilometrage_actuel INTEGER,
    notes TEXT,
    actif BOOLEAN NOT NULL,
    id UUID NOT NULL,
    garage_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT vehicules_pkey PRIMARY KEY (id),
    CONSTRAINT vehicules_garage_id_fkey FOREIGN KEY (garage_id) REFERENCES garages (id) ON DELETE CASCADE
);
CREATE INDEX ix_vehicules_garage_id ON vehicules (garage_id);
CREATE UNIQUE INDEX uq_vehicules_garage_immat ON vehicules (garage_id, immatriculation_cle);
CREATE UNIQUE INDEX uq_vehicules_garage_vin ON vehicules (garage_id, vin) WHERE vin IS NOT NULL;

CREATE TABLE vehicule_proprietaires (
    vehicule_id UUID NOT NULL,
    client_id UUID NOT NULL,
    date_debut TIMESTAMP WITH TIME ZONE NOT NULL,
    date_fin TIMESTAMP WITH TIME ZONE,
    id UUID NOT NULL,
    garage_id UUID NOT NULL,
    CONSTRAINT vehicule_proprietaires_pkey PRIMARY KEY (id),
    CONSTRAINT vehicule_proprietaires_client_id_fkey FOREIGN KEY (client_id) REFERENCES clients (id),
    CONSTRAINT vehicule_proprietaires_garage_id_fkey FOREIGN KEY (garage_id) REFERENCES garages (id) ON DELETE CASCADE,
    CONSTRAINT vehicule_proprietaires_vehicule_id_fkey FOREIGN KEY (vehicule_id) REFERENCES vehicules (id) ON DELETE CASCADE
);
CREATE INDEX ix_vehicule_proprietaires_client_id ON vehicule_proprietaires (client_id);
CREATE INDEX ix_vehicule_proprietaires_garage_id ON vehicule_proprietaires (garage_id);
CREATE INDEX ix_vehicule_proprietaires_vehicule_id ON vehicule_proprietaires (vehicule_id);
-- Une seule ligne "propriétaire actuel" (date_fin vide) par véhicule
CREATE UNIQUE INDEX uq_vehicule_proprietaire_ouvert ON vehicule_proprietaires (vehicule_id) WHERE date_fin IS NULL;

-- Marque la migration comme appliquée (suite de la Phase 1)
UPDATE alembic_version SET version_num = 'c7d2a9e4b153' WHERE version_num = '86df1e0c850e';

COMMIT;
