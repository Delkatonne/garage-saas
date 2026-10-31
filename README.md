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

## Déploiement sur Render

1. Pousser le dépôt sur GitHub, créer un « Blueprint » Render à partir de `render.yaml` (vérifier les noms de plans dans le tableau de bord Render).
2. Renseigner `APP_BASE_URL`, les variables SMTP (Brevo, Mailgun ou Gmail avec mot de passe d'application) et `CLOUDINARY_URL`.
3. `flask db upgrade` s'exécute avant chaque déploiement. Créer le super-admin une fois via le Shell Render : `flask create-admin`.
4. Pour plusieurs workers/instances, définir `RATELIMIT_STORAGE_URI` (Redis).

## Points d'attention

* **Logos en production : Cloudinary obligatoire** (le disque Render est éphémère ; le stockage local est réservé au développement).
* L'essai dure 30 jours (`TRIAL_DAYS`) ; à son terme la connexion est refusée tant que le super-admin n'active pas l'abonnement.
* Le changement d'email du garage (qui sert à la connexion) n'est volontairement pas dans le profil : il demandera un flux de reconfirmation dédié.
* Toute nouvelle table métier doit hériter de `TenantMixin` ; ne jamais lire `garage_id` depuis la requête ; éviter le SQL brut sur les tables métier.
