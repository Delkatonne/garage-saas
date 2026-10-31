# Schéma de base de données : Garage SaaS

Les tables marquées **[P1]** sont implémentées et migrées (Phase 1). Les autres sont spécifiées ici et seront créées phase par phase.

## Conventions

* Clés primaires `id UUID`. Montants `NUMERIC(14,2)`, quantités `NUMERIC(12,3)`. Heures en UTC (`timestamptz`).
* **Toutes les tables ont `garage_id UUID NOT NULL`** (FK `garages.id`, index), sauf 3 tables globales : `garages`, `platform_admins`, `revoked_tokens`.
* Colonnes communes (non répétées ci-dessous) : `created_at`, `updated_at`, `created_by` (FK `users.id`, nullable).
* Les unicités métier incluent toujours `garage_id` : ex. `UNIQUE (garage_id, immatriculation)`.
* **Intégrité inter-garages** : chaque table parente porte `UNIQUE (garage_id, id)` et les clés étrangères sont composites
  `(garage_id, parent_id) -> parent(garage_id, id)`. La base refuse alors par elle-même qu'une ligne du garage A pointe vers une ligne du garage B.
* Énumérations en `VARCHAR` + `CHECK` (évolution plus simple que les types ENUM PostgreSQL).
* Suppression : jamais de suppression physique des données comptables ; `actif`/`archive_le` ailleurs.

## Vue d'ensemble des relations

```
garages 1─* users                    garages 1─* clients 1─* vehicule_proprietaires *─1 vehicules
clients 1─* ordres_reparation *─1 vehicules          devis 1─* devis_lignes
ordres_reparation 1─* or_lignes      ordres_reparation 1─* taches 1─* pointages
devis ─ (accepté) ─> ordres_reparation ─ (terminé) ─> factures 1─* facture_lignes
factures 1─* paiements 1─1 recus     factures 1─* avoirs     ordres_reparation 1─1 bons_sortie
pieces 1─* mouvements_stock          commandes_fournisseurs 1─* commande_lignes *─1 pieces
or_lignes ─> garanties ─> reclamations        vehicules 1─* rappels_entretien
```

## 1. Identité et plateforme

* **garages [P1]** : nom_garage, nom_chef_garage, email (unique), telephone, adresse, ville, pays (défaut BJ), logo_url, logo_public_id, devise (XOF), devise_decimales (0), tva_active, tva_taux, ifu, rccm, email_verifie, actif, statut_abonnement (essai/actif/suspendu/expire), essai_fin, abonnement_fin. (`created_at` = `date_creation`.)
* **users [P1]** : garage_id, email (unique global), nom_complet, role (owner/receptionniste/mecanicien/magasinier/comptable), password_hash (Argon2id), email_verifie, actif, failed_attempts, locked_until, last_login_at, password_changed_at. *Le hash est porté par `users` (et non `garages`) car chaque employé a ses propres identifiants.*
* **employes_profils** (P1b) : user_id (unique), telephone, date_embauche, taux_horaire, commission_pct, specialites (voiture/moto), notes.
* **platform_admins [P1]** *(globale)* : email, nom, password_hash, actif, failed_attempts, locked_until, password_changed_at.
* **auth_tokens [P1]** : garage_id, user_id, purpose (verify_email/reset_password/invitation), token_hash (unique), expires_at, used_at.
* **revoked_tokens [P1]** *(globale)* : jti (unique), token_type, expires_at, revoked_at.
* **audit_logs [P1]** : garage_id, user_id, action, entity_type, entity_id, details (JSON : avant/après), ip, user_agent, created_at. Index (garage_id, created_at).
* **demandes_export** (P3) : type (export/suppression), statut, fichier_url, demandee_par, traitee_le.

## 2. Clients et véhicules

* **clients** : type (particulier/entreprise/flotte), nom, prenom, raison_sociale, telephone, whatsapp, email, adresse, ifu, notes, actif. Index (garage_id, telephone), (garage_id, nom).
* **contacts_client** (flotte/entreprise) : client_id, nom, fonction, telephone, email.
* **vehicules** : type (voiture/moto/scooter/quad), marque, modele, version, immatriculation, vin, annee, couleur, carburant, cylindree_cc, kilometrage_actuel, notes, actif. `UNIQUE (garage_id, immatriculation)`, `UNIQUE (garage_id, vin) WHERE vin IS NOT NULL`.
* **vehicule_proprietaires** : vehicule_id, client_id, date_debut, date_fin (NULL = propriétaire actuel). Une seule ligne ouverte par véhicule (index unique partiel). Un véhicule peut changer de propriétaire sans perdre son historique.

## 3. Accueil et ordres de réparation

* **ordres_reparation** : numero (`OR-2026-0001`, unique par garage), client_id, vehicule_id, devis_id, motif, symptomes, kilometrage_entree, niveau_carburant (0 à 100), etat_arrivee (texte + JSON des rayures/accessoires), statut (en_attente, diagnostic, devis_envoye, devis_accepte, en_cours, attente_pieces, termine, facture, livre, annule), urgent, mecanicien_id, poste_id, date_entree, date_sortie_prevue, date_livraison, signature_autorisation_url, signature_nom, signature_date, signature_ip.
* **or_statut_historique** : or_id, ancien_statut, nouveau_statut, user_id, date, commentaire.
* **or_photos** : or_id, url, public_id, type (arrivee/sortie/diagnostic), legende.
* **or_lignes** : or_id, devis_ligne_id (traçabilité), type (main_oeuvre/piece/forfait/consommable/autre), designation, piece_id, quantite, unite, prix_unitaire, remise_pct, tva_taux, mecanicien_id, realise_le. Source de la facture : aucune ressaisie.

## 4. Devis, facturation, paiements

* **sequences_documents** : type (DEV/FAC/AV/REC/BS/OR), annee, dernier_numero. `UNIQUE (garage_id, type, annee)`, incrément sous verrou `FOR UPDATE` : numérotation sans trous.
* **devis** : numero, version, devis_parent_id, client_id, vehicule_id, or_id, statut (brouillon/envoye/accepte/refuse/expire/remplace), date_emission, date_validite, remise_globale, total_ht, total_tva, total_ttc, conditions, token_public_hash (lien/QR), accepte_le, acceptation_nom, acceptation_ip, signature_url.
* **devis_lignes** : devis_id, position, type, designation, piece_id, quantite, unite, prix_unitaire, remise_pct, tva_taux, total_ht.
* **factures** : numero, or_id, devis_id, client_id, vehicule_id, statut (brouillon/emise/annulee), emise_le, echeance, remise_globale, total_ht, total_tva, total_ttc, total_acomptes, snapshot (JSON garage + client + véhicule figés), hash_integrite, `emecef_uid`, `emecef_code`, `emecef_qr`, `emecef_statut` (extension fiscale, NULL aujourd'hui). `reste_a_payer = total_ttc − paiements valides − avoirs`. **Trigger : UPDATE/DELETE interdits dès que `emise_le` est renseigné.**
* **facture_lignes** : facture_id, position, type, designation, quantite, unite, prix_unitaire, remise_pct, tva_taux, total_ht, or_ligne_id. Immuable après émission (même trigger).
* **avoirs** : numero, facture_id, motif, total_ht, total_tva, total_ttc, emis_le, snapshot. Immuable. **avoir_lignes** : avoir_id, facture_ligne_id, designation, quantite, prix_unitaire, tva_taux, total_ht.
* **paiements** : facture_id (NULL pour un acompte avant facture), or_id, client_id, montant, moyen (especes/momo_mtn/momo_moov/momo_celtiis/virement/carte/cheque), reference_transaction, date_paiement, encaisse_par (FK users), statut (valide/annule), motif_annulation, idempotency_key (unique par garage). Aucun paiement supprimé : annulation tracée. Les acomptes de l'OR sont rattachés à la facture à l'émission.
* **recus** : numero (`REC-`), paiement_id (unique), solde_restant, snapshot, encaisse_par_nom. Créé dans la même transaction que le paiement.
* **bons_sortie** : numero (`BS-`), or_id (unique), kilometrage_sortie, etat_vehicule, pieces_remplacees (JSON), garantie_texte, remis_a_nom, signature_client_url, date_livraison.
* **documents_pdf** : type, ref_id, numero, client_id, vehicule_id, storage_url, hash_sha256, generated_at. Historique rattaché au client et au véhicule ; réimpression à tout moment.
* **documents_envois** : document_id, canal (email/whatsapp/telechargement), destinataire, statut, envoye_le.
* **relances** (P3) : facture_id, niveau, canal, envoyee_le, prochaine_relance.

## 5. Stock et pièces

* **pieces** : reference, designation, marque, categorie (piece/huile/consommable/pneu/outillage), type_vehicule (voiture/moto/commun), unite, prix_achat, prix_vente, marge (calculée), seuil_alerte, stock_actuel (cache recalculable), emplacement, attributs (JSON : viscosité, dimension de pneu, norme...), actif. `UNIQUE (garage_id, reference)`.
* **piece_compatibilites** : piece_id, type_vehicule, marque, modele, annee_debut, annee_fin.
* **fournisseurs** : nom, contact, telephone, email, adresse, delai_moyen_jours, notes.
* **mouvements_stock** *(ajout seul)* : piece_id, type (entree/sortie_or/ajustement/inventaire/retour_client/retour_fournisseur/perte/casse), quantite (signée), cout_unitaire, or_id, commande_id, user_id, motif, date. Le stock = somme des mouvements.
* **commandes_fournisseurs** : numero, fournisseur_id, statut (brouillon/envoyee/partielle/recue/annulee), date_commande, date_attendue, total.
* **commande_lignes** : commande_id, piece_id, quantite_commandee, quantite_recue, prix_achat, client_id, or_id (pièce commandée pour un client précis), statut (en_attente/recue/a_recuperer/recuperee), date_recuperation_limite.
* **receptions** (P3) : commande_id, date, recu_par, bon_livraison_ref ; **reception_lignes** : reception_id, commande_ligne_id, quantite.
* **retours_pieces** : piece_id, fournisseur_id, or_id, quantite, motif (defectueuse/erreur_commande), statut, avoir_fournisseur_ref.
* **inventaires** : date, statut (en_cours/valide), valide_par ; **inventaire_lignes** : inventaire_id, piece_id, quantite_theorique, quantite_comptee, ecart.

## 6. Planning et atelier (Phase 2b)

* **postes** : nom, type (pont/poste/zone_moto/lavage), actif.
* **rendez_vous** : client_id, vehicule_id, mecanicien_id, poste_id, debut, fin, motif, statut (prevu/confirme/arrive/absent/annule/termine), urgent, or_id, rappel_envoye_le.
* **taches** : or_id, or_ligne_id, titre, mecanicien_id, temps_estime_min, statut (a_faire/en_cours/pause/terminee), ordre.
* **pointages** : tache_id, user_id, debut, fin. Temps réel = somme des pointages.
* **absences** : user_id, debut, fin, motif.

## 7. Suivi et fidélisation

* **rappels_entretien** : vehicule_id, type (vidange/revision/controle_technique/assurance/pneus/autre), echeance_date, echeance_km, statut (a_venir/notifie/fait/ignore), notifie_le.
* **carnet_entretien** : vehicule_id, or_id (NULL si saisie manuelle), date, kilometrage, description, pieces (JSON).
* **notifications** : client_id, canal (whatsapp_lien/email/sms), modele (vehicule_pret/devis_a_valider/rappel_rdv/rappel_entretien/relance), statut (a_envoyer/envoye/echec), payload (JSON), envoye_le.
* **fidelite_comptes** : client_id (unique), points. **fidelite_mouvements** : client_id, points, motif, facture_id.

## 8. Garanties et litiges

* **garanties** : or_ligne_id, type (piece/main_oeuvre), debut, fin, conditions, statut (active/expiree/utilisee).
* **reclamations** : client_id, vehicule_id, or_origine_id, garantie_id, type (reclamation/retour/reprise/meme_probleme), description, statut (ouverte/en_analyse/acceptee/refusee/cloturee), resolution, nouvel_or_id, ouverte_le, cloturee_le.
* **Traçabilité** : `audit_logs` + `or_statut_historique` + `mouvements_stock` + `pointages` répondent à « qui a fait quoi, quand, avec quelles pièces ».

## 9. RH et performance

* **commissions** : user_id, or_id, base, taux_pct, montant, periode, statut (a_payer/payee). La productivité (temps, nombre d'OR, chiffre d'affaires par mécanicien) est une vue calculée à partir de `pointages` et `or_lignes`.

## 10. Comptabilité et rapports

* **categories_depenses** : nom (loyer, électricité, outillage, salaires...).
* **depenses** : categorie_id, libelle, montant, date, moyen_paiement, fournisseur_id, justificatif_url, saisie_par.
* **caisse_journees** : date, ouverture, fermeture_theorique, fermeture_comptee, ecart, statut (ouverte/cloturee), cloturee_par. `UNIQUE (garage_id, date)`. Entrées = paiements en espèces, sorties = dépenses en espèces.
* Tableau de bord et exports Excel/PDF : requêtes agrégées sur factures, paiements, `or_lignes`, stock (chiffre d'affaires, marge, impayés, top clients, services les plus rentables). Aucune table dédiée.
