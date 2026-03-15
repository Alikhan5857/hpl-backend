# app/providers/sportmonks.py

import os
import requests
from typing import Any, Dict, Optional


def _base_url() -> str:
    return os.getenv("SPORTMONKS_BASE_URL", "https://cricket.sportmonks.com/api/v2.0").rstrip("/")


def _api_token() -> str:
    token = os.getenv("SPORTMONKS_API_KEY", "").strip()
    if not token:
        raise ValueError("SPORTMONKS_API_KEY missing in .env")
    return token


def sportmonks_get(path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Dict[str, Any]:
    url = f"{_base_url()}/{path.lstrip('/')}"
    qp = dict(params or {})
    qp["api_token"] = _api_token()

    r = requests.get(url, params=qp, timeout=timeout)
    try:
        data = r.json()
    except Exception:
        data = {"raw_text": r.text}

    return {
        "url_called": r.url,
        "status_code": r.status_code,
        "data": data,
    }


def list_fixtures(page: int = 1, per_page: int = 25, live_only: bool = False) -> Dict[str, Any]:
    params: Dict[str, Any] = {"page": page, "per_page": per_page}
    if live_only:
        params["filter[live]"] = "true"
    return sportmonks_get("/fixtures", params=params)


def get_fixture(fixture_id: int) -> Dict[str, Any]:
    params = {
        "include": "scoreboards",
    }
    return sportmonks_get(f"/fixtures/{fixture_id}", params=params)


# -----------------------------
# NEW HELPERS: finished/winner detect
# -----------------------------
def _extract_fixture_dict(fixture_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    outer = fixture_payload.get("data", {})
    if not isinstance(outer, dict):
        return None

    fx = outer.get("data")
    if isinstance(fx, list):
        return fx[0] if fx else None
    if isinstance(fx, dict):
        return fx

    if "id" in outer:
        return outer

    return None


def is_fixture_finished(payload):
    if not payload:
        return False

    fx = _extract_fixture_dict(payload)
    if not fx:
        return False

    status = str(fx.get("status", "")).lower()

    finished_states = [
        "finished",
        "ft",
        "completed",
        "result",
        "final result"
    ]

    return status in finished_states


def get_fixture_winner_pick(payload):
    if not payload:
        return None

    fx = _extract_fixture_dict(payload)
    if not fx:
        return None

    winner = fx.get("winner_team_id")
    home = fx.get("localteam_id")
    away = fx.get("visitorteam_id")

    if winner and home and int(winner) == int(home):
        return "A"

    if winner and away and int(winner) == int(away):
        return "B"

    return None

def normalize_scoreboard(payload):
    """
    Convert SportMonks scoreboard payload into simple format.
    """
    if not payload:
        return {}

    outer = payload.get("data", {})
    if not isinstance(outer, dict):
        return {}

    fx = outer.get("data")

    if isinstance(fx, list):
        fx = fx[0] if fx else {}

    if not isinstance(fx, dict):
        return {}

    home = fx.get("localteam", {}).get("name")
    away = fx.get("visitorteam", {}).get("name")

    home_score = fx.get("localteam_score")
    away_score = fx.get("visitorteam_score")

    return {
        "home_team": home,
        "away_team": away,
        "home_score": home_score,
        "away_score": away_score,
        "status": fx.get("status"),
    }