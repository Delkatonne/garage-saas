def garage_dict(g):
    return {
        "id": str(g.id),
        "nom_garage": g.nom_garage,
        "nom_chef_garage": g.nom_chef_garage,
        "email": g.email,
        "telephone": g.telephone,
        "adresse": g.adresse,
        "ville": g.ville,
        "pays": g.pays,
        "logo_url": g.logo_url,
        "initiales": g.initiales,
        "devise": g.devise,
        "devise_decimales": g.devise_decimales,
        "tva_active": g.tva_active,
        "tva_taux": float(g.tva_taux),
        "ifu": g.ifu,
        "rccm": g.rccm,
        "email_verifie": g.email_verifie,
        "statut_abonnement": g.statut_abonnement,
        "essai_fin": g.essai_fin.isoformat() if g.essai_fin else None,
        "abonnement_fin": g.abonnement_fin.isoformat() if g.abonnement_fin else None,
        "actif": g.actif,
        "cree_le": g.created_at.isoformat() if g.created_at else None,
    }


def user_dict(u):
    return {
        "id": str(u.id),
        "email": u.email,
        "nom_complet": u.nom_complet,
        "role": u.role,
        "email_verifie": u.email_verifie,
    }


def client_dict(c):
    return {
        "id": str(c.id),
        "type": c.type,
        "nom": c.nom,
        "prenom": c.prenom,
        "raison_sociale": c.raison_sociale,
        "nom_affiche": c.nom_affiche,
        "telephone": c.telephone,
        "whatsapp": c.whatsapp,
        "email": c.email,
        "adresse": c.adresse,
        "ifu": c.ifu,
        "notes": c.notes,
        "actif": c.actif,
        "cree_le": c.created_at.isoformat() if c.created_at else None,
    }


def vehicule_dict(v, proprietaire=None):
    """`proprietaire` : le Client actuel (ou None)."""
    return {
        "id": str(v.id),
        "type": v.type,
        "marque": v.marque,
        "modele": v.modele,
        "version": v.version,
        "immatriculation": v.immatriculation,
        "vin": v.vin,
        "annee": v.annee,
        "couleur": v.couleur,
        "carburant": v.carburant,
        "cylindree_cc": v.cylindree_cc,
        "kilometrage_actuel": v.kilometrage_actuel,
        "notes": v.notes,
        "actif": v.actif,
        "proprietaire": ({"id": str(proprietaire.id), "nom_affiche": proprietaire.nom_affiche,
                          "telephone": proprietaire.telephone} if proprietaire else None),
        "cree_le": v.created_at.isoformat() if v.created_at else None,
    }


def _num(value):
    return float(value) if value is not None else None


def ligne_dict(l):
    return {"position": l.position, "type": l.type, "designation": l.designation, "unite": l.unite,
            "quantite": _num(l.quantite), "prix_unitaire": _num(l.prix_unitaire),
            "remise_pct": _num(l.remise_pct), "total_ht": _num(l.total_ht)}


def _money_block(d):
    return {"devise": d.devise, "devise_decimales": d.devise_decimales, "tva_active": d.tva_active,
            "tva_taux": _num(d.tva_taux), "sous_total_ht": _num(d.sous_total_ht),
            "remise_globale": _num(d.remise_globale), "total_ht": _num(d.total_ht),
            "total_tva": _num(d.total_tva), "total_ttc": _num(d.total_ttc)}


def _iso(dt):
    return dt.isoformat() if dt else None


def devis_dict(d, client=None, vehicule=None, with_lignes=True, ordre=None):
    out = {
        "id": str(d.id), "numero": d.numero, "version": d.version, "statut": d.statut,
        "statut_effectif": d.statut_effectif, "date_emission": _iso(d.date_emission),
        "date_validite": _iso(d.date_validite), "conditions": d.conditions,
        "client_id": str(d.client_id), "vehicule_id": str(d.vehicule_id) if d.vehicule_id else None,
        "accepte_le": _iso(d.accepte_le), "acceptation_nom": d.acceptation_nom, "acceptation_mode": d.acceptation_mode,
        "refuse_le": _iso(d.refuse_le), "refus_motif": d.refus_motif,
        "or_id": str(d.or_id) if d.or_id else None,
        "ordre": {"id": str(ordre.id), "numero": ordre.numero} if ordre else None,
        "lien_public_actif": bool(d.token_public_hash), "devis_parent_id": str(d.devis_parent_id) if d.devis_parent_id else None,
        "cree_le": _iso(d.created_at),
        "client": ({"id": str(client.id), "nom_affiche": client.nom_affiche, "telephone": client.telephone,
                    "whatsapp": client.whatsapp, "email": client.email} if client else None),
        "vehicule": ({"id": str(vehicule.id), "libelle": f"{vehicule.marque} {vehicule.modele}",
                      "immatriculation": vehicule.immatriculation} if vehicule else None),
        **_money_block(d),
    }
    if with_lignes:
        out["lignes"] = [ligne_dict(l) for l in d.lignes]
    return out


def devis_public_dict(d, garage, client, vehicule):
    """Vue destinée au client final (lien public) : aucun identifiant interne."""
    return {
        "garage": {"nom_garage": garage.nom_garage, "logo_url": garage.logo_url, "initiales": garage.initiales,
                   "telephone": garage.telephone, "adresse": garage.adresse, "ville": garage.ville},
        "devis": {
            "numero": d.numero, "version": d.version, "statut": d.statut_effectif,
            "date_emission": _iso(d.date_emission), "date_validite": _iso(d.date_validite),
            "conditions": d.conditions, "accepte_le": _iso(d.accepte_le), "acceptation_nom": d.acceptation_nom,
            "lignes": [ligne_dict(l) for l in d.lignes], **_money_block(d),
        },
        "client": client.nom_affiche if client else None,
        "vehicule": (f"{vehicule.marque} {vehicule.modele}" + (f" · {vehicule.immatriculation}" if vehicule.immatriculation else "")) if vehicule else None,
    }


def or_dict(o, client=None, vehicule=None, mecanicien=None, show_phone=True):
    return {
        "id": str(o.id), "numero": o.numero, "statut": o.statut, "urgent": o.urgent, "motif": o.motif,
        "symptomes": o.symptomes, "kilometrage_entree": o.kilometrage_entree, "niveau_carburant": o.niveau_carburant,
        "etat_arrivee": o.etat_arrivee, "diagnostic": o.diagnostic, "travaux_effectues": o.travaux_effectues,
        "date_entree": _iso(o.date_entree), "date_sortie_prevue": _iso(o.date_sortie_prevue),
        "date_livraison": _iso(o.date_livraison), "mecanicien_id": str(o.mecanicien_id) if o.mecanicien_id else None,
        "mecanicien": ({"id": str(mecanicien.id), "nom": mecanicien.nom_complet} if mecanicien else None),
        "autorisation": ({"nom": o.signature_nom, "date": _iso(o.signature_date)} if o.signature_nom else None),
        "client_id": str(o.client_id), "vehicule_id": str(o.vehicule_id),
        "client": ({"id": str(client.id), "nom_affiche": client.nom_affiche,
                    "telephone": client.telephone if show_phone else None} if client else None),
        "vehicule": ({"id": str(vehicule.id), "libelle": f"{vehicule.marque} {vehicule.modele}",
                      "immatriculation": vehicule.immatriculation, "type": vehicule.type,
                      "kilometrage_actuel": vehicule.kilometrage_actuel} if vehicule else None),
        "cree_le": _iso(o.created_at),
    }


def paiement_dict(p, recu=None):
    from app.models import MOYEN_LABELS

    return {"id": str(p.id), "facture_id": str(p.facture_id) if p.facture_id else None, "or_id": str(p.or_id) if p.or_id else None,
            "client_id": str(p.client_id), "montant": _num(p.montant), "devise": p.devise, "moyen": p.moyen,
            "moyen_label": MOYEN_LABELS.get(p.moyen, p.moyen), "reference": p.reference_transaction,
            "date_paiement": _iso(p.date_paiement), "statut": p.statut, "motif_annulation": p.motif_annulation,
            "recu": ({"numero": recu.numero, "solde_restant": _num(recu.solde_restant)} if recu else None)}


def facture_dict(f, paid=0, client=None, vehicule=None, ordre=None, devis=None, with_lignes=True):
    from decimal import Decimal

    from app.services.factures_core import payment_status

    paid = Decimal(paid or 0)
    out = {
        "id": str(f.id), "numero": f.numero, "statut": f.statut, "statut_paiement": payment_status(f, paid),
        "emise_le": _iso(f.emise_le), "echeance": _iso(f.echeance), "conditions": f.conditions,
        "client_id": str(f.client_id), "vehicule_id": str(f.vehicule_id) if f.vehicule_id else None,
        "or_id": str(f.or_id) if f.or_id else None, "devis_id": str(f.devis_id) if f.devis_id else None,
        "total_paye": float(paid), "reste_a_payer": float(Decimal(f.total_ttc) - paid) if f.statut == "emise" else None,
        "empreinte": f.hash_integrite[:16] if f.hash_integrite else None,
        "annulee_le": _iso(f.annulee_le), "motif_annulation": f.motif_annulation, "cree_le": _iso(f.created_at),
        "client": ({"id": str(client.id), "nom_affiche": client.nom_affiche, "telephone": client.telephone} if client else None),
        "vehicule": ({"id": str(vehicule.id), "libelle": f"{vehicule.marque} {vehicule.modele}",
                      "immatriculation": vehicule.immatriculation} if vehicule else None),
        "ordre": {"id": str(ordre.id), "numero": ordre.numero} if ordre else None,
        "devis": {"id": str(devis.id), "numero": devis.numero} if devis else None,
        **_money_block(f),
    }
    if with_lignes:
        out["lignes"] = [ligne_dict(l) for l in f.lignes]
    return out
