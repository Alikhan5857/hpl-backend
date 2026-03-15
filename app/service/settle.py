def compute_winner_from_scoreboard(sb: dict) -> str:
    """
    return: "A" / "B" / "DRAW" / "REFUND"
    """
    if not sb:
        return "REFUND"

    # Example expectation:
    # sb = {"team_a": {"runs": 180}, "team_b": {"runs": 175}}
    a = ((sb.get("team_a") or {}).get("runs"))
    b = ((sb.get("team_b") or {}).get("runs"))

    if a is None or b is None:
        return "REFUND"

    if a > b:
        return "A"
    if b > a:
        return "B"
    return "DRAW"