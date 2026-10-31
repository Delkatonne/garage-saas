# Garage SaaS : Phase 1 (comptes garages)

Application web de gestion de garages auto et moto (multi-garages, isolation stricte des données).
Phase 1 : inscription, vérification d'email, connexion JWT, mot de passe oublié, profil du garage (logo, IFU, RCCM, devise, TVA),
back-office super-admin. Architecture et schéma complet : `docs/ARCHITECTURE.md`, `docs/DATABASE_SCHEMA.md`.

## Lancer en local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # SQLite en dev si DATABASE_URL est vide ; adapter les secrets
export FLASK_APP=wsgi.py
flask db upgrade                # crée les tables (instance/garage_dev.db en dev)
flask create-admin              # super-admin de la plateforme (email, nom, mot de passe)
flask run                       # http://localhost:5000
```

Sans `MAIL_SERVER`, les emails (lien de confirmation, réinitialisation) sont **affichés dans la console** du serveur.
Avec PostgreSQL : `DATABASE_URL=postgresql://user:pass@localhost:5432/garage_saas`, puis `flask db upgrade`.

## Tests

```bash
pytest -q        # 42 tests, base SQLite en mémoire
```

Les tests d'isolation (`tests/test_isolation.py`) prouvent qu'un garage A ne peut ni lire, ni modifier, ni supprimer les
données d'un garage B (HTTP et ORM), qu'un `garage_id` fourni par le client ou un jeton falsifié sont sans effet, et
qu'une table sans `garage_id` fait échouer la suite.

## Pages

`/` · `/inscription` · `/connexion` · `/mot-de-passe-oublie` · `/reinitialiser-mot-de-passe?token=` · `/verifier-email?token=` · `/tableau-de-bord` · `/profil`

## API (JSON, préfixe `/api`)

| Méthode | Route | Rôle |
|---|---|---|
| POST | `/auth/register` | Inscription (JSON ou multipart avec `logo`) |
| POST | `/auth/verify-email` · `/auth/resend-verification` | Confirmation d'email |
| POST | `/auth/login` · `/auth/refresh` · `/auth/logout` | Session (cookies httpOnly + CSRF) |
| POST | `/auth/forgot-password` · `/auth/reset-password` | Lien unique, 30 min |
| POST | `/auth/change-password` · GET `/auth/me` | Compte connecté |
| GET/PATCH | `/garage/profile` | Profil (PATCH réservé au propriétaire) |
| POST/DELETE | `/garage/logo` | Logo (PNG/JPG/WEBP, 2 Mo) |
| POST | `/admin/auth/login` | Connexion super-admin |
| GET | `/admin/garages` · `/admin/garages/<id>` | Liste, détail (filtres `q`, `statut`, `page`) |
| POST | `/admin/garages/<id>/suspendre` · `/activer` | Suspension immédiate |
| PATCH | `/admin/garages/<id>/abonnement` | Statut, fin d'essai, fin d'abonnement |

Erreurs : `{"erreur": "...", "code": "...", "details": {champ: message}}` (422 pour la validation, 401 générique pour les identifiants).
Pour un client non navigateur, l'en-tête `Authorization: Bearer <access_token>` est accepté (pas de CSRF dans ce cas).

## Déploiement sur Vercel

Tout (pages + API) tourne dans UNE fonction serverless Python (`api/index.py`) ; `vercel.json` y envoie toutes les URL.

### 1. Créer les services externes
* **Neon** (PostgreSQL) : copier l'adresse de connexion **pooled** (hôte contenant `-pooler`) avec `?sslmode=require`.
* **Cloudinary** : copier `CLOUDINARY_URL` (obligatoire : le disque de Vercel est en lecture seule).
* **Brevo** : créer une clé **API** (Paramètres → SMTP & API → Clés API) et vérifier l'adresse d'expéditeur.
* **Upstash Redis** (recommandé avant les vrais clients) : copier l'adresse `rediss://...`.

### 2. Créer les tables et le super-admin (depuis votre ordinateur, une fois)
```bash
export DATABASE_URL="postgresql://...neon.tech/neondb?sslmode=require"   # adresse Neon
export FLASK_APP=wsgi.py
flask db upgrade
flask create-admin
```
À refaire (`flask db upgrade`) après chaque nouvelle migration, AVANT de déployer le code qui en dépend.

### 3. Importer le dépôt dans Vercel
Add New → Project → choisir le dépôt GitHub. Renseigner les variables d'environnement (Settings → Environment Variables) :

| Variable | Valeur |
|---|---|
| `APP_ENV` | `production` |
| `SECRET_KEY`, `JWT_SECRET_KEY` | deux longues chaînes aléatoires différentes |
| `DATABASE_URL` | adresse Neon pooled |
| `CLOUDINARY_URL` | adresse Cloudinary |
| `BREVO_API_KEY`, `MAIL_DEFAULT_SENDER` | clé API et expéditeur vérifié |
| `APP_BASE_URL` | `https://votre-domaine` (sinon le domaine de production Vercel est utilisé) |
| `RATELIMIT_STORAGE_URI` | adresse Upstash `rediss://...` |
| `CRON_SECRET` | longue chaîne aléatoire (Vercel l'envoie au cron quotidien de purge) |

L'application **refuse de démarrer** en production si `SECRET_KEY`, `DATABASE_URL`, `CLOUDINARY_URL`, un service d'email
ou `APP_BASE_URL` manque (message clair dans les logs de la fonction).

### 4. Vérifier
Ouvrir `/healthz` (doit répondre `{"statut": "ok"}`), puis tester inscription, email de confirmation, connexion,
mot de passe oublié et logo.

## Points d'attention

* **Logos en production : Cloudinary obligatoire** (pas de disque persistant sur Vercel).
* **Emails envoyés pendant la requête** (pas de thread d'arrière-plan en serverless) ; un échec d'envoi est journalisé sans bloquer l'inscription.
* **Limitation des tentatives** : sans Redis (`RATELIMIT_STORAGE_URI`), chaque instance compte de son côté. Le verrouillage par compte reste efficace (stocké en base).
* **Cron** : `/api/cron/purge-tokens` (chaque jour à 03:00 UTC) supprime les jetons expirés ; la route répond 404 sans `CRON_SECRET`.
* L'essai dure 30 jours (`TRIAL_DAYS`) ; à son terme la connexion est refusée tant que le super-admin n'active pas l'abonnement.
* Le plan gratuit de Vercel (Hobby) est réservé à un usage non commercial : vérifier les conditions avant d'accueillir des garages payants.
* Le changement d'email du garage (qui sert à la connexion) n'est volontairement pas dans le profil : il demandera un flux de reconfirmation dédié.
* Toute nouvelle table métier doit hériter de `TenantMixin` ; ne jamais lire `garage_id` depuis la requête ; éviter le SQL brut sur les tables métier.
