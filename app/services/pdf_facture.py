"""PDF des factures, avoirs et reçus de paiement (ReportLab)."""
import io
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from app.models import MOYEN_LABELS
from app.services.pdf_devis import GREY, LINE, TEAL, TYPE_LABELS, _p, fmt_date, fmt_money, fmt_qty, load_logo


def _styles():
    base = ParagraphStyle("base", parent=getSampleStyleSheet()["Normal"], fontName="Helvetica", fontSize=9, leading=12)
    return {"base": base, "small": ParagraphStyle("small", parent=base, fontSize=8, textColor=GREY),
            "bold": ParagraphStyle("bold", parent=base, fontName="Helvetica-Bold"),
            "right": ParagraphStyle("right", parent=base, alignment=TA_RIGHT),
            "title": ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=TEAL, alignment=TA_RIGHT)}


def _logo(logo_bytes):
    if not logo_bytes:
        return []
    try:
        w, h = ImageReader(io.BytesIO(logo_bytes)).getSize()
        scale = min(45 * mm / w, 22 * mm / h)
        return [Image(io.BytesIO(logo_bytes), width=w * scale, height=h * scale, hAlign="LEFT"), Spacer(1, 2 * mm)]
    except Exception:  # noqa: BLE001
        return []


def _garage_block(g, st):
    block = [_p(g["nom_garage"], ParagraphStyle("gn", parent=st["bold"], fontSize=12, leading=15))]
    for line in (", ".join(x for x in (g.get("adresse"), g.get("ville")) if x), g.get("telephone"), g.get("email")):
        if line:
            block.append(_p(line, st["base"]))
    ids = " · ".join(x for x in ((f"IFU : {g['ifu']}" if g.get("ifu") else ""), (f"RCCM : {g['rccm']}" if g.get("rccm") else "")) if x)
    if ids:
        block.append(_p(ids, st["small"]))
    return block


def render_facture_pdf(doc: dict, logo_bytes=None) -> bytes:
    """`doc` : voir pdf_facture_doc() dans l'API. mode = facture | avoir."""
    st = _styles()
    d, devise = doc["decimales"], doc["devise"]
    avoir = doc["mode"] == "avoir"
    sign = "- " if avoir else ""
    money = lambda v: sign + fmt_money(v, d, devise)  # noqa: E731
    watermark = {"brouillon": "BROUILLON", "annulee": "ANNULÉE"}.get(doc["statut"]) if not avoir else None

    left = _logo(logo_bytes) + _garage_block(doc["garage"], st)
    number = doc["numero"] or "BROUILLON"
    right = [Paragraph("AVOIR" if avoir else "FACTURE", st["title"]),
             _p(f"N° {number}", ParagraphStyle("n", parent=st["right"], fontName="Helvetica-Bold", fontSize=11, leading=14))]
    if doc.get("date"):
        right.append(_p(f"Date : {fmt_date(doc['date'])}", st["right"]))
    if doc.get("echeance") and not avoir:
        right.append(_p(f"Échéance : {fmt_date(doc['echeance'])}", st["right"]))
    if avoir:
        right.append(_p(f"Annule la facture {doc['facture_numero']}", st["right"]))
    header = Table([[left, right]], colWidths=[100 * mm, 80 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))

    c = doc["client"]
    client_lines = [_p("CLIENT", st["small"]), _p(c["nom_affiche"], st["bold"])]
    for line in (c.get("adresse"), c.get("telephone"), c.get("email"), f"IFU : {c['ifu']}" if c.get("ifu") else None):
        if line:
            client_lines.append(_p(line, st["base"]))
    veh = doc.get("vehicule")
    veh_lines = [_p("VÉHICULE", st["small"])]
    if veh:
        veh_lines.append(_p(veh["libelle"], st["bold"]))
        for line in (veh.get("immatriculation") and f"Immatriculation : {veh['immatriculation']}",
                     veh.get("kilometrage") is not None and f"Kilométrage : {fmt_money(veh['kilometrage'], 0, '', False)} km"):
            if line:
                veh_lines.append(_p(line, st["base"]))
    else:
        veh_lines.append(_p("—", st["base"]))
    parties = Table([[client_lines, veh_lines]], colWidths=[90 * mm, 90 * mm])
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (0, 0), 0.5, LINE), ("BOX", (1, 0), (1, 0), 0.5, LINE),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))

    ht = " HT" if doc["tva_active"] else ""
    rows = [[_p("Désignation", st["bold"]), _p("Qté", st["right"]), _p(f"Prix unit.{ht}", st["right"]), _p("Remise", st["right"]), _p(f"Total{ht}", st["right"])]]
    for l in doc["lignes"]:
        kind = TYPE_LABELS.get(l["type"], "")
        unit = f" {escape(l['unite'])}" if l.get("unite") else ""
        rows.append([Paragraph(f"{escape(l['designation'])}<br/><font size='7' color='#6b7280'>{escape(kind)}</font>", st["base"]),
                     Paragraph(fmt_qty(l["quantite"]) + unit, st["right"]),
                     _p(fmt_money(l["prix_unitaire"], d, devise, False), st["right"]),
                     _p(f"{fmt_qty(l['remise_pct'])} %" if Decimal(l["remise_pct"] or 0) else "", st["right"]),
                     _p(sign + fmt_money(l["total_ht"], d, devise, False), st["right"])])
    table = Table(rows, colWidths=[78 * mm, 24 * mm, 30 * mm, 18 * mm, 30 * mm], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ecfdf5")), ("LINEBELOW", (0, 0), (-1, 0), 0.8, TEAL),
                               ("LINEBELOW", (0, 1), (-1, -1), 0.25, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))

    trows = []
    if doc["tva_active"] or Decimal(doc["remise"] or 0) > 0:
        trows.append([_p("Sous-total" + ht, st["base"]), _p(money(doc["sous_total"]), st["right"])])
    if Decimal(doc["remise"] or 0) > 0:
        trows.append([_p("Remise", st["base"]), _p("- " + fmt_money(doc["remise"], d, devise), st["right"])])
    if doc["tva_active"]:
        trows.append([_p("Total HT", st["base"]), _p(money(doc["total_ht"]), st["right"])])
        trows.append([_p(f"TVA ({fmt_qty(doc['tva_taux'])} %)", st["base"]), _p(money(doc["total_tva"]), st["right"])])
    trows.append([_p("TOTAL TTC" if doc["tva_active"] else "TOTAL", st["bold"]),
                  Paragraph(f"<b>{escape(money(doc['total_ttc']))}</b>", ParagraphStyle("tt", parent=st["right"], fontSize=11, leading=14))])
    totals = Table(trows, colWidths=[45 * mm, 45 * mm], hAlign="RIGHT")
    totals.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 0.8, TEAL), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))

    story = [header, Spacer(1, 6 * mm), parties, Spacer(1, 6 * mm), table, Spacer(1, 4 * mm), totals]
    if not doc["tva_active"]:
        story.append(_p("TVA non applicable.", ParagraphStyle("na", parent=st["small"], alignment=TA_RIGHT)))
    if avoir:
        story += [Spacer(1, 6 * mm), _p(f"Motif : {doc['motif']}", st["bold"])]
    else:
        pay = doc.get("paiements") or []
        if pay:
            prow = [[_p("Paiements reçus", st["bold"]), "", "", ""]] + [
                [_p(fmt_date(p["date"]), st["base"]), _p(MOYEN_LABELS.get(p["moyen"], p["moyen"]), st["base"]),
                 _p(p.get("reference") or "", st["base"]), _p(fmt_money(p["montant"], d, devise), st["right"])] for p in pay]
            ptable = Table(prow, colWidths=[28 * mm, 40 * mm, 62 * mm, 40 * mm])
            ptable.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE), ("SPAN", (0, 0), (-1, 0)), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
            story += [Spacer(1, 5 * mm), ptable]
        if doc["statut"] == "emise":
            story += [Spacer(1, 2 * mm), _p(f"Total payé : {fmt_money(doc['paye'], d, devise)}", st["right"]),
                      Paragraph(f"<b>Reste à payer : {escape(fmt_money(doc['reste'], d, devise))}</b>", ParagraphStyle("rp", parent=st["right"], fontSize=10, leading=13))]
        if doc.get("conditions"):
            story += [Spacer(1, 6 * mm), _p("Conditions de paiement", st["bold"]), _p(doc["conditions"], st["base"])]
        if doc["statut"] == "annulee" and doc.get("avoir"):
            story += [Spacer(1, 5 * mm), _p(f"Facture annulée par l'avoir {doc['avoir']['numero']} du {fmt_date(doc['avoir']['date'])}.", st["bold"])]

    def decorate(canvas, pdf):
        if watermark:
            canvas.saveState()
            canvas.setFont("Helvetica-Bold", 70)
            canvas.setFillGray(0.92)
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(45)
            canvas.drawCentredString(0, 0, watermark)
            canvas.restoreState()
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(GREY)
        canvas.drawString(15 * mm, 10 * mm, f"{doc['garage']['nom_garage']} - {'Avoir' if avoir else 'Facture'} {number}")
        if doc.get("hash"):
            canvas.drawCentredString(A4[0] / 2, 6 * mm, f"Empreinte d'intégrité : {doc['hash'][:32]}")
        canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Page {pdf.page}")
        canvas.restoreState()

    buffer = io.BytesIO()
    pdf = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=18 * mm,
                            title=f"{'Avoir' if avoir else 'Facture'} {number}", author=doc["garage"]["nom_garage"])
    pdf.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


def render_recu_pdf(doc: dict, logo_bytes=None) -> bytes:
    """Reçu de paiement (format A5). `doc` = contenu figé du reçu + statut du paiement."""
    st = _styles()
    d, devise = doc["decimales"], doc["devise"]
    cancelled = doc["statut_paiement"] == "annule"
    left = _logo(logo_bytes) + _garage_block(doc["garage"], st)
    right = [Paragraph("REÇU", ParagraphStyle("t", parent=st["title"], fontSize=18)),
             _p(f"N° {doc['numero']}", ParagraphStyle("n", parent=st["right"], fontName="Helvetica-Bold", fontSize=11, leading=14)),
             _p(f"Date : {fmt_date(doc['date'])}", st["right"])]
    header = Table([[left, right]], colWidths=[75 * mm, 55 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    rows = [[_p("Reçu de", st["small"]), _p(doc["client"], st["bold"])],
            [_p("Montant", st["small"]), Paragraph(f"<b>{escape(fmt_money(doc['montant'], d, devise))}</b>", ParagraphStyle("m", parent=st["base"], fontSize=13, leading=16))],
            [_p("Mode de paiement", st["small"]), _p(MOYEN_LABELS.get(doc["moyen"], doc["moyen"]), st["base"])]]
    if doc.get("reference"):
        rows.append([_p("Référence", st["small"]), _p(doc["reference"], st["base"])])
    if doc.get("facture_numero"):
        rows.append([_p("Pour la facture", st["small"]), _p(doc["facture_numero"], st["base"])])
        rows.append([_p("Total de la facture", st["small"]), _p(fmt_money(doc["total_facture"], d, devise), st["base"])])
        rows.append([_p("Reste à payer", st["small"]), Paragraph(f"<b>{escape(fmt_money(doc['solde_restant'], d, devise))}</b>", st["base"])])
    elif doc.get("or_numero"):
        rows.append([_p("Acompte pour l'ordre", st["small"]), _p(doc["or_numero"], st["base"])])
    if doc.get("encaisse_par"):
        rows.append([_p("Encaissé par", st["small"]), _p(doc["encaisse_par"], st["base"])])
    table = Table(rows, colWidths=[40 * mm, 90 * mm])
    table.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story = [header, Spacer(1, 8 * mm), table, Spacer(1, 10 * mm), _p("Merci de votre confiance.", st["small"])]
    if cancelled:
        story += [Spacer(1, 4 * mm), _p("Ce paiement a été annulé.", st["bold"])]

    def decorate(canvas, pdf):
        if cancelled:
            canvas.saveState()
            canvas.setFont("Helvetica-Bold", 60)
            canvas.setFillGray(0.9)
            canvas.translate(A5[0] / 2, A5[1] / 2)
            canvas.rotate(45)
            canvas.drawCentredString(0, 0, "ANNULÉ")
            canvas.restoreState()
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(GREY)
        canvas.drawString(10 * mm, 8 * mm, f"{doc['garage']['nom_garage']} - Reçu {doc['numero']}")
        canvas.restoreState()

    buffer = io.BytesIO()
    pdf = SimpleDocTemplate(buffer, pagesize=A5, leftMargin=10 * mm, rightMargin=10 * mm, topMargin=10 * mm, bottomMargin=14 * mm,
                            title=f"Reçu {doc['numero']}", author=doc["garage"]["nom_garage"])
    pdf.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


def pdf_response(data: bytes, filename: str):
    from flask import make_response

    resp = make_response(data)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = f'inline; filename="{filename}.pdf"'
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


def logo_for(garage_dict):
    from flask import current_app

    class _G:  # load_logo lit seulement logo_url
        logo_url = garage_dict.get("logo_url")

    return load_logo(_G, current_app.config.get("UPLOAD_FOLDER"))
