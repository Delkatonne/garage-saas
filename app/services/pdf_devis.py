"""PDF du devis (ReportLab, Python pur : compatible avec les fonctions serverless de Vercel)."""
import io
import urllib.request
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TEAL = colors.HexColor("#0f766e")
GREY = colors.HexColor("#6b7280")
LINE = colors.HexColor("#d1d5db")
CURRENCY_LABELS = {"XOF": "FCFA", "XAF": "FCFA"}
TYPE_LABELS = {"main_oeuvre": "Main-d'œuvre", "piece": "Pièce", "forfait": "Forfait", "consommable": "Consommable",
               "autre": "Autre"}
MAX_LOGO_BYTES = 2 * 1024 * 1024


def fmt_money(value, decimals: int, devise: str, with_currency=True) -> str:
    number = Decimal(value or 0).quantize(Decimal(1).scaleb(-decimals))
    integer, _, frac = f"{abs(number):f}".partition(".")
    grouped = f"{int(integer):,}".replace(",", " ")
    text = grouped + ("," + frac if decimals else "")
    if number < 0:
        text = "-" + text
    return f"{text} {CURRENCY_LABELS.get(devise, devise)}" if with_currency else text


def fmt_qty(value) -> str:
    number = Decimal(value)
    return f"{number.normalize():f}".replace(".", ",") if number != number.to_integral() else str(int(number))


def fmt_date(dt) -> str:
    return dt.strftime("%d/%m/%Y") if dt else ""


def _p(text, style):
    return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)


def load_logo(garage, upload_folder=None):
    """Octets du logo (ou None). Cloudinary : téléchargement court et plafonné ; sinon fichier local de développement."""
    url = getattr(garage, "logo_url", None)
    if not url:
        return None
    try:
        if url.startswith("https://"):
            with urllib.request.urlopen(url, timeout=5) as resp:  # URL produite par notre propre téléversement
                data = resp.read(MAX_LOGO_BYTES + 1)
            return data if len(data) <= MAX_LOGO_BYTES else None
        if upload_folder and url.startswith("/uploads/logos/"):
            import os
            name = os.path.basename(url)
            with open(os.path.join(upload_folder, "logos", name), "rb") as fh:
                return fh.read(MAX_LOGO_BYTES + 1)
    except Exception:  # noqa: BLE001 - un logo introuvable ne doit jamais empêcher le PDF
        return None
    return None


def render_devis_pdf(devis, garage, client, vehicule=None, logo_bytes=None) -> bytes:
    styles = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=12)
    small = ParagraphStyle("small", parent=base, fontSize=8, textColor=GREY)
    bold = ParagraphStyle("bold", parent=base, fontName="Helvetica-Bold")
    right = ParagraphStyle("right", parent=base, alignment=TA_RIGHT)
    title = ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=TEAL,
                           alignment=TA_RIGHT)
    d, devise = devis.devise_decimales, devis.devise
    money = lambda v: fmt_money(v, d, devise)  # noqa: E731
    is_draft = devis.statut == "brouillon"

    # ---- En-tête : garage (gauche) / titre du devis (droite)
    left = []
    if logo_bytes:
        try:
            reader = ImageReader(io.BytesIO(logo_bytes))
            w, h = reader.getSize()
            scale = min(45 * mm / w, 22 * mm / h)
            left.append(Image(io.BytesIO(logo_bytes), width=w * scale, height=h * scale, hAlign="LEFT"))
            left.append(Spacer(1, 2 * mm))
        except Exception:  # noqa: BLE001
            pass
    left.append(_p(garage.nom_garage, ParagraphStyle("gn", parent=bold, fontSize=12, leading=15)))
    for line in (", ".join(x for x in (garage.adresse, garage.ville) if x), garage.telephone, garage.email):
        if line:
            left.append(_p(line, base))
    ids = " · ".join(x for x in ((f"IFU : {garage.ifu}" if garage.ifu else ""),
                                 (f"RCCM : {garage.rccm}" if garage.rccm else "")) if x)
    if ids:
        left.append(_p(ids, small))
    number = devis.numero or "BROUILLON"
    right_block = [Paragraph("DEVIS", title), _p(f"N° {number}", ParagraphStyle("n", parent=right, fontName="Helvetica-Bold", fontSize=11, leading=14))]
    if devis.version and devis.version > 1:
        right_block.append(_p(f"Version {devis.version}", right))
    if devis.date_emission:
        right_block.append(_p(f"Date : {fmt_date(devis.date_emission)}", right))
    if devis.date_validite:
        right_block.append(_p(f"Valable jusqu'au : {fmt_date(devis.date_validite)}", right))
    header = Table([[left, right_block]], colWidths=[100 * mm, 80 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))

    # ---- Client et véhicule
    client_lines = [_p("CLIENT", small), _p(client.nom_affiche, bold)]
    for line in (client.adresse, client.telephone, client.email):
        if line:
            client_lines.append(_p(line, base))
    veh_lines = [_p("VÉHICULE", small)]
    if vehicule is not None:
        veh_lines.append(_p(f"{vehicule.marque} {vehicule.modele}", bold))
        for line in (vehicule.immatriculation and f"Immatriculation : {vehicule.immatriculation}",
                     vehicule.kilometrage_actuel is not None and f"Kilométrage : {fmt_money(vehicule.kilometrage_actuel, 0, '', False)} km"):
            if line:
                veh_lines.append(_p(line, base))
    else:
        veh_lines.append(_p("—", base))
    parties = Table([[client_lines, veh_lines]], colWidths=[90 * mm, 90 * mm])
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (0, 0), 0.5, LINE),
                                 ("BOX", (1, 0), (1, 0), 0.5, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 6),
                                 ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))

    # ---- Lignes
    ht = " HT" if devis.tva_active else ""
    rows = [[_p("Désignation", bold), _p("Qté", right), _p(f"Prix unit.{ht}", right), _p("Remise", right), _p(f"Total{ht}", right)]]
    for ligne in devis.lignes:
        label = escape(ligne.designation)
        kind = TYPE_LABELS.get(ligne.type, "")
        cell = Paragraph(f"{label}<br/><font size='7' color='#6b7280'>{escape(kind)}</font>", base)
        unit = f" {escape(ligne.unite)}" if ligne.unite else ""
        rows.append([cell, Paragraph(fmt_qty(ligne.quantite) + unit, right),
                     _p(fmt_money(ligne.prix_unitaire, d, devise, False), right),
                     _p(f"{fmt_qty(ligne.remise_pct)} %" if Decimal(ligne.remise_pct or 0) else "", right),
                     _p(fmt_money(ligne.total_ht, d, devise, False), right)])
    table = Table(rows, colWidths=[78 * mm, 24 * mm, 30 * mm, 18 * mm, 30 * mm], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ecfdf5")),
                               ("LINEBELOW", (0, 0), (-1, 0), 0.8, TEAL), ("LINEBELOW", (0, 1), (-1, -1), 0.25, LINE),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))

    # ---- Totaux
    trows = []
    show_detail = devis.tva_active or Decimal(devis.remise_globale or 0) > 0
    if show_detail:
        trows.append([_p("Sous-total" + ht, base), _p(money(devis.sous_total_ht), right)])
    if Decimal(devis.remise_globale or 0) > 0:
        trows.append([_p("Remise", base), _p("- " + money(devis.remise_globale), right)])
    if devis.tva_active:
        trows.append([_p("Total HT", base), _p(money(devis.total_ht), right)])
        trows.append([_p(f"TVA ({fmt_qty(devis.tva_taux)} %)", base), _p(money(devis.total_tva), right)])
    trows.append([_p("TOTAL TTC" if devis.tva_active else "TOTAL", bold),
                  Paragraph(f"<b>{escape(money(devis.total_ttc))}</b>", ParagraphStyle("tt", parent=right, fontSize=11, leading=14))])
    totals = Table(trows, colWidths=[45 * mm, 45 * mm], hAlign="RIGHT")
    totals.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 0.8, TEAL), ("TOPPADDING", (0, 0), (-1, -1), 3),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))

    story = [header, Spacer(1, 6 * mm), parties, Spacer(1, 6 * mm), table, Spacer(1, 4 * mm), totals]
    if not devis.tva_active:
        story.append(Spacer(1, 1 * mm))
        story.append(_p("TVA non applicable.", ParagraphStyle("na", parent=small, alignment=TA_RIGHT)))
    if devis.conditions:
        story += [Spacer(1, 6 * mm), _p("Conditions", bold), _p(devis.conditions, base)]
    story.append(Spacer(1, 8 * mm))
    if devis.statut == "accepte":
        who = devis.acceptation_nom or ""
        story.append(_p(f"Devis accepté par {who} le {fmt_date(devis.accepte_le)}.", bold))
    elif devis.statut == "envoye":
        box = Table([[_p("Bon pour accord - nom, date et signature du client :", base)]], colWidths=[180 * mm], rowHeights=[28 * mm])
        box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 6)]))
        story.append(box)

    def decorate(canvas, doc):
        canvas.saveState()
        if is_draft:
            canvas.setFont("Helvetica-Bold", 70)
            canvas.setFillGray(0.92)
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(45)
            canvas.drawCentredString(0, 0, "BROUILLON")
        canvas.restoreState()
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(GREY)
        canvas.drawString(15 * mm, 10 * mm, f"{garage.nom_garage} - Devis {number}")
        canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
                            bottomMargin=18 * mm, title=f"Devis {number}", author=garage.nom_garage)
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


def pdf_response(devis, garage, client, vehicule):
    """Réponse HTTP (application/pdf) pour un devis."""
    from flask import current_app, make_response

    logo = load_logo(garage, current_app.config.get("UPLOAD_FOLDER"))
    resp = make_response(render_devis_pdf(devis, garage, client, vehicule, logo))
    resp.headers["Content-Type"] = "application/pdf"
    name = f"Devis-{devis.numero}" if devis.numero else "Devis-brouillon"
    resp.headers["Content-Disposition"] = f'inline; filename="{name}.pdf"'
    resp.headers["Cache-Control"] = "private, no-store"
    return resp
