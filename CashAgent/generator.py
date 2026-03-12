"""
generator.py — Claude message writer in Cash's voice
"""

import anthropic
import json
from database import get_learning_stats, save_message_draft

CLAUDE_API_KEY = "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"


def get_client():
    return anthropic.Anthropic(api_key=CLAUDE_API_KEY)


def get_best_tone(patterns):
    tone_rates = {p["key"]: p["response_rate"] for p in patterns if p["pattern_type"] == "tone_response_rate"}
    return max(tone_rates, key=tone_rates.get) if tone_rates else "casual"


def build_system_prompt(patterns):
    tone_data = {
        p["key"]: {"response_rate": round(p["response_rate"] * 100, 1), "conversions": p["conversions"]}
        for p in patterns if p["pattern_type"] == "tone_response_rate"
    }
    tone_context = json.dumps(tone_data, indent=2) if tone_data else "No data yet — use casual."

    return f"""You are Cash's AI sales assistant at Grubbs Infiniti in San Antonio.

Your ONLY job: write short, human follow-up texts that get a response.

CASH'S VOICE — match exactly:
- 1-3 sentences max. Never longer.
- Casual and human. Never sounds like a dealership blast.
- Always end with one open-ended question.
- No emojis unless it flows naturally.
- No corporate filler: no "I hope this message finds you well", no "don't hesitate", no "at your earliest convenience".
- No em dashes.
- Sign off: "- Cash"
- Opener: "Hey [Name],"

THE GAME: Engagement is everything. A reply = a conversation = a deal.

TONE PERFORMANCE (what's actually working):
{tone_context}

SEQUENCE RULES:
- Follow-up 1: friendly, low pressure, reference their vehicle
- Follow-up 2: light curiosity or soft urgency
- Follow-up 3: value-add (trade value, incentive, market info)
- Follow-up 4+: breakup style — human, not pushy

OUTPUT: Return ONLY the text message. No label, no quotes, no explanation."""


def generate_message(lead: dict, follow_up_num: int = 1, tone: str = None) -> dict:
    client = get_client()
    patterns = get_learning_stats()

    if tone is None:
        tone = get_best_tone(patterns) if follow_up_num > 1 else "casual"

    system = build_system_prompt(patterns)
    vehicle = lead.get("vehicle_interest") or "a vehicle"
    source  = lead.get("source") or "online"
    name    = (lead.get("name") or "there").split()[0]

    from scorer import days_since
    d = days_since(lead.get("lead_date"))
    if d < 1:     days_ago = "today"
    elif d < 2:   days_ago = "yesterday"
    else:         days_ago = f"{int(d)} days ago"

    from database import get_conn
    conn = get_conn()
    last_msg = conn.execute("""
        SELECT sent_text, got_response, response_text FROM messages
        WHERE lead_id=? AND sent_at IS NOT NULL ORDER BY sent_at DESC LIMIT 1
    """, (lead["id"],)).fetchone()
    conn.close()

    history_context = ""
    if last_msg:
        history_context = f'\nLast message sent: "{last_msg["sent_text"]}"'
        if last_msg["got_response"]:
            history_context += f'\nThey replied: "{last_msg["response_text"]}"'
        else:
            history_context += "\nNo response yet."

    user_prompt = f"""Write follow-up #{follow_up_num} for this lead.

Customer: {name}
Vehicle interest: {vehicle}
Lead source: {source}
Lead came in: {days_ago}
Tone: {tone}{history_context}

Write the text now."""

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=200,
        system=system,
        messages=[{"role": "user", "content": user_prompt}]
    )

    draft         = response.content[0].text.strip()
    input_tokens  = response.usage.input_tokens
    output_tokens = response.usage.output_tokens

    msg_id = save_message_draft(
        lead_id=lead["id"], draft=draft, tone=tone,
        follow_up_num=follow_up_num,
        input_tokens=input_tokens, output_tokens=output_tokens
    )

    return {
        "msg_id": msg_id, "draft": draft, "tone": tone,
        "lead_name": name, "lead_id": lead["id"],
        "tokens_in": input_tokens, "tokens_out": output_tokens,
    }


def generate_batch(leads: list) -> list:
    results = []
    from database import get_conn
    for lead in leads:
        conn = get_conn()
        sent_count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE lead_id=? AND sent_at IS NOT NULL", (lead["id"],)
        ).fetchone()[0]
        conn.close()
        try:
            result = generate_message(lead, follow_up_num=sent_count + 1)
            results.append(result)
            print(f"Draft: {result['lead_name']} (#{sent_count+1}) — {result['tokens_in']}in/{result['tokens_out']}out")
        except Exception as e:
            print(f"Failed for {lead.get('name')}: {e}")
    return results
