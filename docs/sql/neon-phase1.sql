-- Garage SaaS - Phase 1 : création des tables (équivalent de la migration Alembic 86df1e0c850e)
-- À coller en entier dans l'éditeur SQL de Neon, puis cliquer sur "Run".
-- À exécuter UNE SEULE FOIS sur une base vide.

BEGIN;

CREATE TABLE garages (
    nom_garage VARCHAR(120) NOT NULL,
    nom_chef_garage VARCHAR(120) NOT NULL,
    email VARCHAR(255) NOT NULL,
    telephone VARCHAR(30),
    adresse VARCHAR(255),
    ville VARCHAR(100),
    pays VARCHAR(2) NOT NULL,
    logo_url VARCHAR(500),
    logo_public_id VARCHAR(255),
    devise VARCHAR(3) NOT NULL,
    devise_decimales INTEGER NOT NULL,
    tva_active BOOLEAN NOT NULL,
    tva_taux NUMERIC(5, 2) NOT NULL,
    ifu VARCHAR(50),
    rccm VARCHAR(50),
    email_verifie BOOLEAN NOT NULL,
    actif BOOLEAN NOT NULL,
    statut_abonnement VARCHAR(20) NOT NULL,
    essai_fin TIMESTAMP WITH TIME ZONE,
    abonnement_fin TIMESTAMP WITH TIME ZONE,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT garages_pkey PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_garages_email ON garages (email);

CREATE TABLE platform_admins (
    email VARCHAR(255) NOT NULL,
    nom VARCHAR(120) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    actif BOOLEAN NOT NULL,
    failed_attempts INTEGER NOT NULL,
    locked_until TIMESTAMP WITH TIME ZONE,
    password_changed_at TIMESTAMP WITH TIME ZONE,
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT platform_admins_pkey PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_platform_admins_email ON platform_admins (email);

CREATE TABLE revoked_tokens (
    jti VARCHAR(64) NOT NULL,
    token_type VARCHAR(10) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE NOT NULL,
    id UUID NOT NULL,
    CONSTRAINT revoked_tokens_pkey PRIMARY KEY (id)
);
CREATE INDEX ix_revoked_tokens_expires_at ON revoked_tokens (expires_at);
CREATE UNIQUE INDEX ix_revoked_tokens_jti ON revoked_tokens (jti);

CREATE TABLE users (
    email VARCHAR(255) NOT NULL,
    nom_complet VARCHAR(120) NOT NULL,
    role VARCHAR(20) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    email_verifie BOOLEAN NOT NULL,
    actif BOOLEAN NOT NULL,
    failed_attempts INTEGER NOT NULL,
    locked_until TIMESTAMP WITH TIME ZONE,
    last_login_at TIMESTAMP WITH TIME ZONE,
    password_changed_at TIMESTAMP WITH TIME ZONE,
    id UUID NOT NULL,
    garage_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT users_pkey PRIMARY KEY (id),
    CONSTRAINT users_garage_id_fkey FOREIGN KEY (garage_id) REFERENCES garages (id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX ix_users_email ON users (email);
CREATE INDEX ix_users_garage_id ON users (garage_id);

CREATE TABLE audit_logs (
    user_id UUID,
    action VARCHAR(60) NOT NULL,
    entity_type VARCHAR(60),
    entity_id VARCHAR(64),
    details JSON,
    ip VARCHAR(45),
    user_agent VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    id UUID NOT NULL,
    garage_id UUID NOT NULL,
    CONSTRAINT audit_logs_pkey PRIMARY KEY (id),
    CONSTRAINT audit_logs_garage_id_fkey FOREIGN KEY (garage_id) REFERENCES garages (id) ON DELETE CASCADE,
    CONSTRAINT audit_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX ix_audit_garage_created ON audit_logs (garage_id, created_at);
CREATE INDEX ix_audit_logs_action ON audit_logs (action);
CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);
CREATE INDEX ix_audit_logs_garage_id ON audit_logs (garage_id);

CREATE TABLE auth_tokens (
    user_id UUID NOT NULL,
    purpose VARCHAR(30) NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    id UUID NOT NULL,
    garage_id UUID NOT NULL,
    CONSTRAINT auth_tokens_pkey PRIMARY KEY (id),
    CONSTRAINT auth_tokens_token_hash_key UNIQUE (token_hash),
    CONSTRAINT auth_tokens_garage_id_fkey FOREIGN KEY (garage_id) REFERENCES garages (id) ON DELETE CASCADE,
    CONSTRAINT auth_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_auth_tokens_garage_id ON auth_tokens (garage_id);
CREATE INDEX ix_auth_tokens_user_id ON auth_tokens (user_id);

-- Marque la migration comme appliquée (pour les migrations futures de Flask-Migrate/Alembic)
CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
INSERT INTO alembic_version (version_num) VALUES ('86df1e0c850e');

COMMIT;
