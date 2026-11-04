"""Calcul des montants d'un devis : toujours refait côté serveur, jamais fourni par le client."""
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal(0)
HUNDRED = Decimal(100)


def quantize(value, decimals: int) -> Decimal:
    return Decimal(value).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def line_total(quantite, prix_unitaire, remise_pct, decimals: int) -> Decimal:
    return quantize(Decimal(quantite) * Decimal(prix_unitaire) * (HUNDRED - Decimal(remise_pct)) / HUNDRED, decimals)


def totals(line_totals, remise_globale, tva_active: bool, tva_taux, decimals: int):
    """Retourne (sous_total_ht, remise, total_ht, total_tva, total_ttc). La TVA porte sur le total HT après remise."""
    sous_total = sum((Decimal(t) for t in line_totals), ZERO)
    remise = quantize(remise_globale, decimals)
    if remise > sous_total:
        raise ValueError("La remise ne peut pas dépasser le total des lignes.")
    total_ht = sous_total - remise
    total_tva = quantize(total_ht * Decimal(tva_taux) / HUNDRED, decimals) if tva_active else ZERO
    return quantize(sous_total, decimals), remise, quantize(total_ht, decimals), total_tva, quantize(total_ht + total_tva, decimals)
