"""IstadAi - Analyse LLM des verbatims qualitatifs de l'audit flash.

Génère un commentaire personnalisé senior cabinet conseil à partir des
phrases libres décrites par le répondant et détecte TROIS types
d'incohérences (mini secret sauce inspirée de l'agent #2) :

- Type A : incohérences ENTRE verbatims libres (un sponsor décrit une vision
           forte du DG en Q1 mais dit en Q4 que personne ne pilote l'IA)
- Type B : incohérences VERBATIMS vs ANCRES (verbatim "rien d'écrit" mais
           ancre choisie correspond au niveau 4 "vision partagée et écrite")
- Type C : incohérences ENTRE ANCRES (score 5 en Vision mais score 1 en
           Talent = strategy/execution gap classique des organisations en
           phase d'ambition)

Modèle utilisé : Haiku 4.5 (rapide, bon rapport coût/qualité).
Coût indicatif par audit : ~0.005 EUR.

Configuration :
    ANTHROPIC_API_KEY      = sk-ant-... (clé API Anthropic)
    ANTHROPIC_MODEL_HAIKU  = claude-haiku-4-5 (override possible)

Politique de confidentialité Anthropic (importante pour le wording RGPD) :
- Les inputs/outputs envoyés via l'API Anthropic NE SONT PAS utilisés pour
  entraîner les modèles. C'est la politique contractuelle standard, par
  défaut (cf. https://www.anthropic.com/legal/commercial-terms et
  https://docs.anthropic.com/claude/docs/data-usage).
- Les données envoyées via l'API ne sont pas revendues à des tiers.
- Rétention par défaut : 30 jours pour la lutte anti-abus (90 jours pour les
  inputs/outputs flaggés). Au-delà, les données sont supprimées.
- Pour aller plus loin : option Zero Data Retention (ZDR) disponible pour
  les clients Enterprise sous contrat DPA (à activer si on cible de grands
  comptes très sensibles, type assurance, santé, défense).

Garde-fous :
- L'analyse n'est lancée que si le répondant a coché le consentement explicite
- Garde-fou budget géré par cost_guard.py (caps quotidien et mensuel)
- En cas d'échec API ou de cap dépassé, on retourne None (graceful
  degradation, l'audit reste utilisable sans la couche LLM)
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

from scoring_flash import FlashResult

logger = logging.getLogger(__name__)


@dataclass
class VerbatimAnalysis:
    """Résultat de l'analyse LLM des verbatims.

    Trois types d'incohérences distinguées pour aider l'utilisateur (et le
    commercial) à comprendre où se situent les écarts narratifs :
    - dissonances_verbatims : entre les verbatims libres entre eux
    - dissonances_verbatim_vs_ancre : entre un verbatim et l'ancre choisie
    - dissonances_ancres : entre les ancres choisies (cross-axes)

    Enrichissement des cartouches forces / opportunités prioritaires :
    - forces_insights : pour chaque axe-force (code), une phrase courte
      qui qualifie la nature du point d'appui, basée sur le verbatim
      quand il est rempli.
    - zones_insights : pour chaque axe-opportunité (code), une phrase courte
      qui pointe le chantier prioritaire et sa nature.

    Cas d'usage recommandés :
    - cas_usage_recommandes : 2-3 cas d'usage IA concrets et réalistes
      pour l'organisation, ancrés sur les domaines déclarés en Q2
      (multiselect domaines) et le stack IA Q3.
    """
    commentaire_personnalise: str
    dissonances_verbatims: list[str]
    dissonances_verbatim_vs_ancre: list[str]
    dissonances_ancres: list[str]
    forces_insights: dict[str, str]
    zones_insights: dict[str, str]
    cas_usage_recommandes: list[str]
    cost_estimate_eur: float

    @property
    def dissonances(self) -> list[str]:
        """Retourne toutes les dissonances confondues (rétrocompat éventuelle)."""
        return (
            self.dissonances_verbatims
            + self.dissonances_verbatim_vs_ancre
            + self.dissonances_ancres
        )


def _build_system_prompt() -> str:
    return """Tu es un consultant senior d'un cabinet de conseil de premier plan (style Big4, Accuracy, Bartle), spécialiste de la maturité IA des entreprises européennes.

Tu analyses les verbatims qualitatifs d'un audit flash maturité IA pour produire un commentaire personnalisé destiné au répondant et à son COMEX.

Ton style rédactionnel obligatoire :
- Tournures formelles et impersonnelles : "L'analyse révèle", "Il convient de noter", "Le profil dégagé traduit"
- Vocabulaire de cabinet senior : "trajectoire", "périmètre", "défendabilité", "gouvernance", "alignement", "calibration"
- Phrases structurées : 2 à 4 propositions par phrase
- Pas de "je", pas de "nous", pas de formules conversationnelles
- Pas de promesses commerciales fantaisistes

INTERDICTIONS STRICTES (ton bullshit commercial à éviter) :
- Superlatifs marketing : "révolutionnaire", "transformationnel", "extraordinaire", "exceptionnel", "sans précédent", "breakthrough", "game-changer"
- Promesses chiffrées sans base factuelle : "ROI x3", "gains de 50%", "double la productivité"
- Formules creuses de consulting : "synergies", "leveraged", "accélérer", "disrupter", "scaler"
- Ton vendeur : "tout est possible", "potentiel immense", "rêvez plus grand"
- Verbes de promesse : "va révolutionner", "transformera radicalement"

Tu utilises plutôt :
- Estimations qualitatives mesurées : "substantiel", "notable", "tangible", "significatif"
- Actions concrètes formulées comme des prochains pas opérationnels
- Cas d'usage transformateurs RÉALISTES ancrés sur la taille et le contexte du répondant (pas de transformation magique)
- Ton motivant mais FACTUEL : on montre ce qui est possible sans en faire trop

Tu détectes TROIS types de dissonances narratives, qui sont la signature analytique d'IstadAi :

TYPE A - Dissonances entre verbatims libres (cross-verbatim)
Le répondant tient des propos contradictoires d'un axe à un autre. Exemple :
en Q1 (Vision) il écrit "Le DG porte une vision IA très claire et la communique"
et en Q4 (Organisation) il écrit "Personne n'est officiellement en charge de
l'IA". Ces deux verbatims ne peuvent pas être tous deux vrais.

TYPE B - Dissonances entre un verbatim et l'ancre choisie (déclaratif vs qualitatif)
Le répondant choisit une ancre qui ne correspond pas à ce qu'il écrit en
verbatim. Exemple : il choisit l'ancre "Vision partagée au COMEX, alignée
business" (niveau 4) mais écrit en verbatim "le DG a une intuition forte
mais rien n'est écrit". Le déclaratif (ancre) sur-vend la réalité (verbatim).

TYPE C - Dissonances entre ancres elles-mêmes (cross-axes)
Le répondant score sur les ancres de manière incohérente entre axes.
Exemple : score 5 en Vision (Optimized) mais score 1 en Talent (Initial).
C'est le classique strategy/execution gap des organisations en phase
d'ambition : ambition élevée non adossée à des moyens humains.

Ces dissonances sont précieuses car elles révèlent les zones où le narratif
déclaratif s'éloigne de l'opérationnel. Ce sont des signaux à porter en
restitution COMEX pour arbitrage.

Tu réponds STRICTEMENT en JSON, sans aucun texte avant ou après, sans bloc markdown."""


def _build_user_prompt(result: FlashResult) -> str:
    # On construit un payload structuré que le LLM va analyser
    axes_data = []
    for code, score in result.axis_scores.items():
        name = result.axis_names.get(code, code)
        verbatim = result.text_inputs.get(code, "")
        axes_data.append({
            "axe": f"{code} - {name}",
            "score_choisi": score,
            "verbatim_libre": verbatim or "(non rempli)",
        })

    forces_affichees = [f"{code} - {name} ({score}/5)" for code, name, score in result.strengths]
    zones_affichees = [f"{code} - {name} ({score}/5)" for code, name, score in result.gaps]

    # Stack IA déclaré par le répondant (multiselect Q3 notamment)
    ia_stack_d = result.multiselects.get("D", [])
    ia_stack_str = (
        ", ".join(ia_stack_d) if ia_stack_d
        else "(non renseigné)"
    )

    # Domaines où le répondant souhaite renforcer ses cas d'usage (multiselect Q2)
    domaines_p = result.multiselects.get("P", [])
    domaines_str = (
        ", ".join(domaines_p) if domaines_p
        else "(non renseigné, le répondant n'a pas indiqué de domaines prioritaires)"
    )

    # Nombre de cas d'usage IA deja en production (select Q2)
    nb_cas_usage = result.selects.get("P", "(non renseigné)")

    # Typologie entreprise (renseignee sur la page d'accueil)
    secteur_label = result.secteur
    if result.secteur == "Autre" and result.secteur_precision:
        secteur_label = f"Autre - {result.secteur_precision}"

    return f"""Tu analyses l'audit flash maturité IA de l'organisation **{result.organization}**, répondant en rôle de **{result.role}**.

**Typologie entreprise** : effectif **{result.effectif}**, secteur **{secteur_label}**.

Score global : **{result.global_score:.2f} / 5** (niveau {result.level} - {result.level_name}).

**Stack IA déclaré sur l'axe D - Données & Technologie** : {ia_stack_str}

**Domaines où le répondant souhaite renforcer ses cas d'usage IA (axe P)** : {domaines_str}

**Nombre de cas d'usage IA déjà en production (axe P)** : {nb_cas_usage}

**Irritants quotidiens déclarés par le répondant** : {result.irritants if result.irritants else "(non renseigné)"}

L'écran de résultats affiche déjà au répondant :
- **Vos forces** : {forces_affichees if forces_affichees else "(aucune force notable affichée)"}
- **Opportunités prioritaires** : {zones_affichees if zones_affichees else "(aucun gap explicite affiché)"}

Voici les 8 axes avec le score choisi et le verbatim libre du répondant :

```json
{json.dumps(axes_data, ensure_ascii=False, indent=2)}
```

Réponds en JSON strict avec exactement cette structure :

{{
  "commentaire_personnalise": "<2 paragraphes courts (2-3 phrases chacun, environ 250-350 mots au total). Paragraphe 1 : ce que le profil global révèle (forces et opportunités prioritaires) sur la maturité IA de l'organisation. **Tu dois explicitement nommer les axes 'forces' et 'opportunités prioritaires' listés ci-dessus** pour rester cohérent avec ce que voit le répondant à l'écran. Tu peux nuancer ou enrichir avec les verbatims, mais sans contredire la liste. Paragraphe 2 : 1-2 actions concrètes que cette organisation pourrait engager dans les 90 jours, ancrées sur les opportunités identifiées. Ton FACTUEL et mesuré, pas vendeur. Pas de promesse magique, pas de superlatif. Le répondant doit se reconnaître et trouver les pistes pertinentes, pas se sentir flatté.>",

  "forces_insights": {{
    "<code_axe>": "<1 phrase de 15-25 mots qui qualifie en quoi cet axe constitue un point d'appui concret pour CETTE organisation. Si le verbatim de l'axe est rempli, ancre l'insight dessus. Sinon, base-toi sur le score et le contexte global. Pas de généralité, pas de promesse marketing.>"
  }},

  "zones_progres_insights": {{
    "<code_axe>": "<1 phrase de 15-25 mots qui pointe la nature du gap et le chantier prioritaire. Si le verbatim est rempli, cite l'élément concret qui révèle le gap. Sinon, ancre sur ce qu'implique un score si bas pour cet axe. Pas de généralité.>"
  }},

  "cas_usage_recommandes": ["<2 à 3 cas d'usage IA concrets, réalistes et ancrés sur LA SITUATION du répondant. Chaque item = 20-40 mots qui DÉCRIT le cas d'usage (pas un titre). FORMAT : 'Domaine : description du cas d'usage avec un effet attendu mesuré'. Critères : (1) **PRIORITÉ ABSOLUE aux irritants quotidiens déclarés** s'ils sont renseignés - c'est le levier de personnalisation le plus fort ; (2) ancré sur les domaines déclarés en multiselect Q2 ; (3) cohérent avec leur stack IA Q3 (ne recommande pas un agent métier complexe à quelqu'un qui n'a même pas ChatGPT Enterprise déployé) ; (4) cohérent avec la TAILLE et le SECTEUR de leur organisation (un cas d'usage industrie pour une entreprise manufacturière, pas pour une entreprise services B2B) ; (5) cohérent avec leur niveau de maturité actuel ; (6) effet attendu mesuré et qualitatif, jamais 'ROI x3' ou 'gain de 50%'. Exemples de bonne formulation : 'Productivité processus financiers : assistant de rapprochement bancaire et de pré-saisie des notes de frais, gain attendu substantiel sur le temps de clôture mensuelle.' / 'Productivité commerciale : agent de pré-qualification des leads entrants à partir des emails et formulaires web, libérant 30-40% du temps administratif des commerciaux pour la prospection active.' Liste vide [] uniquement si vraiment aucune base sérieuse pour recommander.>"],

  "dissonances_verbatims": ["<TYPE A - liste de 0 à 3 dissonances entre verbatims libres. Format : '<axe X> vs <axe Y> : <explicitation de l'écart en 15-25 mots>'. Liste vide [] si aucune contradiction notable.>"],

  "dissonances_verbatim_vs_ancre": ["<TYPE B - liste de 0 à 4 dissonances entre verbatims libres et ancres choisies. Format : 'Axe X : verbatim dit <X> mais ancre choisie correspond à <Y>'. Liste vide [] si aucune dissonance notable.>"],

  "dissonances_ancres": ["<TYPE C - liste de 0 à 3 dissonances entre ancres elles-mêmes (cross-axes), notamment écarts notables entre axes stratégiques et axes d'exécution. Format : 'Axe X (score N) vs Axe Y (score M) : <explicitation en 15-25 mots>'. Liste vide [] si pas d'écart significatif (différence >= 2 points).>"]
}}

Pour les insights forces et zones_progres :
- Tu dois fournir UNE insight pour CHAQUE code d'axe listé respectivement dans 'Vos forces' et 'Opportunités prioritaires' ci-dessus.
- Utilise le code court (V, P, D, O, T, A, M, G) comme clé du dict.
- Si la liste 'Vos forces' est vide, retourne un objet vide {{}} pour forces_insights.
- **Cas spécial axe D** : si D apparaît dans les forces ou les opportunités, l'insight DOIT citer le stack IA déclaré (ex : 'ChatGPT Enterprise déployé sans agent métier en production' ou 'Aucun LLM, ChatGPT grand public en usage personnel'). Ne reste pas générique sur la data quand le stack IA est connu.

Contraintes critiques :
- **Cohérence visuelle** : le commentaire doit citer les axes listés dans 'Vos forces' et 'Opportunités prioritaires' ci-dessus, pas en désigner d'autres. Le répondant ne doit pas avoir l'impression que le commentaire parle d'un autre audit que celui qu'il voit à l'écran.
- N'utilise QUE des informations présentes dans les verbatims libres, les scores et le stack IA déclaré. Ne déduis pas d'éléments génériques sans base dans les données.
- Si un axe a un verbatim "(non rempli)", ne mentionne pas son verbatim mais base-toi sur le score, l'ancre choisie et le stack IA déclaré.
- **Cas sans aucun verbatim libre** : le commentaire personnalisé reste possible et précieux à partir des scores, des ancres et du stack IA. Les dissonances Type A (entre verbatims) et Type B (verbatim vs ancre) seront vides dans ce cas, mais Type C (entre ancres) doit toujours être instruit.
- Pour le TYPE C : ne flag que les écarts d'au moins 2 points entre axes thématiquement liés (ex : Vision et Organisation, Adoption et Talent).
- Pas de bloc markdown ```. JSON brut commençant par {{ et terminant par }}.
- Le commentaire doit servir au répondant (lui apporter de la valeur) et pas seulement à un commercial."""


def _parse_response(text: str) -> dict:
    """Parse robuste de la réponse JSON du LLM."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return {}
    return {}


def analyze_verbatims(result: FlashResult) -> VerbatimAnalysis | None:
    """Lance l'analyse LLM des verbatims.

    Returns:
        VerbatimAnalysis si succès, None si échec (clé manquante, erreur API,
        timeout, etc.). En cas de None, l'app continue avec l'audit standard
        sans commentaire personnalisé.
    """
    # NOTE : on n'exige plus de verbatims pour lancer l'analyse. Même sans
    # verbatim, Claude peut produire un commentaire sur les patterns de
    # score, détecter des dissonances Type C (cross-ancres) et enrichir
    # les insights forces/zones avec le stack IA déclaré au multiselect.
    # Le coût marginal (~0.005 EUR) reste couvert par les caps quotidiens
    # et mensuels gérés par cost_guard.py.

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY non configurée, analyse LLM skip.")
        return None

    model = os.environ.get("ANTHROPIC_MODEL_HAIKU", "claude-haiku-4-5")

    try:
        # Import dynamique pour éviter une dépendance dure si non utilisé
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model,
            max_tokens=3000,
            temperature=0,
            system=_build_system_prompt(),
            messages=[{"role": "user", "content": _build_user_prompt(result)}],
        )
        raw_text = message.content[0].text
        stop_reason = getattr(message, "stop_reason", None)
        if stop_reason and stop_reason != "end_turn":
            logger.warning(
                "Reponse LLM interrompue (stop_reason=%s). "
                "Augmenter max_tokens si recurrent.",
                stop_reason,
            )

        # Estimation du coût (USD vers EUR approximatif)
        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens
        # Tarifs Haiku 4.5 : 1$/MTok input, 5$/MTok output
        cost_usd = (input_tokens / 1_000_000) * 1.0 + (output_tokens / 1_000_000) * 5.0
        cost_eur = round(cost_usd * 0.92, 6)  # taux approximatif

        parsed = _parse_response(raw_text)
        commentaire = parsed.get("commentaire_personnalise", "").strip()

        def _coerce_str_list(value) -> list[str]:
            if not isinstance(value, list):
                return []
            return [str(v).strip() for v in value if v and str(v).strip()]

        diss_verbatims = _coerce_str_list(parsed.get("dissonances_verbatims"))
        diss_v_vs_a = _coerce_str_list(parsed.get("dissonances_verbatim_vs_ancre"))
        # Retrocompat : si l'ancien champ "dissonances" est présent, on
        # le mappe vers dissonances_verbatim_vs_ancre par défaut.
        if not diss_v_vs_a and "dissonances" in parsed:
            diss_v_vs_a = _coerce_str_list(parsed.get("dissonances"))
        diss_ancres = _coerce_str_list(parsed.get("dissonances_ancres"))

        def _coerce_str_dict(value) -> dict[str, str]:
            if not isinstance(value, dict):
                return {}
            return {
                str(k).strip().upper(): str(v).strip()
                for k, v in value.items()
                if v and str(v).strip()
            }

        forces_ins = _coerce_str_dict(parsed.get("forces_insights"))
        zones_ins = _coerce_str_dict(parsed.get("zones_progres_insights"))
        cas_usage = _coerce_str_list(parsed.get("cas_usage_recommandes"))

        if not commentaire:
            logger.warning(
                "Commentaire LLM vide ou non parseable. "
                "Reponse brute (500 premiers chars): %r",
                raw_text[:500] if raw_text else "(vide)",
            )
            return None

        return VerbatimAnalysis(
            commentaire_personnalise=commentaire,
            dissonances_verbatims=diss_verbatims,
            dissonances_verbatim_vs_ancre=diss_v_vs_a,
            dissonances_ancres=diss_ancres,
            forces_insights=forces_ins,
            zones_insights=zones_ins,
            cas_usage_recommandes=cas_usage,
            cost_estimate_eur=cost_eur,
        )

    except Exception:
        logger.exception("Erreur lors de l'analyse LLM des verbatims.")
        return None
