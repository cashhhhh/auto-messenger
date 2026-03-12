"""
lead_validator.py — Bulletproof lead data guard
Validates, scores quality, and protects against bad data before any API spend
"""

import re
from database import get_conn, get_setting, log_scrape_run

# ── QUALITY SCORING ─────────────────────────────────────────────────────────
# Each lead gets a quality score 0-4
# Agent only drafts for leads scoring >= min_quality_score (default 2)

def score_quality(lead: dict) -> tuple:
    """
    Returns (quality_score 0-4, skip_reason or None)
    0 = totally useless, 4 = perfect lead
    """
    score = 0
    issues = []

    name = (lead.get("name") or "").strip()
    phone = (lead.get("phone") or "").strip()
    email = (lead.get("email") or "").strip()
    vehicle = (lead.get("vehicle_interest") or "").strip()
    source = (lead.get("source") or "").strip()

    # ── HARD DISQUALIFIERS (score = 0, skip entirely) ─────────────────────
    if not name or name.lower() in ("unknown", "n/a", "test", ""):
        return 0, "No valid name"

    if not phone and not email:
        return 0, "No phone or email"

    # ── QUALITY POINTS ────────────────────────────────────────────────────
    # Has a real phone number (10 digits)
    if phone and re.fullmatch(r'\d{10}', re.sub(r'\D', '', phone)):
        score += 2   # phone is the most valuable — can text them
    elif email and "@" in email:
        score += 1   # email only, less valuable

    # Has vehicle interest
    if vehicle and len(vehicle) > 3:
        score += 1

    # Has a known source
    if source and source.lower() not in ("unknown", ""):
        score += 1

    # Cap at 4
    score = min(score, 4)

    if score == 0:
        return 0, "Insufficient data"

    return score, None


def clean_phone(raw: str) -> str:
    """Strip to 10 digits. Return empty string if not valid."""
    if not raw:
        return ""
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def validate_and_enrich(leads: list) -> dict:
    """
    Run all leads through validation.
    Returns dict with validated leads + full audit report.
    """
    validated = []
    skipped = []
    enriched = 0

    for lead in leads:
        # Clean phone
        raw_phone = lead.get("phone") or ""
        clean = clean_phone(raw_phone)
        if clean:
            lead["phone"] = clean
            enriched += 1
        elif raw_phone:
            lead["phone"] = ""  # had a phone but it was invalid

        # Quality score
        q_score, skip_reason = score_quality(lead)
        lead["quality_score"] = q_score
        lead["skip_reason"] = skip_reason

        if skip_reason:
            skipped.append({
                "name": lead.get("name", "Unknown"),
                "reason": skip_reason,
                "phone": raw_phone,
            })
        else:
            validated.append(lead)

    return {
        "validated":   validated,
        "skipped":     skipped,
        "total_in":    len(leads),
        "total_valid": len(validated),
        "total_skip":  len(skipped),
        "enriched":    enriched,
    }


def verify_scrape_count(page_count: int, tekion_display_count: int) -> dict:
    """
    Compare what we scraped vs what Tekion says it has.
    Returns dict with match status and recommendation.
    """
    if tekion_display_count <= 0:
        return {
            "match": False,
            "tekion_count": tekion_display_count,
            "scraped_count": page_count,
            "pct_captured": 0,
            "recommendation": "Could not read Tekion lead count — proceed with caution.",
            "abort": False,
        }

    pct = (page_count / tekion_display_count) * 100 if tekion_display_count > 0 else 0

    if pct >= 90:
        status = "GOOD"
        abort = False
        rec = f"Captured {page_count}/{tekion_display_count} leads ({pct:.0f}%) — proceeding."
    elif pct >= 60:
        status = "PARTIAL"
        abort = False
        rec = f"Only captured {page_count}/{tekion_display_count} leads ({pct:.0f}%). Some leads may be missing. Proceeding anyway."
    else:
        status = "LOW"
        abort = True
        rec = f"Only captured {page_count}/{tekion_display_count} leads ({pct:.0f}%). Scrape likely failed. Aborting to protect budget."

    return {
        "match": pct >= 90,
        "tekion_count": tekion_display_count,
        "scraped_count": page_count,
        "pct_captured": round(pct, 1),
        "status": status,
        "recommendation": rec,
        "abort": abort,
    }


def check_duplicate_today(lead_id: int) -> bool:
    """Return True if we already drafted/sent a message to this lead today."""
    conn = get_conn()
    count = conn.execute("""
        SELECT COUNT(*) FROM messages
        WHERE lead_id = ?
          AND date(created_at) = date('now')
    """, (lead_id,)).fetchone()[0]
    conn.close()
    return count > 0


def filter_already_messaged_today(leads: list) -> tuple:
    """
    Remove leads already messaged today.
    Returns (filtered_leads, skipped_count)
    """
    filtered = []
    skipped = 0
    for lead in leads:
        if lead.get("id") and check_duplicate_today(lead["id"]):
            skipped += 1
        else:
            filtered.append(lead)
    return filtered, skipped


def build_pre_batch_report(leads: list, cost_estimate: float) -> dict:
    """
    Build the approval report shown before any API spend.
    Shows exactly what will happen and what it will cost.
    """
    sources = {}
    quality_dist = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    no_phone = 0
    no_vehicle = 0

    for lead in leads:
        src = lead.get("source") or "Unknown"
        sources[src] = sources.get(src, 0) + 1
        q = lead.get("quality_score", 0)
        quality_dist[q] = quality_dist.get(q, 0) + 1
        if not lead.get("phone"):
            no_phone += 1
        if not lead.get("vehicle_interest"):
            no_vehicle += 1

    return {
        "total_leads":    len(leads),
        "cost_estimate":  cost_estimate,
        "sources":        sources,
        "quality_dist":   quality_dist,
        "no_phone":       no_phone,
        "no_vehicle":     no_vehicle,
    }
