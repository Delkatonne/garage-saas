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


def devis_dict(d, client=None, vehicule=None, with_lignes=True):
    out = {
        "id": str(d.id), "numero": d.numero, "version": d.version, "statut": d.statut,
        "statut_effectif": d.statut_effectif, "date_emission": _iso(d.date_emission),
        "date_validite": _iso(d.date_validite), "conditions": d.conditions,
        "client_id": str(d.client_id), "vehicule_id": str(d.vehicule_id) if d.vehicule_id else None,
        "accepte_le": _iso(d.accepte_le), "acceptation_nom": d.acceptation_nom, "acceptation_mode": d.acceptation_mode,
        "refuse_le": _iso(d.refuse_le), "refus_motif": d.refus_motif,
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
