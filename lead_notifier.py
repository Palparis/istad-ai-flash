"""IstadAi - Notification email du lead à chaque audit flash complété.

Envoie à pierre-alain.laval@istada.fr un mail récapitulatif avec :
- L'identité du lead (nom, email, téléphone)
- L'organisation et le rôle
- Le score global + niveau + 8 axes
- Les forces et zones de progrès
- Les 8 verbatims qualitatifs
- La dissonance déclaratif/réel si présente
- Le PDF de synthèse en pièce jointe

Configuration via variables d'environnement (.env ou Streamlit secrets) :
    SMTP_HOST            = smtp.gmail.com
    SMTP_PORT            = 587
    SMTP_USER            = ton.adresse@gmail.com
    SMTP_PASSWORD        = app password Gmail (16 caractères)
    LEAD_NOTIFICATION_TO = pierre-alain.laval@istada.fr

Si SMTP_USER ou SMTP_PASSWORD ne sont pas définis, l'envoi est skippé
silencieusement (mode dev local) - un warning apparaît dans les logs.
"""

from __future__ import annotations

import logging
import os
import re
import smtplib
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from scoring_flash import FlashResult

logger = logging.getLogger(__name__)


# ============================================================
# Validation des champs
# ============================================================

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def is_valid_email(value: str) -> bool:
    return bool(EMAIL_RE.match((value or "").strip()))


def is_valid_phone(value: str) -> bool:
    """Validation laxe : au moins 8 chiffres après nettoyage."""
    digits = re.sub(r"\D", "", value or "")
    return len(digits) >= 8


# ============================================================
# Envoi de la notification
# ============================================================

def send_lead_notification(
    result: FlashResult,
    lead_email: str,
    lead_first_name: str,
    lead_last_name: str,
    lead_phone: str,
    pdf_bytes: bytes | None = None,
) -> tuple[bool, str]:
    """Envoie une notification email à IstadAi avec le récap de l'audit.

    Returns:
        (success: bool, message: str)
    """
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    to_email = os.environ.get(
        "LEAD_NOTIFICATION_TO", "pierre-alain.laval@istada.fr"
    )

    # Nettoyage défensif des credentials :
    # - retire les whitespace (espaces normaux, tabs, newlines)
    # - retire les espaces insécables \xa0 qui se glissent quand on copie-colle
    #   l'App Password depuis l'interface Google (qui affiche "abcd efgh ...").
    # str.split() sans argument fractionne sur tous les whitespace dont \xa0,
    # donc "".join(s.split()) garantit une chaîne sans aucun blanc.
    if smtp_user:
        smtp_user = "".join(smtp_user.split())
    if smtp_password:
        smtp_password = "".join(smtp_password.split())

    # En l'absence de credentials, on log mais on n'échoue pas
    # (mode dev - permet de tester sans configurer SMTP)
    if not smtp_user or not smtp_password:
        logger.warning(
            "SMTP non configuré - notification skippée. Lead : %s %s (%s, %s) - %s",
            lead_first_name, lead_last_name, lead_email, lead_phone,
            result.organization,
        )
        return False, "SMTP non configuré (mode dev)."

    # ── Construction du mail ──
    msg = MIMEMultipart()
    msg["Subject"] = (
        f"🎯 Nouveau lead Audit Flash IstadAi - "
        f"{lead_first_name} {lead_last_name} ({result.organization})"
    )
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg["Reply-To"] = lead_email  # permet de répondre directement au lead

    html_body = _build_lead_email_html(
        result, lead_email, lead_first_name, lead_last_name, lead_phone
    )
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # ── PDF en pièce jointe ──
    if pdf_bytes:
        attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
        safe_org = "".join(
            c if c.isalnum() or c in "_-" else "_"
            for c in result.organization
        )
        filename = f"AuditFlash_{safe_org}_{datetime.now().strftime('%Y-%m-%d')}.pdf"
        attachment.add_header(
            "Content-Disposition", "attachment", filename=filename,
        )
        msg.attach(attachment)

    # ── Envoi SMTP ──
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        logger.info(
            "Notification lead envoyée : %s %s <%s> - %s (score %.2f/5)",
            lead_first_name, lead_last_name, lead_email,
            result.organization, result.global_score,
        )
        return True, "Notification envoyée."
    except Exception as exc:
        logger.exception("Erreur SMTP lors de l'envoi de la notification lead")
        return False, f"Erreur SMTP : {exc}"


# ============================================================
# Template HTML du mail récapitulatif
# ============================================================

def _build_lead_email_html(
    result: FlashResult,
    lead_email: str,
    lead_first_name: str,
    lead_last_name: str,
    lead_phone: str,
) -> str:
    """Construit le corps HTML du mail récap."""
    now_str = datetime.now().strftime("%d/%m/%Y à %H:%M")

    # Forces
    if result.strengths:
        strengths_html = "".join(
            f"<li><b>{code}</b> - {name} ({score}/5)</li>"
            for code, name, score in result.strengths
        )
    else:
        strengths_html = "<li><em>Aucune force marquée - terrain d'opportunité large.</em></li>"

    # Zones de progrès
    gaps_html = "".join(
        f"<li><b>{code}</b> - {name} ({score}/5)</li>"
        for code, name, score in result.gaps
    )

    # Tous les scores axe par axe
    axis_scores_html = "".join(
        f"<tr><td><b>{code}</b> - {result.axis_names[code]}</td>"
        f"<td style='text-align: right;'>{score} / 5</td></tr>"
        for code, score in result.axis_scores.items()
    )

    # Verbatims
    if result.text_inputs:
        verbatims_html = "".join(
            f"<p style='margin: 8px 0;'><b>{code} - {result.axis_names[code]}</b><br>"
            f"<em>« {quote} »</em></p>"
            for code, quote in result.text_inputs.items()
        )
    else:
        verbatims_html = "<p><em>Aucun verbatim fourni par le répondant.</em></p>"

    # Dissonance
    dissonance_html = ""
    if result.has_dissonance:
        dissonance_html = f"""
        <div style="background: #FFF3E0; padding: 12px; border-left: 4px solid #F57C00;
                    margin: 12px 0;">
            <b>⚠️ Dissonance déclaratif / réel :</b><br>
            Maturité déclarée <b>{result.global_score:.2f}/5</b> vs maturité réelle
            (cas d'usage en prod) <b>{result.q9_real_score}/5</b> - écart de
            <b>{result.dissonance_declaratif_vs_reel:.1f} point</b>. Signal classique
            d'organisation en phase d'ambition à challenger en restitution.
        </div>
        """

    return f"""
    <html><body style="font-family: -apple-system, Helvetica, Arial, sans-serif;
                       color: #1A1A1A; max-width: 720px; line-height: 1.5;">

    <h2 style="color: #1F365A; margin-bottom: 4px;">
        🎯 Nouveau lead Audit Flash
    </h2>
    <p style="color: #666; margin-top: 0; font-size: 13px;">
        Audit complété le {now_str}
    </p>

    <h3 style="color: #1F365A; border-bottom: 1px solid #ddd; padding-bottom: 4px;">
        Lead
    </h3>
    <table style="border-collapse: collapse; width: 100%;">
        <tr><td style="padding: 4px 12px 4px 0;"><b>Nom</b></td>
            <td>{lead_first_name} {lead_last_name}</td></tr>
        <tr><td style="padding: 4px 12px 4px 0;"><b>Email</b></td>
            <td><a href="mailto:{lead_email}">{lead_email}</a></td></tr>
        <tr><td style="padding: 4px 12px 4px 0;"><b>Téléphone</b></td>
            <td><a href="tel:{lead_phone}">{lead_phone}</a></td></tr>
        <tr><td style="padding: 4px 12px 4px 0;"><b>Organisation</b></td>
            <td>{result.organization}</td></tr>
        <tr><td style="padding: 4px 12px 4px 0;"><b>Rôle</b></td>
            <td>{result.role}</td></tr>
    </table>

    <h3 style="color: #1F365A; border-bottom: 1px solid #ddd; padding-bottom: 4px;
               margin-top: 24px;">
        Résultat global
    </h3>
    <p style="font-size: 18px; margin: 8px 0;">
        <b>{result.global_score:.2f} / 5</b> &nbsp;·&nbsp;
        <span style="color: {result.level_color};">●</span>
        <b>Niveau {result.level} - {result.level_name}</b>
    </p>
    <p style="color: #666; font-style: italic; margin-top: 0;">
        « {result.level_description} »
    </p>

    {dissonance_html}

    <h3 style="color: #1F365A; border-bottom: 1px solid #ddd; padding-bottom: 4px;
               margin-top: 24px;">
        Scores par axe
    </h3>
    <table style="border-collapse: collapse; width: 100%; font-size: 14px;">
        {axis_scores_html}
    </table>

    <h3 style="color: #388E3C; margin-top: 24px;">✅ Forces</h3>
    <ul>{strengths_html}</ul>

    <h3 style="color: #D32F2F; margin-top: 16px;">🎯 Zones de progrès prioritaires</h3>
    <ul>{gaps_html}</ul>

    <h3 style="color: #1F365A; border-bottom: 1px solid #ddd; padding-bottom: 4px;
               margin-top: 24px;">
        Verbatims qualitatifs
    </h3>
    {verbatims_html}

    <hr style="margin-top: 32px; border: none; border-top: 1px solid #ddd;">
    <p style="color: #999; font-size: 12px;">
        Mail généré automatiquement par l'app Audit Flash IstadAi.<br>
        Le PDF de synthèse complet est en pièce jointe.<br>
        Pour répondre au lead, utilise l'adresse en Reply-To (déjà préremplie).
    </p>
    </body></html>
    """
