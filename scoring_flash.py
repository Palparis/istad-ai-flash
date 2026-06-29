"""IstadAi - Scoring déterministe pour l'audit flash.

100% Python, zéro LLM. Calcule à partir des 9 ancres (8 axes + 1 transverse).

Logique :
- Score axe = ancre choisie (1-5) - simple, lisible, alignée CMMI
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
    q9_real_score: int  # score Q9 transverse (cas d'usage en prod réels)
    global_score: float
    level: int
    level_name: str
    level_description: str
    level_color: str
    strengths: list[tuple[str, str, int]]  # (axis_code, axis_name, score)
    gaps: list[tuple[str, str, int]]  # (axis_code, axis_name, score), triés croissant
    dissonance_declaratif_vs_reel: float  # global_score - q9_real_score, en valeur absolue
    has_dissonance: bool  # True si écart >= 1.0
    role: str
    organization: str


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
    q9_real_score = 3  # fallback

    for q in questions:
        qid = q["id"]
        axis_code = q["axis_code"]
        score = int(answers.get(qid, 3))

        if axis_code.startswith("TRANSVERSE"):
            q9_real_score = score
            continue

        axis_scores[axis_code] = score
        axis_names[axis_code] = q["axis_name"]
        text_value = (answers.get(f"{qid}_text") or "").strip()
        if text_value:
            text_inputs[axis_code] = text_value
        ms_value = answers.get(f"{qid}_multiselect") or []
        if ms_value:
            multiselects[axis_code] = [
                opt for opt in ms_value if isinstance(opt, str) and opt.strip()
            ]

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

    # Dissonance déclaratif vs réel
    dissonance = abs(global_score - float(q9_real_score))
    has_dissonance = dissonance >= 1.0

    return FlashResult(
        axis_scores=axis_scores,
        axis_names=axis_names,
        text_inputs=text_inputs,
        multiselects=multiselects,
        q9_real_score=q9_real_score,
        global_score=round(global_score, 2),
        level=level,
        level_name=level_name,
        level_description=level_description,
        level_color=level_color,
        strengths=strengths,
        gaps=gaps,
        dissonance_declaratif_vs_reel=round(dissonance, 2),
        has_dissonance=has_dissonance,
        role=answers.get("role", "Non renseigné"),
        organization=answers.get("organization", "Votre organisation").strip()
            or "Votre organisation",
    )
