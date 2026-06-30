"""IstadAi - Scoring déterministe pour l'audit flash.

100% Python, zéro LLM. Calcule à partir des 9 ancres (8 axes + 1 transverse).

Logique :
- Score axe = ancre choisie (1-5) - simple, lisible, inspiree de CMMI + Gartner
- Score global = moyenne arithmétique des 8 scores d'axe
  (la question transverse Q9 ne rentre PAS dans la moyenne - c'est un check de cohérence)
- Niveau global = round(score_global), clampé entre 1 et 5
- Forces = axes ≥ 4
- Zones de progrès = axes ≤ 2, triés par valeur croissante
- Dissonance Q9 = écart entre la maturité déclarée (moyenne 8 axes) et la maturité réelle (Q9)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class FlashResult:
    """Résultat d'un audit flash."""
    axis_scores: dict[str, int]  # {axis_code: score 1-5} pour les 8 axes
    axis_names: dict[str, str]  # {axis_code: name}
    text_inputs: dict[str, str]  # {axis_code: phrase libre}
    multiselects: dict[str, list[str]]  # {axis_code: options cochées} - Q3 IA stack notamment
    selects: dict[str, str]  # {axis_code: option choisie en single-select} - Q2 nb cas d'usage notamment
    chosen_anchors: dict[str, str]  # {axis_code: texte intégral de l'ancre choisie} - pour annexe PDF
    irritants: str  # text_area Q9 transverse - irritants quotidiens du répondant
    global_score: float
    level: int
    level_name: str
    level_description: str
    level_color: str
    strengths: list[tuple[str, str, int]]  # (axis_code, axis_name, score)
    gaps: list[tuple[str, str, int]]  # (axis_code, axis_name, score), triés croissant
    role: str
    organization: str
    effectif: str  # bucket taille effectif (intro page)
    secteur: str  # secteur entreprise (intro page)
    secteur_precision: str  # precision si secteur = Autre (intro page)
    # Champs deprecies (Q9 reconvertie en irritants en juin 2026) :
    # q9_real_score, q9_chosen_anchor, dissonance_declaratif_vs_reel,
    # has_dissonance ont ete retires car non pertinents sans Q9 scoree.


def load_questions(yaml_path: Path | str | None = None) -> dict:
    """Charge le YAML des questions."""
    if yaml_path is None:
        yaml_path = Path(__file__).parent / "questions_flash.yaml"
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def compute_flash_result(
    config: dict,
    answers: dict,
) -> FlashResult:
    """Calcule le résultat de l'audit flash.

    Args:
        config : dict chargé depuis questions_flash.yaml
        answers : dict avec les clés :
            - q1..q9 : score 1-5 (int) pour chaque question
            - q1_text..q8_text : phrase libre (str, optionnel)
            - role : str (rôle Q10)
            - organization : str (nom organisation)

    Returns:
        FlashResult avec tous les agrégats nécessaires à l'affichage et au PDF.
    """
    questions = config["questions"]
    level_colors = config["level_colors"]
    level_names = config["level_names"]
    level_descriptions = config["level_descriptions"]

    # Mapping axis_code → name + score
    axis_scores: dict[str, int] = {}
    axis_names: dict[str, str] = {}
    text_inputs: dict[str, str] = {}
    multiselects: dict[str, list[str]] = {}
    selects: dict[str, str] = {}
    chosen_anchors: dict[str, str] = {}
    irritants = ""

    for q in questions:
        qid = q["id"]
        axis_code = q["axis_code"]
        anchors = q.get("anchors") or {}

        if axis_code.startswith("TRANSVERSE"):
            # Q9 transverse irritants (text_area uniquement, pas de score)
            irritants = (answers.get(f"{qid}_text") or "").strip()
            continue

        score = int(answers.get(qid, 3))
        anchor_text = anchors.get(score, "")

        axis_scores[axis_code] = score
        axis_names[axis_code] = q["axis_name"]
        chosen_anchors[axis_code] = anchor_text
        text_value = (answers.get(f"{qid}_text") or "").strip()
        if text_value:
            text_inputs[axis_code] = text_value
        ms_value = answers.get(f"{qid}_multiselect") or []
        if ms_value:
            multiselects[axis_code] = [
                opt for opt in ms_value if isinstance(opt, str) and opt.strip()
            ]
        sel_value = (answers.get(f"{qid}_select") or "").strip()
        if sel_value:
            selects[axis_code] = sel_value

    # Score global = moyenne arithmétique des 8 axes
    if axis_scores:
        global_score = sum(axis_scores.values()) / len(axis_scores)
    else:
        global_score = 0.0

    # Niveau = round
    level = max(1, min(5, round(global_score)))
    level_name = level_names.get(level, "?")
    level_description = level_descriptions.get(level, "")
    level_color = level_colors.get(level, "#666666")

    # Forces et zones de progrès
    sorted_axes = sorted(axis_scores.items(), key=lambda kv: kv[1])
    strengths = [
        (code, axis_names[code], score)
        for code, score in sorted_axes
        if score >= 4
    ][-3:][::-1]  # top 3, décroissants
    gaps = [
        (code, axis_names[code], score)
        for code, score in sorted_axes
        if score <= 2
    ][:3]  # bottom 3, croissants

    # Si pas de gaps explicites (tous ≥ 3), on prend les 3 plus bas
    if not gaps:
        gaps = [
            (code, axis_names[code], score)
            for code, score in sorted_axes[:3]
        ]

    return FlashResult(
        axis_scores=axis_scores,
        axis_names=axis_names,
        text_inputs=text_inputs,
        multiselects=multiselects,
        selects=selects,
        chosen_anchors=chosen_anchors,
        irritants=irritants,
        global_score=round(global_score, 2),
        level=level,
        level_name=level_name,
        level_description=level_description,
        level_color=level_color,
        strengths=strengths,
        gaps=gaps,
        role=answers.get("role", "Non renseigné"),
        organization=answers.get("organization", "Votre organisation").strip()
            or "Votre organisation",
        effectif=(answers.get("effectif") or "Non renseigné").strip()
            or "Non renseigné",
        secteur=(answers.get("secteur") or "Non renseigné").strip()
            or "Non renseigné",
        secteur_precision=(answers.get("secteur_precision") or "").strip(),
    )
