"""
cost_estimator.py — Penny-accurate API cost tracking
Haiku 4.5: $1.00/1M input, $5.00/1M output
"""

from database import get_conn
from datetime import date

HAIKU_INPUT_PER_TOKEN  = 1.00 / 1_000_000
HAIKU_OUTPUT_PER_TOKEN = 5.00 / 1_000_000

AVG_INPUT_TOKENS_PER_DRAFT  = 560
AVG_OUTPUT_TOKENS_PER_DRAFT = 55


def cost_per_draft() -> float:
    return (AVG_INPUT_TOKENS_PER_DRAFT * HAIKU_INPUT_PER_TOKEN +
            AVG_OUTPUT_TOKENS_PER_DRAFT * HAIKU_OUTPUT_PER_TOKEN)


def estimate_daily_cost(num_leads: int) -> dict:
    regen_rate = 0.15
    total_calls = num_leads * (1 + regen_rate)
    input_tokens  = total_calls * AVG_INPUT_TOKENS_PER_DRAFT
    output_tokens = total_calls * AVG_OUTPUT_TOKENS_PER_DRAFT
    input_cost    = input_tokens  * HAIKU_INPUT_PER_TOKEN
    output_cost   = output_tokens * HAIKU_OUTPUT_PER_TOKEN
    total_cost    = input_cost + output_cost
    return {
        "leads":          num_leads,
        "total_calls":    round(total_calls, 1),
        "input_tokens":   round(input_tokens),
        "output_tokens":  round(output_tokens),
        "input_cost":     round(input_cost, 6),
        "output_cost":    round(output_cost, 6),
        "total_cost":     round(total_cost, 6),
        "total_cost_str": f"${total_cost:.4f}",
        "monthly_proj":   round(total_cost * 30, 4),
    }


def get_actual_daily_cost(target_date: str = None) -> dict:
    if target_date is None:
        target_date = date.today().isoformat()

    conn = get_conn()
    row = conn.execute("""
        SELECT
            COUNT(*)                                    as total_drafts,
            SUM(COALESCE(input_tokens,  ?))             as input_tokens,
            SUM(COALESCE(output_tokens, ?))             as output_tokens
        FROM messages WHERE date(created_at) = ?
    """, (AVG_INPUT_TOKENS_PER_DRAFT, AVG_OUTPUT_TOKENS_PER_DRAFT, target_date)).fetchone()
    conn.close()

    total_drafts  = row[0] or 0
    input_tokens  = row[1] or 0
    output_tokens = row[2] or 0
    input_cost    = input_tokens  * HAIKU_INPUT_PER_TOKEN
    output_cost   = output_tokens * HAIKU_OUTPUT_PER_TOKEN
    total_cost    = input_cost + output_cost

    return {
        "date":           target_date,
        "total_drafts":   total_drafts,
        "input_tokens":   input_tokens,
        "output_tokens":  output_tokens,
        "input_cost":     round(input_cost, 6),
        "output_cost":    round(output_cost, 6),
        "total_cost":     round(total_cost, 6),
        "total_cost_str": f"${total_cost:.4f}",
    }
