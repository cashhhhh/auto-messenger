"""
scorer.py — Lead priority scoring engine
Scores 0-100. Learns from response/conversion history over time.
"""

from datetime import datetime
from database import get_conn, get_learning_stats
import json

SOURCE_BASE = {
    "TrueCar": 72, "CARFAX": 68, "Capital One": 75,
    "JD Power": 65, "CarGurus": 70, "AutoTrader": 67,
    "Cars.com": 65, "Dealer": 80, "Referral": 90,
    "Walk": 85, "Phone": 82, "Unknown": 50,
}

STATUS_MULTIPLIER = {
    "new": 1.0, "contacted": 0.85, "engaged": 1.15, "dead": 0.1, "sold": 0.0,
}


def days_since(date_str: str) -> float:
    if not date_str:
        return 999
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "").replace("+00:00", ""))
        return (datetime.now() - dt).total_seconds() / 86400
    except Exception:
        return 999


def recency_score(days: float) -> float:
    if days < 0.5:  return 100
    if days < 1:    return 90
    if days < 2:    return 82
    if days < 3:    return 75
    if days < 5:    return 65
    if days < 7:    return 55
    if days < 14:   return 42
    if days < 30:   return 28
    if days < 60:   return 15
    return 5


def follow_up_penalty(lead_id: int) -> float:
    conn = get_conn()
    count = conn.execute("""
        SELECT COUNT(*) FROM messages
        WHERE lead_id=? AND sent_at IS NOT NULL AND got_response=0
    """, (lead_id,)).fetchone()[0]
    conn.close()
    return {0: 0, 1: -5, 2: -15, 3: -25}.get(count, -40)


def learned_source_boost(source: str, patterns: list) -> float:
    for p in patterns:
        if p["pattern_type"] == "source_response_rate" and p["key"] == source:
            rate = p["response_rate"]
            if rate > 0.4:  return 15
            if rate > 0.25: return 8
            if rate > 0.10: return 2
            if rate < 0.05: return -10
    return 0


def engagement_bonus(lead_id: int) -> float:
    conn = get_conn()
    responded = conn.execute("""
        SELECT COUNT(*) FROM messages WHERE lead_id=? AND got_response=1
    """, (lead_id,)).fetchone()[0]
    conn.close()
    return 20 if responded > 0 else 0


def score_lead(lead: dict, patterns: list = None) -> dict:
    if patterns is None:
        patterns = get_learning_stats()

    breakdown = {}
    source = lead.get("source") or "Unknown"
    source_score = SOURCE_BASE.get(source, 55)
    learned_adj = learned_source_boost(source, patterns)
    breakdown["source"] = source_score
    breakdown["learned_source_adj"] = learned_adj

    days_lead = days_since(lead.get("lead_date"))
    days_activity = days_since(lead.get("last_activity"))
    freshness = max(recency_score(days_lead), recency_score(days_activity))
    breakdown["recency"] = freshness

    status = lead.get("status", "new")
    status_mult = STATUS_MULTIPLIER.get(status, 0.8)
    breakdown["status_multiplier"] = status_mult

    penalty = follow_up_penalty(lead.get("id", 0))
    breakdown["followup_penalty"] = penalty

    eng_bonus = engagement_bonus(lead.get("id", 0))
    breakdown["engagement_bonus"] = eng_bonus

    quality_bonus = (lead.get("quality_score", 0) or 0) * 3
    breakdown["quality_bonus"] = quality_bonus

    raw = (
        (source_score * 0.25) +
        (freshness * 0.35) +
        learned_adj + penalty + eng_bonus + quality_bonus
    ) * status_mult

    score = max(0.0, min(100.0, raw))
    breakdown["final"] = round(score, 2)
    return {"score": round(score, 2), "breakdown": breakdown}


def score_all_leads():
    conn = get_conn()
    leads = conn.execute(
        "SELECT * FROM leads WHERE status NOT IN ('sold','dead')"
    ).fetchall()
    leads = [dict(r) for r in leads]
    conn.close()

    patterns = get_learning_stats()
    now = datetime.now().isoformat()
    conn = get_conn()
    for lead in leads:
        result = score_lead(lead, patterns)
        conn.execute("""
            INSERT INTO lead_scores (lead_id, score, score_breakdown, scored_at)
            VALUES (?, ?, ?, ?)
        """, (lead["id"], result["score"], json.dumps(result["breakdown"]), now))
    conn.commit()
    conn.close()
    return len(leads)


def get_best_tone(patterns: list) -> str:
    tone_rates = {
        p["key"]: p["response_rate"]
        for p in patterns if p["pattern_type"] == "tone_response_rate"
    }
    return max(tone_rates, key=tone_rates.get) if tone_rates else "casual"
