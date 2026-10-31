# Architecture globale : Garage SaaS (Bénin)

## 1. Vue d'ensemble

Monolithe modulaire Flask : un seul déploiement, une seule base PostgreSQL, un découpage strict par module.
Choix assumé pour une équipe réduite : peu de pièces mobiles, déploiement simple sur Render, coût minimal.

```
Navigateur / tablette / téléphone (PWA installable)
        |  HTTPS : pages Jinja + HTMX/Alpine.js (Phase 2) + fetch JSON
        v
Flask (gunicorn)
  ├─ web/        pages HTML, manifest, service worker
  ├─ api/        blueprints JSON par module (auth, garage, admin ; clients, vehicules, or, devis... ensuite)
  ├─ services/   logique métier (auth, stockage logos, emails, audit ; facturation, stock... ensuite)
  ├─ models/     SQLAlchemy (tous les modèles métier héritent de TenantMixin)
  ├─ tenancy.py  isolation automatique par garage (fail-closed)
  └─ auth_hooks  JWT -> utilisateur -> garage courant
        |
        ├─ PostgreSQL (Render)           données + migrations Alembic
        ├─ Cloudinary                    logos, photos d'état à l'arrivée, signatures, PDF archivés
        └─ SMTP (Brevo/Mailgun/Gmail)    emails transactionnels
Render Cron Job : relances, rappels d'entretien, purge des jetons (flask purge-tokens)
```

Pourquoi Flask + Jinja + HTMX/Alpine plutôt que React : un seul déploiement, pas de build front, pages rapides sur
réseau lent, moins de JS à télécharger. Les formulaires lourds (devis, OR) utiliseront HTMX pour les fragments
(ajout de ligne, recalcul des totaux) et Alpine.js pour l'état local. Les écrans de signature utilisent un `<canvas>`.

## 2. Arborescence

```
app/
  __init__.py        usine d'application, en-têtes de sécurité (CSP, HSTS...)
  config.py          configuration par variables d'environnement
  tenancy.py         filtrage automatique par garage_id + garde-fous d'écriture
  auth_hooks.py      callbacks JWT (identité, révocation, garage suspendu)
  permissions.py     rôles -> permissions, décorateurs
  security.py        Argon2id, politique de mot de passe, jetons
  validators.py      validation des entrées
  models/            base.py (mixins), identity.py ; un fichier par module ensuite
  services/          auth_service, mailer, storage, audit ; un fichier par module ensuite
  api/               auth.py, garage.py, admin.py ; un blueprint par module ensuite
  web/ templates/ static/
tests/               pytest (42 tests en Phase 1)
migrations/          Alembic
docs/                ce fichier + DATABASE_SCHEMA.md
```

## 3. Isolation multi-garages (le point le plus critique)

Défense en profondeur, 5 couches :

1. **Colonne `garage_id` NOT NULL** (FK + index) sur toutes les tables métier via `TenantMixin`.
   Un test échoue si une nouvelle table n'a pas `garage_id` (`test_all_business_tables_carry_garage_id`).
2. **Le garage vient de la base, jamais du client** : le JWT contient seulement l'identité de l'utilisateur ;
   `garage_id` est relu en base et recoupé avec la claim du jeton. Un `garage_id` dans un corps JSON, une URL ou
   un jeton falsifié est ignoré ou rejeté.
3. **Filtrage automatique** : un hook `do_orm_execute` ajoute `WHERE garage_id = :id` à tout
   SELECT/UPDATE/DELETE sur une table `TenantMixin` (y compris `session.get`, jointures et chargements paresseux).
4. **Fail-closed** : pendant une requête HTTP sans garage authentifié, les tables métier apparaissent vides et les
   écritures sont refusées. Les accès globaux (connexion, jetons, back-office) passent explicitement par
   `with unscoped():`, ce qui les rend repérables à la relecture de code.
5. **Garde-fous d'écriture** (`before_flush`) : refus d'insérer pour un autre garage, de modifier ou supprimer un
   objet d'un autre garage, ou de changer un `garage_id`.

Limites connues à garder en tête : le SQL brut (`text()`) et les requêtes `Core` sur des tables sans entité ORM
ne sont pas filtrés automatiquement. Règle de code : pas de SQL brut sur des tables métier sans `garage_id` explicite.
Option de durcissement ultérieure : Row Level Security PostgreSQL (`SET app.garage_id` par requête) en 2e filet.

## 4. Authentification et sessions

* Mots de passe : Argon2id. Politique : 8 caractères minimum, lettre + chiffre, liste de mots de passe courants refusés.
* JWT access (15 min) + refresh (30 jours) en **cookies httpOnly** + protection **CSRF double-submit**
  (`X-CSRF-TOKEN`). Les cookies sont `Secure` + `SameSite=Lax` en production. Le refresh est limité au chemin
  `/api/auth/`. Les en-têtes `Authorization: Bearer` restent acceptés pour de futurs clients non navigateur.
* **Rotation du refresh token** : chaque refresh révoque l'ancien ; la réutilisation d'un jeton révoqué est refusée.
* Déconnexion = révocation (table `revoked_tokens`). Changer ou réinitialiser le mot de passe invalide toutes les sessions
  existantes (comparaison `iat` / `password_changed_at`).
* Suspension d'un garage par le super-admin : effet immédiat, y compris sur les sessions ouvertes.
* Vérification d'email obligatoire avant la première connexion. Jetons : 32 octets aléatoires, **seul le hash SHA-256
  est stocké**, usage unique atomique, 24 h (vérification) ou 30 min (réinitialisation).
* Anti-force brute : limitation par IP (Flask-Limiter) + verrouillage du compte (5 échecs = 15 min, indépendant du nombre
  de workers). Messages génériques : même réponse pour email inconnu, mauvais mot de passe ou compte verrouillé ;
  le détail (email non confirmé, garage suspendu) n'est donné qu'après un mot de passe correct.
* Envoi de l'email de réinitialisation : réponse identique que le compte existe ou non.

## 5. Rôles et permissions

`owner` (chef de garage, tous droits), `receptionniste`, `mecanicien`, `magasinier`, `comptable`. Permissions
nommées `module.action` (ex. `factures.emit`), vérifiées par `@require_permission`. La matrice complète est
dans `permissions.py` et s'affine module par module.

## 6. Documents PDF et numérotation légale (Phase 2)

* Numérotation sans trous par garage, par type et par année : table `sequences_documents` avec verrou de ligne
  (`SELECT ... FOR UPDATE`) dans la même transaction que l'émission. Formats : `DEV-2026-0001`, `FAC-2026-0001`,
  `REC-2026-0001`, `BS-2026-0001`, `AV-2026-0001`, `OR-2026-0001`.
* **Facture émise = immuable** : (a) l'application n'expose aucune route de modification/suppression d'une facture
  émise ; (b) un trigger PostgreSQL rejette tout UPDATE/DELETE sur `factures` et `facture_lignes` une fois `emise_le`
  renseigné ; (c) un instantané JSON (garage, client, véhicule) et un hash d'intégrité sont figés à l'émission.
  Correction uniquement par **avoir** (`AV-`), qui référence la facture et annule tout ou partie.
* Le **reçu** est créé automatiquement avec chaque paiement (même transaction), avec solde restant et encaisseur.
* Génération PDF : WeasyPrint (HTML/CSS vers PDF, modèles Jinja identiques à l'aperçu écran). Il nécessite des
  bibliothèques système (Pango) : déploiement Render via Docker. Alternative sans dépendances système : ReportLab.
  Le PDF est archivé (Cloudinary) avec son hash ; la réimpression resert le fichier archivé (jamais régénéré pour une facture émise).
* Envoi : email (pièce jointe) ou lien WhatsApp `wa.me` pré-rempli avec un lien public à jeton signé et expirant.
* **e-MECeF** : la facture porte déjà les champs d'extension (`emecef_uid`, `emecef_code`, `emecef_qr`, `emecef_statut`)
  et l'émission passe par un service `FiscalAdapter` (implémentation `Noop` aujourd'hui). Brancher e-MECeF
  consistera à ajouter un adaptateur qui appelle l'API de la DGI à l'émission, sans changer le reste.

## 7. Argent, temps, fichiers

* Montants : `NUMERIC(14,2)` côté base, `Decimal` côté Python, jamais de `float`. Le nombre de décimales d'affichage
  vient du garage (`devise_decimales`, 0 pour le FCFA). Arrondi calculé ligne par ligne, puis total.
* Heures stockées en UTC ; affichage en `Africa/Porto-Novo` (UTC+1, sans heure d'été).
* Fichiers : validation du type réel (Pillow), taille, ré-encodage (supprime métadonnées et contenus piégés),
  stockage Cloudinary en production. Le disque de Render n'est pas persistant : le stockage local sert au développement.

## 8. Tolérance aux connexions instables

* PWA installable (manifest + service worker qui met en cache la coquille statique, jamais l'API).
* Brouillons de formulaires sauvegardés localement (jamais les mots de passe), restaurés au rechargement.
* Opérations d'écriture idempotentes (clé `Idempotency-Key` pour paiements et émissions, Phase 2) : un clic répété ou un
  renvoi après coupure ne crée pas de doublon.
* Hors-ligne complet avec synchronisation : volontairement repoussé (coût élevé, risques de conflits sur le stock et la
  numérotation légale).

## 9. Sécurité transverse

CSP stricte (`script-src 'self'`, aucun script inline), HSTS, `X-Frame-Options: DENY`, `nosniff`, CORS fermé par défaut,
cookies httpOnly, auto-échappement Jinja (XSS), requêtes paramétrées SQLAlchemy (injection SQL), limite de taille des
requêtes, journal d'audit (`audit_logs`, jamais modifié par l'application), sauvegardes PostgreSQL quotidiennes (plan
Render payant + export hebdomadaire), export et suppression des données du garage à la demande (Phase 3).

## 10. Déploiement

Render : 1 Web Service (gunicorn), 1 PostgreSQL, 1 Cron Job quotidien. `flask db upgrade` à chaque déploiement.
Variables : voir `.env.example`. En production multi-workers, définir `RATELIMIT_STORAGE_URI` (Redis) ; sans Redis,
le verrouillage par compte reste efficace car il est stocké en base.

## 11. Découpage en phases

| Phase | Contenu | État |
|---|---|---|
| 1 | Comptes garages : inscription, email, connexion JWT, mot de passe oublié, profil, logo, super-admin, isolation + tests | **Livrée** |
| 1b | Employés et permissions par rôle (création par le chef, invitation par email) | À venir |
| 2 | MVP : clients, véhicules, OR, devis, facture, avoir, paiements, reçus, bon de sortie, stock de base, PDF | À venir |
| 2b | Planning, rendez-vous, rappels d'entretien (juste après le MVP) | À venir |
| 3 | Fournisseurs/commandes, garanties/litiges, RH/commissions, comptabilité/caisse, fidélité, exports, relances | À venir |

## 12. Risques et cas limites déjà traités ou planifiés

* **Contestation de devis/facture** : devis versionnés (jamais écrasés), acceptation tracée (date, IP, nom, signature),
  facture figée, avoirs, historique d'audit.
* **Pièces commandées jamais récupérées** : `commande_lignes.client_id/or_id`, statut `a_recuperer`, alerte au-delà d'un délai paramétrable.
* **Véhicules oubliés au parking** : alerte sur les OR `termine` non `livre` depuis plus de N jours, frais de gardiennage optionnels.
* **Vol/perte de pièces, erreurs de stock** : mouvements de stock en ajout seul (la quantité en stock est un cache recalculable),
  type `perte`/`casse` avec motif et utilisateur, inventaires avec écarts.
* **Mécanicien absent** : table `absences`, réaffectation des tâches, alerte planning.
* **Impayés** : `reste_a_payer`, relances à niveaux, suivi des créances, blocage optionnel de livraison.
* **Véhicule revenu pour le même problème** : `reclamations` rattachées à l'OR d'origine, détection par véhicule + catégorie dans la garantie.
* **Urgences** : drapeau `urgent` sur OR/rendez-vous, insertion dans le planning avec signalement des rendez-vous décalés.
* **Voiture/moto** : `type_vehicule` sur véhicules, pièces et compatibilités ; catalogue et outillage filtrés par type.
