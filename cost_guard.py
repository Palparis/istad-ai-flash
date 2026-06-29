"""IstadAi - Garde-fou budget API pour l'analyse LLM des verbatims.

Limite le nombre d'analyses LLM par jour et par mois pour éviter de saturer
le budget Anthropic en cas de pic de trafic ou d'abus. Si un cap est atteint,
l'analyse LLM est skip et l'utilisateur a un audit standard (déterministe).

Configuration via variables d'environnement :
    LLM_DAILY_CAP        = 50    (nb max analyses LLM par jour)
    LLM_MONTHLY_CAP      = 500   (nb max analyses LLM par mois)
    LLM_COST_PER_AUDIT_EUR = 0.005  (coût estimé Haiku 4.5 par audit)

Persistance : fichier JSON local ~/.audit-flash-cost-counter.json.
Sur Streamlit Cloud, ce fichier est reset à chaque redéploiement (= les
compteurs repartent à zéro). C'est volontairement permissif : on perd des
caps en cas de redéploiement, mais on évite la complexité d'un store externe
pour ce MVP.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

# Caps par défaut (override possible via variables d'env)
DAILY_CAP_DEFAULT = 50
MONTHLY_CAP_DEFAULT = 500
COST_PER_AUDIT_EUR_DEFAULT = 0.005  # estimation Haiku 4.5

# Localisation du compteur. Sous Streamlit Cloud, $HOME est /home/appuser
COUNTER_PATH = Path.home() / ".audit-flash-cost-counter.json"


def _load_counter() -> dict:
    """Charge le compteur depuis le fichier JSON, retourne {} si absent ou corrompu."""
    if not COUNTER_PATH.is_file():
        return {}
    try:
        return json.loads(COUNTER_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Compteur cost_guard corrompu, reset : %s", exc)
        return {}


def _save_counter(counter: dict) -> None:
    """Persiste le compteur. Best-effort, n'échoue pas si le filesystem est read-only."""
    try:
        COUNTER_PATH.write_text(
            json.dumps(counter, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("Impossible d'écrire le compteur cost_guard : %s", exc)


def get_daily_cap() -> int:
    try:
        return int(os.environ.get("LLM_DAILY_CAP", DAILY_CAP_DEFAULT))
    except (TypeError, ValueError):
        return DAILY_CAP_DEFAULT


def get_monthly_cap() -> int:
    try:
        return int(os.environ.get("LLM_MONTHLY_CAP", MONTHLY_CAP_DEFAULT))
    except (TypeError, ValueError):
        return MONTHLY_CAP_DEFAULT


def get_cost_per_audit_eur() -> float:
    try:
        return float(os.environ.get("LLM_COST_PER_AUDIT_EUR", COST_PER_AUDIT_EUR_DEFAULT))
    except (TypeError, ValueError):
        return COST_PER_AUDIT_EUR_DEFAULT


def is_llm_available() -> tuple[bool, str]:
    """Vérifie si on peut encore lancer une analyse LLM aujourd'hui.

    Returns:
        (available, reason) où reason est "" si OK, sinon "daily_cap" ou "monthly_cap".
    """
    today_str = date.today().isoformat()
    month_str = date.today().strftime("%Y-%m")

    counter = _load_counter()
    daily_counter = counter.get("daily", {})
    daily_count = daily_counter.get(today_str, 0)
    monthly_count = sum(v for k, v in daily_counter.items() if k.startswith(month_str))

    if daily_count >= get_daily_cap():
        return False, "daily_cap"
    if monthly_count >= get_monthly_cap():
        return False, "monthly_cap"
    return True, ""


def increment_counter() -> None:
    """Incrémente le compteur après un appel LLM réussi."""
    today_str = date.today().isoformat()
    counter = _load_counter()
    if "daily" not in counter:
        counter["daily"] = {}
    counter["daily"][today_str] = counter["daily"].get(today_str, 0) + 1
    _save_counter(counter)


def get_stats() -> dict:
    """Statistiques d'usage pour affichage admin (sidebar ou notification)."""
    today_str = date.today().isoformat()
    month_str = date.today().strftime("%Y-%m")
    counter = _load_counter()
    daily_counter = counter.get("daily", {})
    daily_count = daily_counter.get(today_str, 0)
    monthly_count = sum(v for k, v in daily_counter.items() if k.startswith(month_str))
    cost_per_audit = get_cost_per_audit_eur()
    return {
        "daily_count": daily_count,
        "daily_cap": get_daily_cap(),
        "monthly_count": monthly_count,
        "monthly_cap": get_monthly_cap(),
        "estimated_monthly_cost_eur": round(monthly_count * cost_per_audit, 4),
        "estimated_remaining_monthly_eur": round(
            (get_monthly_cap() - monthly_count) * cost_per_audit, 4
        ),
    }
