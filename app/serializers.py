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
