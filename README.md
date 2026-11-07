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

## Fonctionnalités actuelles

* **Phase 1** : comptes garages, connexion, mot de passe oublié, profil, logo, rôles.
* **Phase 2, étape 1** : **clients** (particulier / entreprise / flotte, recherche, archivage, appel et WhatsApp en un clic) et **véhicules**
  (voiture / moto / scooter / quad, immatriculation et châssis uniques par garage, kilométrage protégé contre les baisses,
  changement de propriétaire avec historique). Pages : `/clients`, `/clients/<id>`, `/vehicules`, `/vehicules/<id>`.
* **Phase 2, étape 2** : **devis** (`/devis`) : lignes de main-d'œuvre, pièces, forfaits, remises par ligne et globale, TVA du garage,
  numérotation `DEV-2026-0001` attribuée à l'envoi (aucun trou), validité, nouvelles versions (`-V2`...), PDF avec logo, lien à envoyer au
  client (WhatsApp) pour qu'il consulte, télécharge et accepte ou refuse le devis sans compte.
* **Phase 2, étape 3** : **ordres de réparation** (`/or`) : accueil du véhicule (motif, symptômes, kilométrage, carburant, état à l'arrivée,
  urgence, mécanicien, sortie prévue), numéro `OR-2026-0001`, statuts avec historique, autorisation de travaux, notes de l'atelier,
  PDF imprimable, devis liés à l'ordre (l'envoi et l'acceptation d'un devis font avancer l'ordre automatiquement).
* **Phase 2, étape 4** : **factures, paiements, reçus et avoirs** (`/factures`) : brouillon créé à partir d'un devis accepté et/ou d'un
  ordre de réparation (ou vide), numéro légal `FAC-2026-0001` attribué à l'émission (aucun trou), données du garage et du client **figées**
  à l'émission, empreinte d'intégrité (SHA-256), facture émise **jamais modifiable ni supprimable** (correction par **avoir** `AV-...`),
  paiements partiels ou totaux (espèces, MTN MoMo, Moov Money, Celtiis Cash, virement, carte, chèque), **reçu** `REC-...` à chaque paiement,
  **acomptes** pris sur l'ordre et rattachés à la facture à son émission, annulation d'un paiement avec motif, caisse du jour, PDF.
  Un paiement renvoyé par erreur (réseau instable) n'est jamais enregistré deux fois (clé d'idempotence).
* À venir : bon de sortie, stock, planning.

## Base de données sans terminal (Neon)

Les fichiers `docs/sql/neon-phase1.sql`, `neon-phase2-etape1.sql` puis `neon-phase2-etape2-devis.sql` `neon-phase2-etape3-or.sql` puis `neon-phase2-etape4-factures.sql` sont à coller dans l'éditeur SQL de Neon, dans cet ordre,
chacun une seule fois. Ils sont l'équivalent exact des migrations Alembic (`flask db upgrade`).

## Déploiement sur Vercel

Tout (pages + API) tourne dans UNE fonction serverless Python : Vercel détecte Flask automatiquement grâce à `wsgi.py`
(variable `app`). Les fichiers statiques (CSS, JS, icônes, `sw.js`, manifeste) sont dans `public/` : le CDN de Vercel les
sert directement, Flask les sert depuis le même dossier en développement.

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

* **Confirmation de l'email désactivée par défaut** : le compte est utilisable dès l'inscription. Pour l'exiger, définir `REQUIRE_EMAIL_VERIFICATION=true` (un email avec lien est alors envoyé). L'email sert toujours à « mot de passe oublié » : une faute de frappe à l'inscription empêche de récupérer le compte.

* **Logos en production : Cloudinary obligatoire** (pas de disque persistant sur Vercel).
* **Emails envoyés pendant la requête** (pas de thread d'arrière-plan en serverless) ; un échec d'envoi est journalisé sans bloquer l'inscription.
* **Limitation des tentatives** : sans Redis (`RATELIMIT_STORAGE_URI`), chaque instance compte de son côté. Le verrouillage par compte reste efficace (stocké en base).
* **Session** : les cookies de connexion sont persistants (30 jours, renouvelés à chaque utilisation) : on reste connecté en quittant l'application. Le jeton d'accès (15 min) est renouvelé automatiquement, y compris au rechargement d'une page.
* **Menu** : barre horizontale sur ordinateur, menu hamburger sur téléphone (largeur ≤ 760 px).
* **Cron** : `/api/cron/purge-tokens` (chaque jour à 03:00 UTC) supprime les jetons expirés ; la route répond 404 sans `CRON_SECRET`.
* **PDF** : générés avec ReportLab (Python pur). Le logo est téléchargé depuis Cloudinary au moment du PDF ; s'il est inaccessible, le PDF est produit sans logo.
* **Lien client d'un devis** : secret aléatoire de 256 bits (seule son empreinte est stockée) ; un nouveau lien remplace l'ancien ; routes publiques limitées en fréquence.
* L'essai dure 30 jours (`TRIAL_DAYS`) ; à son terme la connexion est refusée tant que le super-admin n'active pas l'abonnement.
* Le plan gratuit de Vercel (Hobby) est réservé à un usage non commercial : vérifier les conditions avant d'accueillir des garages payants.
* Le changement d'email du garage (qui sert à la connexion) n'est volontairement pas dans le profil : il demandera un flux de reconfirmation dédié.
* Toute nouvelle table métier doit hériter de `TenantMixin` ; ne jamais lire `garage_id` depuis la requête ; éviter le SQL brut sur les tables métier.
