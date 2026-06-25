"""IstadAi - Audit Flash Maturité IA (v0 lean)
================================================

App Streamlit autonome : 10 questions, scoring déterministe, PDF synthèse.
Lien partageable pour test marché - pas de landing, pas de capture lead,
pas de LLM dans la boucle.

Lancer en local :
    cd istad-ai/agent-audit-flash
    streamlit run app.py

Déployer sur Streamlit Cloud :
    1. Push le repo IstadAi sur GitHub (déjà fait - privé)
    2. Aller sur https://share.streamlit.io et connecter le repo
    3. Path : istad-ai/agent-audit-flash/app.py
    4. Récupérer l'URL : https://istad-ai-flash.streamlit.app/
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import quote

import plotly.graph_objects as go
import streamlit as st

from dotenv import load_dotenv

from lead_notifier import is_valid_email, is_valid_phone, send_lead_notification
from pdf_flash import generate_flash_pdf
from scoring_flash import compute_flash_result, load_questions

# Charger .env du monorepo (pour SMTP credentials en dev local)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ============================================================
# Config Streamlit
# ============================================================

st.set_page_config(
    page_title="IstadAi - Audit Flash Maturité IA",
    page_icon="🎯",
    layout="centered",  # centré pour effet "tunnel"
    initial_sidebar_state="collapsed",
)

# ============================================================
# Style CSS minimal pour adoucir l'UI
# ============================================================

st.markdown("""
    <style>
        .main .block-container { padding-top: 2rem; max-width: 800px; }
        h1 { color: #1F365A; }
        h2, h3 { color: #1F365A; margin-top: 1.5rem; }
        .stRadio label { font-size: 0.95rem; }
        .istad-tagline {
            color: #666; font-size: 0.85rem;
            margin-top: -0.5rem; margin-bottom: 2rem;
        }
    </style>
""", unsafe_allow_html=True)


# ============================================================
# Helpers session
# ============================================================

@st.cache_resource
def get_questions_config() -> dict:
    return load_questions(Path(__file__).parent / "questions_flash.yaml")


def reset_session():
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def _scroll_to_top() -> None:
    """Force le scroll en haut de page après un st.rerun().

    Streamlit conserve par défaut la position de scroll entre les reruns,
    ce qui donne une UX cassée quand on passe d'une vue courte (intro)
    à une vue longue (questionnaire). Ce hack injecte un petit script JS
    qui scrolle au top dès que le composant est monté.
    """
    import streamlit.components.v1 as components
    components.html(
        """
        <script>
            setTimeout(function() {
                const doc = window.parent.document;
                const main = doc.querySelector('section.main')
                          || doc.querySelector('div.main')
                          || doc.querySelector('.stApp');
                if (main) main.scrollTo({top: 0, behavior: 'instant'});
                window.parent.scrollTo({top: 0, behavior: 'instant'});
            }, 50);
        </script>
        """,
        height=0,
    )


# ============================================================
# Vue 1 - Consentement + identification organisation
# ============================================================

def render_intro(config: dict) -> None:
    st.title("🎯 Audit Flash Maturité IA")
    st.markdown(
        '<div class="istad-tagline">Un pré-diagnostic en 10 questions - '
        "5 à 10 minutes - proposé par IstadAi.</div>",
        unsafe_allow_html=True,
    )

    st.markdown("### Ce que vous allez recevoir")
    st.markdown(
        "- Un **score global** sur 5 et votre **niveau de maturité** (1 à 5)\n"
        "- Un **radar 8 axes** : Vision, Portefeuille, Données, Organisation, "
        "Talent, Adoption, ROI, Gouvernance\n"
        "- Vos **forces** et vos **zones de progrès prioritaires**\n"
        "- Un **PDF de synthèse** d'une page, téléchargeable, à partager en interne"
    )

    st.markdown("### Avant de démarrer")
    st.info(config["consent_text"])

    with st.form("intro_form"):
        org = st.text_input(
            "Nom de votre organisation",
            help="Apparaîtra sur votre rapport. Non collecté côté serveur.",
            placeholder="ex. ACME, MaSociété, etc.",
        )
        role = st.selectbox(
            "Votre rôle",
            options=config["roles"],
            index=0,
            help="Sert uniquement à contextualiser votre rapport - non scoré.",
        )
        consent = st.checkbox(
            "Je comprends que cet audit est gratuit, qu'il restitue un scoring "
            "déterministe selon la méthodologie IstadAi, qu'il me sera demandé "
            "mes coordonnées professionnelles pour accéder à ma synthèse, et "
            "qu'il ne se substitue pas à un audit professionnel motivé.",
            value=False,
        )
        submitted = st.form_submit_button(
            "Commencer l'audit →", type="primary", use_container_width=True,
        )

    if submitted:
        if not org.strip():
            st.error("Merci d'indiquer un nom d'organisation.")
            return
        if not consent:
            st.error("Vous devez cocher la case de consentement pour continuer.")
            return
        st.session_state["organization"] = org.strip()
        st.session_state["role"] = role
        st.session_state["started"] = True
        st.rerun()


# ============================================================
# Vue 2 - Le questionnaire (toutes les questions sur une page)
# ============================================================

def render_questionnaire(config: dict) -> None:
    _scroll_to_top()
    st.title("🎯 Audit Flash Maturité IA")
    st.caption(
        f"Organisation : **{st.session_state['organization']}**  ·  "
        f"Répondant : **{st.session_state['role']}**"
    )
    st.divider()

    st.markdown(
        "Pour chaque axe, vous pouvez :\n"
        "- Décrire votre situation actuelle en une phrase (optionnel - apparaîtra "
        "dans votre rapport)\n"
        "- Indiquer où vous placez votre organisation sur l'échelle 1-5 (obligatoire)"
    )

    st.info(
        "**Lecture des options proposées** : les 5 niveaux affichés sont des "
        "repères illustratifs qui correspondent aux situations les plus "
        "fréquemment observées en ETI. Si votre situation ne correspond à "
        "aucune des descriptions exactement, choisissez celle qui s'en "
        "rapproche le plus, ou notez selon votre propre lecture sur "
        "l'échelle (1 = situation très peu avancée ; 5 = situation très "
        "avancée, sous contrôle, mesurée). Vous pouvez nuancer dans le "
        "champ texte libre situé au-dessus de chaque échelle."
    )

    st.markdown("---")

    questions = config["questions"]
    answers: dict = {}

    with st.form("questionnaire_form"):
        for i, q in enumerate(questions, 1):
            qid = q["id"]
            st.markdown(
                f"### {i}. {q['axis_code']} - {q['axis_name']}"
                if not q["axis_code"].startswith("TRANSVERSE")
                else f"### {i}. {q['axis_name']} *(transverse)*"
            )

            # Champ texte libre (si défini)
            if q.get("text_prompt"):
                txt = st.text_area(
                    q["text_prompt"],
                    key=f"{qid}_text",
                    placeholder="Optionnel - apparaîtra dans votre rapport et nourrira notre échange si vous souhaitez approfondir.",
                    max_chars=200,
                    height=80,
                )
                answers[f"{qid}_text"] = txt or ""

            # Auto-évaluation 5 ancres
            anchor_labels = [
                f"{level} - {q['anchors'][level]}"
                for level in sorted(q["anchors"].keys())
            ]
            choice = st.radio(
                q["eval_prompt"],
                options=anchor_labels,
                index=None,
                key=f"{qid}_radio",
            )
            if choice is not None:
                # Extraire le numéro (premier caractère)
                answers[qid] = int(choice.split(" - ", 1)[0])

            st.markdown("---")

        submitted = st.form_submit_button(
            "Voir mes résultats →", type="primary", use_container_width=True,
        )

    if submitted:
        # Vérifier que toutes les questions sont répondues
        missing = [q["id"] for q in questions if q["id"] not in answers]
        if missing:
            st.error(
                f"Merci de répondre à toutes les questions ({len(missing)} "
                f"question{'s' if len(missing) > 1 else ''} restante"
                f"{'s' if len(missing) > 1 else ''})."
            )
            return

        # Tout est OK : calculer + ranger en session
        answers["role"] = st.session_state["role"]
        answers["organization"] = st.session_state["organization"]
        result = compute_flash_result(config, answers)
        st.session_state["result"] = result
        st.rerun()


# ============================================================
# Vue intermédiaire - Gate email
# ============================================================

def render_email_gate(config: dict) -> None:
    """Vue intermédiaire entre questionnaire et résultats.

    Capture nom + email + téléphone, envoie la notification mail à IstadAi
    avec le PDF en pièce jointe, puis débloque l'accès aux résultats.
    """
    _scroll_to_top()
    result = st.session_state["result"]

    st.title("🎯 Votre audit est terminé")
    st.markdown(
        '<div class="istad-tagline">Une dernière étape avant de découvrir vos résultats.</div>',
        unsafe_allow_html=True,
    )

    st.success(
        f"✓ Questionnaire complété pour **{result.organization}**. "
        f"Votre synthèse personnalisée est prête."
    )

    st.markdown("### Recevez votre synthèse personnalisée")
    st.markdown(
        "Pour accéder à vos résultats et à votre PDF de synthèse, indiquez "
        "vos coordonnées. **Pierre-Alain Laval (IstadAi)** vous recontactera "
        "personnellement pour échanger sur vos résultats."
    )

    with st.form("lead_capture_form"):
        c1, c2 = st.columns(2)
        with c1:
            first_name = st.text_input(
                "Prénom *",
                key="lead_first_name",
                placeholder="Marie",
            )
        with c2:
            last_name = st.text_input(
                "Nom *",
                key="lead_last_name",
                placeholder="Dupont",
            )

        email = st.text_input(
            "Adresse email professionnelle *",
            key="lead_email",
            placeholder="marie.dupont@acme.fr",
        )

        phone = st.text_input(
            "Téléphone *",
            key="lead_phone",
            placeholder="06 12 34 56 78  ou  +33 6 12 34 56 78",
        )

        st.caption(
            "Vos coordonnées sont collectées par IstadAi uniquement pour vous "
            "transmettre votre synthèse et vous recontacter sur les suites. "
            "Conservées 12 mois maximum, jamais partagées avec un tiers. "
            "Suppression à tout moment sur demande à pierre-alain.laval@istada.fr."
        )

        gdpr_consent = st.checkbox(
            "J'accepte d'être recontacté(e) par IstadAi à propos de cet audit.",
            value=False,
        )

        submitted = st.form_submit_button(
            "Voir mes résultats →", type="primary", use_container_width=True,
        )

    if submitted:
        # Validation
        errors = []
        if not first_name.strip() or not last_name.strip():
            errors.append("Merci d'indiquer vos prénom et nom.")
        if not is_valid_email(email):
            errors.append("L'adresse email ne semble pas valide.")
        if not is_valid_phone(phone):
            errors.append("Le numéro de téléphone doit contenir au moins 8 chiffres.")
        if not gdpr_consent:
            errors.append("Vous devez accepter d'être recontacté(e) pour continuer.")

        if errors:
            for err in errors:
                st.error(err)
            return

        # ── Envoi de la notification (best effort) ──
        with st.spinner("Préparation de votre rapport personnalisé…"):
            pdf_bytes = generate_flash_pdf(result)
            success, message = send_lead_notification(
                result=result,
                lead_email=email.strip(),
                lead_first_name=first_name.strip(),
                lead_last_name=last_name.strip(),
                lead_phone=phone.strip(),
                pdf_bytes=pdf_bytes,
            )

        if not success:
            # On ne bloque pas l'utilisateur même si l'envoi mail échoue.
            # Le warning n'est visible que dans les logs serveur.
            import logging
            logging.warning(
                "Notification lead non envoyée pour %s %s : %s",
                first_name, last_name, message,
            )

        # Stocker en session pour passer à la vue résultats
        # NB : on n'écrit PAS sur 'lead_first_name' etc. car ce sont déjà des
        # clés de widget - Streamlit refuse les double-affectations.
        st.session_state["lead_captured"] = True
        st.session_state["lead_pdf_bytes"] = pdf_bytes
        st.rerun()


# ============================================================
# Vue 3 - Résultats
# ============================================================

def render_radar_plotly(result) -> None:
    codes = list(result.axis_scores.keys())
    labels = [f"{c} - {result.axis_names[c][:25]}" for c in codes]
    values = [result.axis_scores[c] for c in codes]

    labels_closed = labels + [labels[0]]
    values_closed = values + [values[0]]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values_closed,
        theta=labels_closed,
        fill="toself",
        line=dict(color="#1F365A", width=2),
        fillcolor="rgba(31, 54, 90, 0.18)",
        name="Votre score",
    ))
    fig.add_trace(go.Scatterpolar(
        r=[5] * len(labels_closed),
        theta=labels_closed,
        mode="lines",
        line=dict(color="rgba(0,0,0,0.2)", width=1, dash="dot"),
        showlegend=False,
    ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True, range=[0, 5],
                tickvals=[1, 2, 3, 4, 5],
                tickfont=dict(size=9),
            ),
            angularaxis=dict(tickfont=dict(size=10)),
        ),
        showlegend=False, height=480,
        margin=dict(l=80, r=80, t=20, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_results(config: dict) -> None:
    _scroll_to_top()
    result = st.session_state["result"]

    st.title("🎯 Vos résultats")
    st.caption(
        f"Organisation : **{result.organization}**  ·  "
        f"Répondant : **{result.role}**"
    )
    st.divider()

    # ── Header : Score + Niveau ──
    c1, c2 = st.columns([1, 2])
    with c1:
        st.metric("Score global", f"{result.global_score:.2f} / 5")
    with c2:
        st.markdown(
            f"""
            <div style="padding: 0.5rem 0;">
                <div style="font-size: 0.875rem; color: #6b6b6b;">Niveau de maturité</div>
                <div style="font-size: 1.5rem; font-weight: 600;">
                    <span style="color: {result.level_color};">●</span>
                    {result.level} - {result.level_name}
                </div>
                <div style="font-size: 0.9rem; font-style: italic; color: #1a1a1a;">
                    « {result.level_description} »
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ── Encadré pédagogie 'Comment lire vos résultats' ──
    with st.expander("ℹ️ Comment lire vos résultats", expanded=False):
        st.markdown(
            """
**Niveau de maturité (échelle 1 à 5)** :

- **1 - Initial** : l'IA reste une intention diffuse, sans cadre ni pilotage
- **2 - Aware** : conscience, premiers pilotes, gouvernance émergente
- **3 - Defined** : pratiques formalisées, premiers cas en production, périmètres définis
- **4 - Managed** : pilotage par KPI, scaling actif, gouvernance opérationnelle
- **5 - Optimized** : IA intégrée à la stratégie et aux opérations, mesure d'impact systématique

**Forces** : axes où vous avez score 4 ou 5 sur 5. Ce sont vos atouts sur lesquels capitaliser.

**Zones de progrès prioritaires** : axes où vous avez score 1 ou 2. Ce sont les leviers à activer en priorité. Une sévérité haute indique un poids fort dans le framework combiné avec un score bas.

**Repère de marché** : selon nos observations, la maturité IA moyenne des ETI françaises se situe entre niveau 2 et 3. Atteindre le niveau 4 demande généralement 18 à 36 mois de transformation structurée.
            """
        )

    st.divider()

    # ── Radar ──
    st.markdown("### 📊 Votre radar 8 axes")
    render_radar_plotly(result)

    # ── Dissonance déclaratif vs réel ──
    if result.has_dissonance:
        st.warning(
            f"**Dissonance détectée** : votre maturité déclarée ressort à "
            f"**{result.global_score:.2f}/5**, mais le nombre de cas d'usage IA "
            f"réellement en production correspond à un niveau "
            f"**{result.q9_real_score}/5** "
            f"(écart : {result.dissonance_declaratif_vs_reel:.1f} point). "
            f"Signal classique d'organisation en phase d'ambition, à transformer "
            f"en exécution."
        )

    # ── Forces / Zones de progrès ──
    st.caption(
        "Vos forces sont les axes scorant 4 ou 5 sur 5. Vos zones de progrès sont "
        "les axes scorant 1 ou 2. Si aucun axe n'atteint ces seuils, le radar "
        "vous donne quand même une lecture relative de vos points d'appui et "
        "de vos chantiers."
    )
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### ✅ Vos forces")
        if result.strengths:
            for code, name, score in result.strengths:
                st.success(f"**{code}** - {name} ({score}/5)")
        else:
            st.info(
                "Aucun axe ne ressort en force marquée - terrain d'opportunité large."
            )
    with c2:
        st.markdown("### 🎯 Zones de progrès prioritaires")
        for code, name, score in result.gaps:
            st.error(f"**{code}** - {name} ({score}/5)")

    st.divider()

    # ── PDF download + CTA ──
    st.markdown("### 📄 Téléchargez votre synthèse")
    st.caption(
        "1 page A4, prête à partager en interne. Inclut votre score, "
        "votre radar, vos forces, vos zones de progrès, et vos apports qualitatifs."
    )

    # On réutilise le PDF généré au gate email (évite double génération)
    pdf_bytes = st.session_state.get("lead_pdf_bytes") or generate_flash_pdf(result)
    safe_org = "".join(c if c.isalnum() or c in "_-" else "_" for c in result.organization)
    filename = f"AuditFlash_{safe_org}_{date.today().isoformat()}.pdf"

    c1, c2 = st.columns([1, 2])
    with c1:
        st.download_button(
            label="⬇️ Télécharger le PDF",
            data=pdf_bytes,
            file_name=filename,
            mime="application/pdf",
            type="primary",
            use_container_width=True,
        )
    with c2:
        st.caption(f"Taille du fichier : {len(pdf_bytes) // 1024} Ko")

    st.divider()

    # ── CTA commercial ──
    cta = config["cta"]
    st.markdown("### 💬 Pour aller plus loin")

    # On construit le mailto en encodant proprement subject et body via
    # urllib.parse.quote, puis on l'injecte en HTML pour eviter que le
    # parseur markdown de Streamlit s'embrouille sur les caracteres speciaux
    # de l'URL (parentheses, accents, %, etc.).
    mail_subject = f"Suite Audit Flash Maturite IA - {result.organization}"
    mail_body = (
        f"Bonjour,\n\n"
        f"J'ai realise l'audit flash IstadAi pour {result.organization} "
        f"(score {result.global_score:.2f}/5, niveau {result.level}).\n"
        f"Je souhaiterais echanger a propos des suites possibles.\n\n"
        f"Cordialement"
    )
    mailto_url = (
        f"mailto:{cta['contact_email']}"
        f"?subject={quote(mail_subject)}"
        f"&body={quote(mail_body)}"
    )

    st.markdown(
        f"""
Cet audit flash est indicatif. Pour un **audit complet** avec entretiens
multi-sponsors, **analyses augmentées par l'IA de votre organisation**
(architecture BYOLLM), cross-check budget IT et plan de transformation
actionnable :

<p style="margin: 1rem 0 0.3rem 0;">
    📧 <a href="{mailto_url}" style="font-weight: 600; color: #1F365A; text-decoration: none;">{cta['contact_email']}</a>
</p>
<p style="margin: 0 0 1rem 0;">
    📞 <a href="tel:+33689394880" style="font-weight: 600; color: #1F365A; text-decoration: none;">+33 6 89 39 48 80</a>
</p>

Pierre-Alain Laval, IstadAi
        """,
        unsafe_allow_html=True,
    )

    st.divider()
    if st.button("🔄 Recommencer un audit", key="btn_restart"):
        reset_session()
        st.rerun()


# ============================================================
# Main router
# ============================================================

def main():
    config = get_questions_config()

    if st.session_state.get("lead_captured"):
        render_results(config)
    elif "result" in st.session_state:
        render_email_gate(config)
    elif st.session_state.get("started"):
        render_questionnaire(config)
    else:
        render_intro(config)


if __name__ == "__main__":
    main()
