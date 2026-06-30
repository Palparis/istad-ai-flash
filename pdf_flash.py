"""IstadAi - Génération du PDF de synthèse de l'audit flash.

1 page A4, sans LLM. Contient :
- En-tête : IstadAi - Audit Flash Maturité IA, organisation, date
- Score global + niveau
- Mini-radar 8 axes (matplotlib, carré strict)
- Vue forces / zones de progrès
- Phrases libres rapportées par axe (effet "rapport personnalisé")
- Dissonance déclaratif vs réel (si présente)
- CTA vers IstadAi
- Footer paginé (Page 1 / 1)
"""

from __future__ import annotations

import io
from datetime import date, datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from scoring_flash import FlashResult
from verbatim_analyzer import VerbatimAnalysis

# Couleurs IstadAi
# Palette IstadAi inspiree de la charte Istada (bleu marine + gris)
# Cf. assets/Charte Graphique.pptx pour les valeurs source.
COLOR_PRIMARY = colors.HexColor("#2E3A66")   # bleu marine Istada
COLOR_TEXT = colors.HexColor("#2D2D2D")      # gris fonce Istada
COLOR_MUTED = colors.HexColor("#808080")     # gris moyen Istada
COLOR_BG_LIGHT = colors.HexColor("#F2F4F8")  # blanc casse
COLOR_GREEN = colors.HexColor("#388E3C")     # vert semantique forces
COLOR_RED = colors.HexColor("#D32F2F")       # rouge semantique zones

MOIS_FR = {
    1: "janvier", 2: "février", 3: "mars", 4: "avril",
    5: "mai", 6: "juin", 7: "juillet", 8: "août",
    9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre",
}


def _format_date_fr(d) -> str:
    if isinstance(d, (date, datetime)):
        return f"{d.day} {MOIS_FR[d.month]} {d.year}"
    return str(d or "")


# ============================================================
# Radar mini (matplotlib, carré strict)
# ============================================================

def _render_radar_png(result: FlashResult) -> bytes:
    """Génère le radar 8 axes au format PNG."""
    codes = list(result.axis_scores.keys())
    labels = [f"{c} - {result.axis_names[c][:18]}" for c in codes]
    values = [result.axis_scores[c] for c in codes]

    n = len(codes)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    angles += angles[:1]
    values_closed = values + values[:1]

    fig, ax = plt.subplots(figsize=(6.0, 6.0), subplot_kw=dict(polar=True))
    fig.patch.set_facecolor("white")
    fig.subplots_adjust(left=0.16, right=0.84, top=0.92, bottom=0.08)

    ax.plot(angles, [5] * len(angles), color="#999999", linewidth=0.8, linestyle="--")
    ax.fill(angles, values_closed, color="#1F365A", alpha=0.18)
    ax.plot(angles, values_closed, color="#1F365A", linewidth=2)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, fontsize=8, color="#1A1A1A")
    ax.set_ylim(0, 5)
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.set_yticklabels(["1", "2", "3", "4", "5"], fontsize=7, color="#666666")
    ax.set_rlabel_position(45)
    ax.grid(color="#cccccc", linewidth=0.5)
    ax.spines["polar"].set_color("#999999")

    ax.set_title("Radar 8 axes - Score / 5", fontsize=9, color="#1F365A", pad=14)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


# ============================================================
# Canvas avec footer paginé (réutilisé d'agent-audit-maturite)
# ============================================================

class _NumberedCanvas(Canvas):
    """Canvas avec footer paginé 'Page X / Y'."""

    _footer_doc_name: str = "IstadAi - Audit Flash Maturité IA"
    _footer_mission: str = ""
    _footer_date: str = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total_pages: int):
        page_num = self._pageNumber
        page_width, _ = A4
        self.setStrokeColor(colors.HexColor("#CCCCCC"))
        self.setLineWidth(0.4)
        self.line(1.8 * cm, 1.05 * cm, page_width - 1.8 * cm, 1.05 * cm)
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#666666"))
        self.drawString(1.8 * cm, 0.75 * cm, self._footer_doc_name)
        center_text = f"{self._footer_mission}  ·  {self._footer_date}"
        self.drawCentredString(page_width / 2.0, 0.75 * cm, center_text)
        self.drawRightString(
            page_width - 1.8 * cm, 0.75 * cm,
            f"Page {page_num} / {total_pages}",
        )


# ============================================================
# Styles
# ============================================================

def _build_styles():
    return {
        "Title": ParagraphStyle(
            "Title", fontName="Helvetica-Bold", fontSize=14, leading=18,
            textColor=COLOR_PRIMARY, spaceAfter=2,
        ),
        "Subtitle": ParagraphStyle(
            "Subtitle", fontName="Helvetica", fontSize=8.5, leading=11,
            textColor=COLOR_MUTED, spaceAfter=4,
        ),
        "Section": ParagraphStyle(
            "Section", fontName="Helvetica-Bold", fontSize=9, leading=11,
            textColor=COLOR_PRIMARY, spaceBefore=6, spaceAfter=2,
        ),
        "Body": ParagraphStyle(
            "Body", fontName="Helvetica", fontSize=8.5, leading=11,
            textColor=COLOR_TEXT, alignment=TA_JUSTIFY, spaceAfter=3,
        ),
        "ScoreBig": ParagraphStyle(
            "ScoreBig", fontName="Helvetica-Bold", fontSize=24, leading=28,
            textColor=COLOR_PRIMARY, alignment=TA_LEFT,
        ),
        "ScoreLabel": ParagraphStyle(
            "ScoreLabel", fontName="Helvetica", fontSize=8, leading=10,
            textColor=COLOR_MUTED, alignment=TA_LEFT,
        ),
        "LevelBig": ParagraphStyle(
            "LevelBig", fontName="Helvetica-Bold", fontSize=13, leading=16,
            textColor=COLOR_PRIMARY, alignment=TA_LEFT,
        ),
        "Strength": ParagraphStyle(
            "Strength", fontName="Helvetica", fontSize=8.5, leading=11,
            textColor=COLOR_GREEN, leftIndent=8, spaceAfter=2,
        ),
        "Gap": ParagraphStyle(
            "Gap", fontName="Helvetica", fontSize=8.5, leading=11,
            textColor=COLOR_RED, leftIndent=8, spaceAfter=2,
        ),
        "Quote": ParagraphStyle(
            "Quote", fontName="Helvetica-Oblique", fontSize=8, leading=10.5,
            textColor=COLOR_TEXT, leftIndent=10, rightIndent=10,
            spaceAfter=3, spaceBefore=0,
        ),
        "CTA": ParagraphStyle(
            "CTA", fontName="Helvetica-Bold", fontSize=9, leading=11,
            textColor=COLOR_PRIMARY, alignment=TA_LEFT, spaceBefore=4,
        ),
        "Footer": ParagraphStyle(
            "Footer", fontName="Helvetica", fontSize=7.5, leading=10,
            textColor=COLOR_MUTED, alignment=TA_JUSTIFY, spaceBefore=6,
        ),
    }


# ============================================================
# Composants
# ============================================================

def _build_header_table(result: FlashResult, styles: dict) -> Table:
    """Bloc score + niveau côte à côte."""
    score_cell = [
        Paragraph("Score global", styles["ScoreLabel"]),
        Paragraph(f"{result.global_score:.2f} / 5", styles["ScoreBig"]),
    ]
    level_cell = [
        Paragraph("Niveau de maturité", styles["ScoreLabel"]),
        Paragraph(
            f'<font color="{result.level_color}">●</font> '
            f"{result.level} - {result.level_name}",
            styles["LevelBig"],
        ),
        Paragraph(
            f"<i>« {result.level_description} »</i>",
            ParagraphStyle(
                "LevelDesc", fontName="Helvetica", fontSize=8, leading=10,
                textColor=COLOR_TEXT,
            ),
        ),
    ]
    table = Table([[score_cell, level_cell]], colWidths=[5.0 * cm, 12.0 * cm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _build_strengths_gaps_table(
    result: FlashResult,
    styles: dict,
    verbatim_analysis: VerbatimAnalysis | None = None,
) -> Table:
    """Forces et zones de progres empilees verticalement (une colonne).

    Avant : 2 colonnes cote a cote de 8.5 cm chacune, soit 17 cm. Probleme :
    cette sous-table devait tenir dans la colonne droite (8.6 cm) a cote du
    radar, et debordait largement. Nouveau layout : une seule colonne qui
    s'inscrit dans les 8.6 cm disponibles.

    Si verbatim_analysis est fourni, on enrichit chaque cartouche d'une
    insight LLM courte (1 phrase) sous le code + nom + score.
    """
    rows = []
    forces_insights = verbatim_analysis.forces_insights if verbatim_analysis else {}
    zones_insights = verbatim_analysis.zones_insights if verbatim_analysis else {}

    # Bloc Forces
    rows.append([Paragraph("<b>Forces (axes &ge; 4 / 5)</b>", styles["Section"])])
    if result.strengths:
        for code, name, score in result.strengths:
            line = f"<b>{code}</b> - {name} ({score}/5)"
            insight = forces_insights.get(code)
            if insight:
                line += f"<br/><font size=\"8\">{insight}</font>"
            rows.append([Paragraph(line, styles["Strength"])])
    else:
        rows.append([Paragraph(
            "Aucun axe ne ressort en force marquée - terrain d'opportunité.",
            styles["Body"],
        )])

    # Bloc Opportunités prioritaires
    rows.append([Paragraph("<b>Opportunités prioritaires</b>", styles["Section"])])
    for code, name, score in result.gaps:
        line = f"<b>{code}</b> - {name} ({score}/5)"
        insight = zones_insights.get(code)
        if insight:
            line += f"<br/><font size=\"8\">{insight}</font>"
        rows.append([Paragraph(line, styles["Gap"])])

    table = Table(rows, colWidths=[8.5 * cm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


# ============================================================
# Build PDF
# ============================================================

def generate_flash_pdf(
    result: FlashResult,
    verbatim_analysis: VerbatimAnalysis | None = None,
) -> bytes:
    """Génère le PDF de synthèse de l'audit flash.

    Si verbatim_analysis est fourni (analyse LLM Anthropic des phrases libres),
    le PDF contient une section supplémentaire 'Lecture personnalisée IstadAi'
    avec le commentaire LLM + les dissonances détectées.
    """
    styles = _build_styles()
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.8 * cm,
        title="Audit Flash Maturité IA",
        author="IstadAi",
    )

    date_str = _format_date_fr(date.today())
    story = []

    # ── En-tête ──
    story.append(Paragraph(
        "IstadAi - Audit Flash Maturité IA", styles["Title"]
    ))
    story.append(Paragraph(
        f"Organisation : <b>{result.organization}</b> &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"Répondant : <b>{result.role}</b> &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"Date : <b>{date_str}</b>",
        styles["Subtitle"],
    ))
    story.append(Spacer(1, 4))

    # ── Score + Niveau ──
    story.append(_build_header_table(result, styles))
    story.append(Spacer(1, 6))

    # ── Radar + Forces/Gaps côte à côte ──
    radar_png = _render_radar_png(result)
    radar_img = Image(io.BytesIO(radar_png), width=8.5 * cm, height=8.5 * cm)
    radar_img.hAlign = "CENTER"

    sg_block = _build_strengths_gaps_table(result, styles, verbatim_analysis)

    # Layout 2 colonnes : radar à gauche, forces+gaps à droite
    inner_table = Table(
        [[radar_img, sg_block]],
        colWidths=[8.6 * cm, 8.6 * cm],
    )
    inner_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(inner_table)

    # ── Stack IA déclaré (multiselect Q3) ──
    ia_stack_d = result.multiselects.get("D", [])
    if ia_stack_d:
        story.append(Paragraph(
            "VOTRE STACK IA DECLARE", styles["Section"]
        ))
        story.append(Paragraph(
            ", ".join(ia_stack_d),
            styles["Body"],
        ))

    # ── Phrases libres ──
    if result.text_inputs:
        story.append(Paragraph(
            "VOS APPORTS QUALITATIFS - VERBATIMS", styles["Section"]
        ))
        for code in result.axis_scores:
            if code in result.text_inputs:
                name = result.axis_names[code]
                quote = result.text_inputs[code]
                story.append(Paragraph(
                    f'<b>{code} - {name}</b> : <i>« {quote} »</i>',
                    styles["Quote"],
                ))

    # ── Analyse personnalisée Claude (si présente) ──
    if verbatim_analysis is not None and verbatim_analysis.commentaire_personnalise:
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            "LECTURE PERSONNALISEE PAR CLAUDE",
            styles["Section"],
        ))
        # Le commentaire LLM peut contenir des sauts de ligne entre paragraphes.
        # On les convertit en balises <br/> pour ReportLab.
        commentaire_html = verbatim_analysis.commentaire_personnalise.replace(
            "\n\n", "<br/><br/>"
        ).replace("\n", "<br/>")
        story.append(Paragraph(commentaire_html, styles["Body"]))

        # Cas d'usage IA recommandés
        if verbatim_analysis.cas_usage_recommandes:
            story.append(Spacer(1, 4))
            story.append(Paragraph(
                "CAS D'USAGE IA RECOMMANDES POUR VOTRE SITUATION",
                styles["Section"],
            ))
            for cu in verbatim_analysis.cas_usage_recommandes:
                story.append(Paragraph(
                    f"&#8226; {cu}",
                    styles["Body"],
                ))

        # Trois types de dissonances rendus séparément pour clarté
        def _append_dissonance_block(title: str, items: list[str]):
            if not items:
                return
            story.append(Spacer(1, 2))
            story.append(Paragraph(f"<b>{title}</b>", styles["Body"]))
            for d in items:
                story.append(Paragraph(
                    f"<i>{d}</i>",
                    styles["Quote"],
                ))

        _append_dissonance_block(
            "Dissonances entre vos verbatims libres :",
            verbatim_analysis.dissonances_verbatims,
        )
        _append_dissonance_block(
            "Dissonances entre vos verbatims et les options choisies :",
            verbatim_analysis.dissonances_verbatim_vs_ancre,
        )
        _append_dissonance_block(
            "Dissonances entre vos scores d'axes (strategy vs execution) :",
            verbatim_analysis.dissonances_ancres,
        )

    # ── CTA ──
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "POUR ALLER PLUS LOIN", styles["Section"]
    ))
    story.append(Paragraph(
        "Cet audit flash est un pré-diagnostic indicatif. Pour un audit complet "
        "(entretiens multi-sponsors, analyses augmentées par l'IA de votre "
        "organisation (architecture BYOLLM), cross-check budget IT, plan de "
        "transformation actionnable), contactez IstadAi : "
        '<a href="mailto:pierre-alain.laval@istada.fr"><b>pierre-alain.laval@istada.fr</b></a>',
        styles["Body"],
    ))

    # ── Annexe : réponses détaillées (traçabilité RGPD) ──
    story.append(PageBreak())
    story.append(Paragraph(
        "ANNEXE - VOS REPONSES DETAILLEES",
        styles["Title"],
    ))
    story.append(Paragraph(
        f"Organisation : <b>{result.organization}</b> &nbsp;|&nbsp; "
        f"Répondant : <b>{result.role}</b> &nbsp;|&nbsp; "
        f"Date : <b>{date_str}</b>",
        styles["Subtitle"],
    ))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Cette annexe restitue intégralement les réponses fournies lors de "
        "l'audit, afin que vous puissiez les relire, les contester ou les "
        "réutiliser. Conformité RGPD : ces données vous appartiennent.",
        styles["Body"],
    ))
    story.append(Spacer(1, 6))

    # Pour chaque axe scoré, on liste : nom, ancre choisie, multiselect, verbatim
    for code in result.axis_scores:
        name = result.axis_names.get(code, code)
        score = result.axis_scores[code]
        anchor_text = result.chosen_anchors.get(code, "(non renseigné)")

        story.append(Paragraph(
            f"<b>{code} - {name}</b> &nbsp;|&nbsp; "
            f"Score auto-évalué : <b>{score} / 5</b>",
            styles["Section"],
        ))
        story.append(Paragraph(
            f"<i>Ancre choisie :</i> {anchor_text}",
            styles["Body"],
        ))

        # Multiselect (stack IA pour D, potentiellement d'autres axes plus tard)
        ms_choices = result.multiselects.get(code, [])
        if ms_choices:
            story.append(Paragraph(
                "<i>Outils ou éléments cochés :</i>",
                styles["Body"],
            ))
            for choice in ms_choices:
                story.append(Paragraph(
                    f"{choice}",
                    styles["Body"],
                ))

        # Verbatim libre
        verbatim = result.text_inputs.get(code, "")
        if verbatim:
            story.append(Paragraph(
                f"<i>Votre verbatim :</i> &laquo; {verbatim} &raquo;",
                styles["Body"],
            ))
        else:
            story.append(Paragraph(
                "<i>Votre verbatim :</i> (non renseigné)",
                styles["Body"],
            ))
        story.append(Spacer(1, 4))

    # Question transverse Q9 - irritants quotidiens
    if result.irritants:
        story.append(Paragraph(
            "<b>Question transverse - Irritants quotidiens</b>",
            styles["Section"],
        ))
        story.append(Paragraph(
            f"<i>Réponse libre :</i> &laquo; {result.irritants} &raquo;",
            styles["Body"],
        ))
        story.append(Spacer(1, 8))

    # Rappel du score global et du niveau
    story.append(Paragraph(
        f"<b>Score global calculé</b> : moyenne arithmétique des 8 axes = "
        f"<b>{result.global_score:.2f} / 5</b> (niveau {result.level} - "
        f"{result.level_name})",
        styles["Body"],
    ))

    # ── Footer méthodologique ──
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "<b>Méthodologie IstadAi</b> - Audit flash construit sur le framework "
        "propriétaire IstadAi Maturity Model (8 axes / 80 items / 480 ancres "
        "comportementales). Sources théoriques : Harvard AI for Leaders (M1-M4), "
        "Gartner AI Maturity Model, expérience cabinet terrain ETI. Scoring 100 % "
        "déterministe et traçable - à scores identiques, conclusions identiques. "
        "L'analyse qualitative optionnelle des verbatims libres (si consentement "
        "accordé) est réalisée par Claude (Anthropic) en tant que sous-traitant, "
        "sans utilisation des données pour l'entraînement et avec rétention "
        "limitée à 30 jours. Dans l'<b>audit complet</b> d'IstadAi (extraction "
        "signaux entretiens, détection dissonances multi-sponsors, narration "
        "livrables COMEX), l'IA est opérée via <b>l'instance IA de votre "
        "organisation</b> (architecture <b>BYOLLM</b>, <i>Bring Your Own LLM</i>) "
        "pour préserver la confidentialité, la souveraineté et la conformité de "
        "vos données. Résultat indicatif - ne se substitue pas à un audit "
        "professionnel motivé.",
        styles["Footer"],
    ))

    # Injecter les métadonnées du footer paginé
    _NumberedCanvas._footer_doc_name = "IstadAi - Audit Flash Maturité IA"
    _NumberedCanvas._footer_mission = result.organization
    _NumberedCanvas._footer_date = date_str

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()
