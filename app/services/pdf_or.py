"""PDF de l'ordre de réparation (bon d'entrée) avec autorisation de travaux à signer."""
import io

from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.pdf_devis import GREY, LINE, TEAL, _p, fmt_date, fmt_money, load_logo

AUTORISATION = ("Le client autorise le garage à effectuer le diagnostic et les travaux décrits ci-dessus. "
                "Tout travail supplémentaire fera l'objet d'un devis soumis à son accord. "
                "Le garage décline toute responsabilité pour les objets de valeur laissés dans le véhicule.")


def render_or_pdf(ordre, garage, client, vehicule, mecanicien_nom=None, logo_bytes=None) -> bytes:
    styles = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=12)
    small = ParagraphStyle("small", parent=base, fontSize=8, textColor=GREY)
    bold = ParagraphStyle("bold", parent=base, fontName="Helvetica-Bold")
    right = ParagraphStyle("right", parent=base, alignment=TA_RIGHT)
    title = ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=TEAL, alignment=TA_RIGHT)

    left = []
    if logo_bytes:
        try:
            w, h = ImageReader(io.BytesIO(logo_bytes)).getSize()
            scale = min(45 * mm / w, 22 * mm / h)
            left += [Image(io.BytesIO(logo_bytes), width=w * scale, height=h * scale, hAlign="LEFT"), Spacer(1, 2 * mm)]
        except Exception:  # noqa: BLE001
            pass
    left.append(_p(garage.nom_garage, ParagraphStyle("gn", parent=bold, fontSize=12, leading=15)))
    for line in (", ".join(x for x in (garage.adresse, garage.ville) if x), garage.telephone, garage.email):
        if line:
            left.append(_p(line, base))
    ids = " · ".join(x for x in ((f"IFU : {garage.ifu}" if garage.ifu else ""), (f"RCCM : {garage.rccm}" if garage.rccm else "")) if x)
    if ids:
        left.append(_p(ids, small))
    right_block = [Paragraph("ORDRE DE RÉPARATION", title),
                   _p(f"N° {ordre.numero}", ParagraphStyle("n", parent=right, fontName="Helvetica-Bold", fontSize=11, leading=14)),
                   _p(f"Date d'entrée : {fmt_date(ordre.date_entree)}", right)]
    if ordre.date_sortie_prevue:
        right_block.append(_p(f"Sortie prévue : {fmt_date(ordre.date_sortie_prevue)}", right))
    if ordre.urgent:
        right_block.append(_p("URGENT", ParagraphStyle("u", parent=right, fontName="Helvetica-Bold", textColor=TEAL)))
    header = Table([[left, right_block]], colWidths=[95 * mm, 85 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))

    client_lines = [_p("CLIENT", small), _p(client.nom_affiche, bold)]
    for line in (client.telephone, client.email):
        if line:
            client_lines.append(_p(line, base))
    veh_lines = [_p("VÉHICULE", small), _p(f"{vehicule.marque} {vehicule.modele}", bold)]
    for line in (vehicule.immatriculation and f"Immatriculation : {vehicule.immatriculation}",
                 vehicule.vin and f"Châssis : {vehicule.vin}",
                 ordre.kilometrage_entree is not None and f"Kilométrage à l'entrée : {fmt_money(ordre.kilometrage_entree, 0, '', False)} km",
                 ordre.niveau_carburant is not None and f"Niveau de carburant : {ordre.niveau_carburant} %"):
        if line:
            veh_lines.append(_p(line, base))
    parties = Table([[client_lines, veh_lines]], colWidths=[90 * mm, 90 * mm])
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (0, 0), 0.5, LINE), ("BOX", (1, 0), (1, 0), 0.5, LINE),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))

    story = [header, Spacer(1, 6 * mm), parties, Spacer(1, 6 * mm), _p("Motif de la visite", bold), _p(ordre.motif, base)]
    for label, text in (("Symptômes décrits par le client", ordre.symptomes), ("État du véhicule à l'arrivée", ordre.etat_arrivee),
                        ("Diagnostic", ordre.diagnostic), ("Travaux effectués", ordre.travaux_effectues)):
        if text:
            story += [Spacer(1, 4 * mm), _p(label, bold), _p(text, base)]
    if mecanicien_nom:
        story += [Spacer(1, 4 * mm), _p(f"Mécanicien responsable : {mecanicien_nom}", base)]
    story += [Spacer(1, 8 * mm), _p("Autorisation de travaux", bold), _p(AUTORISATION, base), Spacer(1, 3 * mm)]
    if ordre.signature_nom:
        story.append(_p(f"Autorisé par {ordre.signature_nom} le {fmt_date(ordre.signature_date)}.", bold))
    else:
        box = Table([[_p("Nom, date et signature du client :", base)]], colWidths=[180 * mm], rowHeights=[28 * mm])
        box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 6)]))
        story.append(box)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(GREY)
        canvas.drawString(15 * mm, 10 * mm, f"{garage.nom_garage} - Ordre de réparation {ordre.numero}")
        canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=18 * mm,
                            title=f"Ordre de réparation {ordre.numero}", author=garage.nom_garage)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def pdf_or_response(ordre, garage, client, vehicule, mecanicien):
    from flask import current_app, make_response

    logo = load_logo(garage, current_app.config.get("UPLOAD_FOLDER"))
    resp = make_response(render_or_pdf(ordre, garage, client, vehicule, mecanicien.nom_complet if mecanicien else None, logo))
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = f'inline; filename="{ordre.numero}.pdf"'
    resp.headers["Cache-Control"] = "private, no-store"
    return resp
