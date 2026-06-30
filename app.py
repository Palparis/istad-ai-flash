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

from cost_guard import get_stats as get_cost_stats
from cost_guard import increment_counter, is_llm_available
from lead_notifier import is_valid_email, is_valid_phone, send_lead_notification
from pdf_flash import generate_flash_pdf
from scoring_flash import compute_flash_result, load_questions
from verbatim_analyzer import analyze_verbatims

# Charger .env du monorepo (pour SMTP credentials en dev local)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ============================================================
# Config Streamlit
# ============================================================

st.set_page_config(
    page_title="IstadAi - Audit Flash Maturité IA",
    page_icon=str(Path(__file__).parent / "assets" / "cube-couleur.png"),
    layout="centered",  # centré pour effet "tunnel"
    initial_sidebar_state="collapsed",
)

# ============================================================
# Style CSS minimal pour adoucir l'UI
# ============================================================

st.markdown("""
    <style>
        /* Compactage agressif pour tenir tout dans le viewport, sans scroll.
           Selecteurs Streamlit modernes (data-testid) + spécificité haute. */
        [data-testid="stAppViewContainer"] [data-testid="stMain"] {
            padding-top: 0 !important;
        }
        [data-testid="stMain"] .block-container,
        [data-testid="stMainBlockContainer"],
        .main .block-container {
            padding-top: 0.5rem !important;
            padding-bottom: 0.5rem !important;
            max-width: 860px;
        }
        /* Cacher le header Streamlit (toolbar haut) pour gagner ~50px */
        [data-testid="stHeader"] { display: none !important; }
        [data-testid="stToolbar"] { display: none !important; }
        /* Palette IstadAi (charte Istada) */
        h1, [data-testid="stMain"] h1 {
            color: #2E3A66 !important; font-weight: 700 !important;
            font-size: 1.6rem !important;
            margin: 0.4rem 0 0.1rem 0 !important;
            padding: 0 !important; line-height: 1.2 !important;
        }
        h2, [data-testid="stMain"] h2,
        h3, [data-testid="stMain"] h3 {
            color: #2E3A66 !important;
            margin: 0.4rem 0 0.2rem 0 !important;
            padding: 0 !important;
        }
        [data-testid="stMain"] p { margin-bottom: 0.25rem !important; }
        [data-testid="stMain"] ul,
        [data-testid="stMain"] ol {
            margin: 0.15rem 0 0.3rem 0 !important;
            padding-left: 1.2rem !important;
        }
        [data-testid="stMain"] li {
            margin-bottom: 0.05rem !important;
            line-height: 1.35 !important;
        }
        .stRadio label { font-size: 0.95rem; }
        .istad-tagline {
            color: #6270B4 !important; font-size: 0.9rem; font-weight: 500;
            margin: -0.2rem 0 0.4rem 0 !important;
        }
        /* Banniere */
        [data-testid="stImage"] { margin: 0 !important; }
        .stImage img { border-radius: 6px; }
        /* Info_box (st.info) compacte */
        [data-testid="stAlert"],
        [data-testid="stAlertContainer"] {
            padding: 0.5rem 0.8rem !important;
            margin: 0.3rem 0 !important;
        }
        [data-testid="stAlert"] p { margin: 0 !important; font-size: 0.9rem; }
        /* Expander compact */
        [data-testid="stExpander"] {
            margin: 0.2rem 0 !important;
        }
        [data-testid="stExpander"] details summary {
            padding: 0.4rem 0.8rem !important;
        }
        /* Form compact */
        [data-testid="stForm"] { padding: 0.5rem !important; }
        [data-testid="stTextInput"] label,
        [data-testid="stSelectbox"] label { font-size: 0.85rem !important; }
        /* Cubes lateraux : logos Istada officiels (extraits .ai par PAL).
           Centres horizontalement entre le bord de l'ecran et le bloc
           central (max-width 860px du block-container).
           Formule : (viewport - contenu)/2 = marge laterale ;
                     /2 = centre de marge ; - largeur_cube/2 = position. */
        .istad-cube-left, .istad-cube-right {
            position: fixed; top: 50%;
            width: 96px; height: auto;
            transform: translateY(-50%); z-index: 1000;
            pointer-events: none;
        }
        .istad-cube-left {
            left: calc((100vw - 860px) / 4 - 48px);
        }
        .istad-cube-right {
            right: calc((100vw - 860px) / 4 - 48px);
        }
        @media (max-width: 1100px) {
            .istad-cube-left, .istad-cube-right { display: none; }
        }
    </style>
""", unsafe_allow_html=True)


# ============================================================
# Cubes lateraux (logos Istada officiels) - injectes globalement
# ============================================================
# Chargés une fois en base64 et réinjectés sur chaque rerun. Comme
# ils sont position:fixed, ils s'affichent identiquement sur toutes
# les vues (intro, questionnaire, gate email, résultats).

def _inject_istad_cubes() -> None:
    import base64
    assets = Path(__file__).parent / "assets"
    html = ""
    for cls, fname in (("istad-cube-left", "cube-couleur.png"),
                       ("istad-cube-right", "cube-bw.png")):
        img_path = assets / fname
        if img_path.exists():
            with open(img_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            html += (
                f'<img class="{cls}" '
                f'src="data:image/png;base64,{b64}" alt="">'
            )
    if html:
        st.markdown(html, unsafe_allow_html=True)


_inject_istad_cubes()


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
    à une vue longue (questionnaire). Ce hack tente plusieurs sélecteurs
    (selon la version de Streamlit Cloud les DOM diffèrent) et plusieurs
    timings (Streamlit re-render après le mount initial).
    """
    import streamlit.components.v1 as components
    components.html(
        """
        <script>
            function istadScrollTop() {
                try {
                    const doc = window.parent.document;
                    const targets = [
                        doc.querySelector('section.main'),
                        doc.querySelector('div.main'),
                        doc.querySelector('.stApp'),
                        doc.querySelector('[data-testid="stAppViewContainer"]'),
                        doc.querySelector('[data-testid="stMain"]'),
                        doc.documentElement,
                        doc.body,
                    ];
                    for (const t of targets) {
                        if (t && t.scrollTo) {
                            t.scrollTo({top: 0, behavior: 'instant'});
                        }
                    }
                    if (window.parent && window.parent.scrollTo) {
                        window.parent.scrollTo({top: 0, behavior: 'instant'});
                    }
                } catch (e) { /* iframes cross-origin, on ignore */ }
            }
            istadScrollTop();
            setTimeout(istadScrollTop, 100);
            setTimeout(istadScrollTop, 300);
            setTimeout(istadScrollTop, 700);
        </script>
        """,
        height=0,
    )


# ============================================================
# Vue 1 - Consentement + identification organisation
# ============================================================

def render_intro(config: dict) -> None:
    assets = Path(__file__).parent / "assets"

    # Banniere photo montagne au format hero (970x180, ratio ~5.4:1).
    # Les cubes lateraux sont injectes globalement au demarrage du script
    # (cf. _inject_istad_cubes) pour qu'ils apparaissent sur toutes les vues.
    for candidate in ("photo-montagne-hero.jpg", "photo-montagne-banner.jpg",
                      "Photo montagne.jpg"):
        photo = assets / candidate
        if photo.exists():
            st.image(str(photo), width="stretch")
            break

    st.title("Audit Flash Maturité IA")
    st.markdown(
        '<div class="istad-tagline">Pré-diagnostic IA en 10 questions, '
        "5 à 10 minutes. Par IstadAi.</div>",
        unsafe_allow_html=True,
    )

    st.markdown("**Ce que vous allez recevoir**")
    st.markdown(
        "- Votre **score global** sur 5 et votre **niveau de maturité** "
        "(Initial à Optimized)\n"
        "- Un **radar 8 axes** couvrant stratégie, exécution et gouvernance\n"
        "- Vos **forces** et vos **zones de progrès**, axe par axe\n"
        "- Un **PDF de synthèse**"
    )

    short_text = config.get("consent_short", "")
    full_text = config.get("consent_text", "")
    if short_text:
        st.info(short_text)
    if full_text:
        with st.expander("Tout savoir avant de commencer (RGPD, analyse Claude, BYOLLM)"):
            st.markdown(full_text)

    with st.form("intro_form"):
        c1, c2 = st.columns([2, 1])
        with c1:
            org = st.text_input(
                "Nom de votre organisation",
                placeholder="ex. ACME, MaSociété, etc.",
            )
        with c2:
            role = st.selectbox(
                "Votre rôle",
                options=config["roles"],
                index=0,
            )

        c3, c4 = st.columns(2)
        with c3:
            effectif = st.selectbox(
                "Effectif de votre organisation",
                options=config.get("effectifs", []),
                index=0,
            )
        with c4:
            secteur = st.selectbox(
                "Secteur d'activité",
                options=config.get("secteurs", []),
                index=0,
            )
        secteur_precision = st.text_input(
            "Si 'Autre' ci-dessus, précisez votre secteur",
            placeholder="(rempli uniquement si vous avez choisi 'Autre')",
        )

        consent = st.checkbox(
            "J'ai pris connaissance des modalités ci-dessus et j'accepte de "
            "démarrer l'audit. Je comprends que mes coordonnées "
            "professionnelles me seront demandées en fin de questionnaire "
            "pour accéder à ma synthèse.",
            value=False,
        )
        submitted = st.form_submit_button(
            "Commencer l'audit flash Maturité IA",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        if not org.strip():
            st.error("Merci d'indiquer un nom d'organisation.")
            return
        if not consent:
            st.error("Vous devez cocher la case de consentement pour continuer.")
            return
        if secteur == "Autre" and not secteur_precision.strip():
            st.error("Vous avez sélectionné 'Autre' comme secteur, merci de préciser dans le champ ci-dessus.")
            return
        st.session_state["organization"] = org.strip()
        st.session_state["role"] = role
        st.session_state["effectif"] = effectif
        st.session_state["secteur"] = secteur
        st.session_state["secteur_precision"] = secteur_precision.strip()
        st.session_state["started"] = True
        st.rerun()


# ============================================================
# Vue 2 - Le questionnaire (toutes les questions sur une page)
# ============================================================

def render_questionnaire(config: dict) -> None:
    _scroll_to_top()
    st.title("Audit Flash Maturité IA")
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

            # Ordre logique : etat actuel (text libre) -> etat souhaite
            # (multiselect domaines) -> processus (ancres).

            # Champ texte libre (si défini) - l'etat actuel decrit avec ses mots
            if q.get("text_prompt"):
                txt = st.text_area(
                    q["text_prompt"],
                    key=f"{qid}_text",
                    placeholder="Optionnel - apparaîtra dans votre rapport et nourrira notre échange si vous souhaitez approfondir.",
                    max_chars=200,
                    height=80,
                )
                answers[f"{qid}_text"] = txt or ""

            # Multiselect (si défini) - typiquement Q2 domaines souhaites,
            # Q3 stack IA effectivement deploye
            if q.get("multiselect"):
                ms_cfg = q["multiselect"]
                ms_choices = st.multiselect(
                    ms_cfg.get("label", "Cochez tout ce qui s'applique"),
                    options=ms_cfg.get("options", []),
                    key=f"{qid}_multiselect",
                )
                answers[f"{qid}_multiselect"] = ms_choices

            # Auto-évaluation 5 ancres (sans afficher le score 1-5)
            #
            # Insight Celia Felipe (25 juin 2026) : afficher le chiffre 1-5 a
            # cote des ancres induit un biais de desirabilite sociale (le
            # repondant choisit l'option "un peu meilleure" pour ne pas se
            # devaluer). On cache donc le chiffre dans l'affichage tout en
            # gardant le mapping description -> score en backend.
            #
            # Q9 transverse (irritants) n'a PAS d'ancres - on saute le radio.
            anchors_cfg = q.get("anchors")
            if anchors_cfg and q.get("eval_prompt"):
                sorted_levels = sorted(anchors_cfg.keys())
                anchor_labels = [anchors_cfg[level] for level in sorted_levels]
                anchor_to_score = {anchors_cfg[level]: level for level in sorted_levels}

                choice = st.radio(
                    q["eval_prompt"],
                    options=anchor_labels,
                    index=None,
                    key=f"{qid}_radio",
                )
                if choice is not None:
                    answers[qid] = anchor_to_score[choice]

            st.markdown("---")

        submitted = st.form_submit_button(
            "Voir mes résultats →", type="primary", use_container_width=True,
        )

    if submitted:
        # Vérifier que toutes les questions scorées sont répondues.
        # Les questions sans ancres (Q9 transverse irritants) n'ont pas
        # besoin d'etre evaluees sur une echelle.
        missing = [
            q["id"] for q in questions
            if q.get("anchors") and q["id"] not in answers
        ]
        if missing:
            st.error(
                f"Merci de répondre à toutes les questions ({len(missing)} "
                f"question{'s' if len(missing) > 1 else ''} restante"
                f"{'s' if len(missing) > 1 else ''})."
            )
            return

        # Vérifier les multiselects obligatoires
        missing_ms = []
        for q in questions:
            ms_cfg = q.get("multiselect")
            if not ms_cfg or not ms_cfg.get("required"):
                continue
            chosen = answers.get(f"{q['id']}_multiselect") or []
            if not chosen:
                missing_ms.append(q["axis_code"])
        if missing_ms:
            st.error(
                "Merci de cocher au moins une option dans la liste des outils IA "
                f"pour la question : {', '.join(missing_ms)}."
            )
            return

        # Tout est OK : calculer + ranger en session
        answers["role"] = st.session_state["role"]
        answers["organization"] = st.session_state["organization"]
        answers["effectif"] = st.session_state.get("effectif", "")
        answers["secteur"] = st.session_state.get("secteur", "")
        answers["secteur_precision"] = st.session_state.get("secteur_precision", "")
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

    st.title("Votre audit flash est terminé")
    st.markdown(
        '<div class="istad-tagline">Une dernière étape avant de découvrir vos résultats.</div>',
        unsafe_allow_html=True,
    )

    st.success(
        f"Questionnaire complété pour **{result.organization}**. "
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

        # Consentement spécifique pour l'analyse LLM des verbatims (optionnel)
        # Activé par défaut pour maximiser la valeur perçue, mais le répondant
        # peut décocher s'il préfère un audit purement déterministe.
        llm_available, llm_reason = is_llm_available()
        llm_consent = st.checkbox(
            "J'accepte que mes verbatims et mes scores soient analysés par "
            "**Claude (Anthropic)** pour enrichir mon rapport d'un commentaire "
            "personnalisé et de la détection de 3 types de dissonances "
            "(entre verbatims, verbatim vs ancre, et entre scores d'axes). "
            "Données traitées par Anthropic en tant que sous-traitant, "
            "**non utilisées pour entraîner les modèles** ni revendues à des "
            "tiers (politique contractuelle Anthropic standard), supprimées "
            "sous 30 jours.",
            value=llm_available,
            disabled=not llm_available,
            help=(
                "Décochez si vous préférez un audit 100% déterministe sans appel "
                "à Claude. Votre rapport contiendra alors uniquement le scoring "
                "des ancres + le radar 8 axes."
                + (
                    f" Quota LLM atteint ({llm_reason}), case désactivée."
                    if not llm_available
                    else ""
                )
            ),
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

        # ── Analyse LLM optionnelle des verbatims (si consentement + budget OK) ──
        verbatim_analysis = None
        if llm_consent and llm_available:
            with st.spinner("Analyse qualitative de vos verbatims par Claude (Anthropic)…"):
                verbatim_analysis = analyze_verbatims(result)
                if verbatim_analysis is not None:
                    increment_counter()

        # ── Préparation du PDF et envoi de la notification (best effort) ──
        with st.spinner("Préparation de votre rapport personnalisé…"):
            pdf_bytes = generate_flash_pdf(result, verbatim_analysis=verbatim_analysis)
            success, message = send_lead_notification(
                result=result,
                lead_email=email.strip(),
                lead_first_name=first_name.strip(),
                lead_last_name=last_name.strip(),
                lead_phone=phone.strip(),
                pdf_bytes=pdf_bytes,
                verbatim_analysis=verbatim_analysis,
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
        st.session_state["verbatim_analysis"] = verbatim_analysis
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

    st.title("Vos résultats")
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
    with st.expander("Comment lire vos résultats", expanded=False):
        st.markdown(
            """
**Niveau de maturité (échelle 1 à 5)** :

- **1 - Initial** : l'IA reste une intention diffuse, sans cadre ni pilotage
- **2 - Aware** : conscience, premiers pilotes, gouvernance émergente
- **3 - Defined** : pratiques formalisées, premiers cas en production, périmètres définis
- **4 - Managed** : pilotage par KPI, scaling actif, gouvernance opérationnelle
- **5 - Optimized** : IA intégrée à la stratégie et aux opérations, mesure d'impact systématique

**Forces** : axes où vous avez score 4 ou 5 sur 5. Ce sont vos atouts sur lesquels capitaliser.

**Opportunités prioritaires** : axes où vous avez score 1 ou 2. Ce sont les leviers à activer en priorité. Une sévérité haute indique un poids fort dans le framework combiné avec un score bas.

**Repère de marché** : selon nos observations, la maturité IA moyenne des ETI françaises se situe entre niveau 2 et 3. Atteindre le niveau 4 demande généralement 18 à 36 mois de transformation structurée.
            """
        )

    st.divider()

    # ── Radar ──
    st.markdown("### Votre radar 8 axes")
    render_radar_plotly(result)

    # ── Lecture personnalisée Claude (si présente) ──
    analysis = st.session_state.get("verbatim_analysis")
    if analysis is not None and analysis.commentaire_personnalise:
        st.markdown("### Lecture personnalisée par Claude")
        st.caption(
            "Analyse qualitative produite par Claude (Anthropic) à partir de "
            f"vos réponses. Coût estimé : {analysis.cost_estimate_eur:.4f} EUR. "
            "Anthropic ne réutilise pas les inputs/outputs pour entraîner ses "
            "modèles (politique contractuelle standard)."
        )
        st.info(analysis.commentaire_personnalise)

        # Cas d'usage IA recommandés (basés sur Q2 multiselect domaines + Q3 stack IA)
        if analysis.cas_usage_recommandes:
            st.markdown("### Cas d'usage IA recommandés pour votre situation")
            st.caption(
                "Suggestions concrètes calibrées sur les domaines que vous avez "
                "indiqués et votre stack IA déclaré."
            )
            for cu in analysis.cas_usage_recommandes:
                st.success(cu)

        # Trois types de dissonances rendus séparément (chacun en expander)
        total_diss = (
            len(analysis.dissonances_verbatims)
            + len(analysis.dissonances_verbatim_vs_ancre)
            + len(analysis.dissonances_ancres)
        )
        if total_diss > 0:
            with st.expander(
                f"{total_diss} dissonance(s) détectée(s), 3 types analysés",
                expanded=False,
            ):
                if analysis.dissonances_verbatims:
                    st.markdown("**Entre vos verbatims libres :**")
                    for d in analysis.dissonances_verbatims:
                        st.warning(d)
                if analysis.dissonances_verbatim_vs_ancre:
                    st.markdown("**Entre vos verbatims et les options choisies :**")
                    for d in analysis.dissonances_verbatim_vs_ancre:
                        st.warning(d)
                if analysis.dissonances_ancres:
                    st.markdown("**Entre vos scores d'axes (strategy vs execution) :**")
                    for d in analysis.dissonances_ancres:
                        st.warning(d)
        st.divider()

    # ── Forces / Opportunités prioritaires ──
    st.caption(
        "Vos forces sont les axes scorant 4 ou 5 sur 5. Vos zones de progrès sont "
        "les axes scorant 1 ou 2. Si aucun axe n'atteint ces seuils, le radar "
        "vous donne quand même une lecture relative de vos points d'appui et "
        "de vos chantiers."
    )
    verbatim_analysis = st.session_state.get("verbatim_analysis")
    forces_insights = verbatim_analysis.forces_insights if verbatim_analysis else {}
    zones_insights = verbatim_analysis.zones_insights if verbatim_analysis else {}

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### Vos forces")
        if result.strengths:
            for code, name, score in result.strengths:
                insight = forces_insights.get(code)
                if insight:
                    st.success(
                        f"**{code}** - {name} ({score}/5)\n\n{insight}"
                    )
                else:
                    st.success(f"**{code}** - {name} ({score}/5)")
        else:
            st.info(
                "Aucun axe ne ressort en force marquée - terrain d'opportunité large."
            )
    with c2:
        st.markdown("### Opportunités prioritaires")
        for code, name, score in result.gaps:
            insight = zones_insights.get(code)
            if insight:
                st.error(
                    f"**{code}** - {name} ({score}/5)\n\n{insight}"
                )
            else:
                st.error(f"**{code}** - {name} ({score}/5)")

    st.divider()

    # ── PDF download + CTA ──
    st.markdown("### Téléchargez votre synthèse")
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
            label="Télécharger le PDF",
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
    st.markdown("### Pour aller plus loin")

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
