"""
tekion.py — AI-powered Tekion CRM scraper
Fully hardcoded — no settings required.
"""

import asyncio
import json
import os
import re
from typing import Optional
from pydantic import BaseModel

os.environ["BROWSER_USE_VERSION_CHECK"] = "false"
os.environ["ANONYMIZED_TELEMETRY"] = "false"

from langchain_anthropic import ChatAnthropic
from browser_use import Agent
from browser_use.browser.session import BrowserSession

from database import upsert_lead, log_scrape_run
from lead_validator import validate_and_enrich, verify_scrape_count

# ── HARDCODED CREDENTIALS ─────────────────────────────────────────────────────
CLAUDE_API_KEY = "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"
TEKION_URL     = "https://app.tekioncloud.com/login?redirectTo=/"
TEKION_USER    = "Cash.mccombs@grubbs.com"
TEKION_PASS    = "Winecountry25!"


class HaikuLLM(ChatAnthropic):
    provider: str = "anthropic"


class LeadRecord(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    vehicle_interest: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = "new"
    lead_date: Optional[str] = None

class ScrapedLeads(BaseModel):
    leads: list[LeadRecord]
    total_count_on_page: int


async def on_step(state, output, step_num):
    action = str(output.action)[:120] if output and hasattr(output, 'action') else str(output)[:120] if output else ""
    print(f"  Step {step_num}: {action}")


async def run_scrape() -> dict:
    print("Building LLM...")
    llm = HaikuLLM(
        model="claude-haiku-4-5",
        api_key=CLAUDE_API_KEY,
        timeout=60,
        max_retries=2,
    )
    print("LLM ready.")

    task = f"""
You are a CRM data harvesting agent. Log into Tekion and collect all active leads.

STEP 1 — Go to this exact URL:
{TEKION_URL}

STEP 2 — Log in:
- Type {TEKION_USER} into the username/email field
- Click Next if there is a Next button and wait for the password field
- Type {TEKION_PASS} into the password field
- Click Sign In and wait for the dashboard to load

STEP 3 — Navigate to leads:
- Find the CRM or Leads section in the navigation menu
- Click into it
- Click the "Active Leads" tab or filter

STEP 4 — Collect every lead on every page:
- For each lead: full name, phone, email, vehicle interest, source, status, date
- Page through ALL pages until done
- Note the total lead count shown on screen

STEP 5 — Return ONLY this JSON, nothing else:
{{
  "leads": [
    {{
      "name": "John Smith",
      "phone": "2105551234",
      "email": "john@email.com",
      "vehicle_interest": "2024 INFINITI QX60",
      "source": "TrueCar",
      "status": "new",
      "lead_date": "2026-03-10"
    }}
  ],
  "total_count_on_page": 47
}}
"""

    print("Opening browser...")
    browser_session = BrowserSession(headless=False, disable_security=True)

    print("Creating agent...")
    agent = Agent(
        task=task,
        llm=llm,
        browser_session=browser_session,
        use_vision=True,
        max_failures=5,
        output_model_schema=ScrapedLeads,
        register_new_step_callback=on_step,
    )

    raw_leads = []
    tekion_count = 0

    print("Running agent (Chrome opening now)...")
    try:
        result = await asyncio.wait_for(agent.run(max_steps=60), timeout=600)

        result_text = ""
        if hasattr(result, 'final_result'):
            fr = result.final_result()
            result_text = str(fr) if fr else ""
        else:
            result_text = str(result)

        print(f"\nAgent done. Preview:\n{result_text[:800]}\n")

        parsed = _parse_leads_json(result_text)
        if parsed:
            raw_leads    = parsed.get("leads", [])
            tekion_count = parsed.get("total_count_on_page", 0)
            print(f"Parsed {len(raw_leads)} leads.")
        else:
            print("WARNING: Could not parse leads JSON.")

    except asyncio.TimeoutError:
        print("ERROR: Timed out after 10 minutes.")
        log_scrape_run(0, 0, 0, 0, 0, "TIMEOUT", "10 min timeout")
        return {"status": "error", "message": "Timed out. Try again."}
    except Exception as e:
        import traceback
        traceback.print_exc()
        log_scrape_run(0, 0, 0, 0, 0, "ERROR", str(e))
        return {"status": "error", "message": str(e)}

    lead_dicts = []
    for lead in raw_leads:
        d = lead if isinstance(lead, dict) else (lead.model_dump() if hasattr(lead, 'model_dump') else dict(lead))
        if not d.get("name"):
            continue
        d["tekion_id"] = f"ai_{abs(hash(d.get('name','') + d.get('phone','') + d.get('email','')))}"
        d["raw_data"]  = {}
        lead_dicts.append(d)

    validation  = validate_and_enrich(lead_dicts)
    validated   = validation["validated"]
    count_check = verify_scrape_count(len(lead_dicts), tekion_count)

    if count_check["abort"]:
        log_scrape_run(len(lead_dicts), 0, validation["total_skip"], tekion_count, 0, "ABORTED", count_check["recommendation"])
        return {"status": "aborted", "message": count_check["recommendation"]}

    imported = 0
    for lead in validated:
        upsert_lead(lead)
        imported += 1

    log_scrape_run(len(lead_dicts), imported, validation["total_skip"], tekion_count,
                   1 if count_check["match"] else 0,
                   "OK" if count_check["match"] else "PARTIAL",
                   count_check["recommendation"])

    return {
        "status":         "ok",
        "raw_count":      len(lead_dicts),
        "tekion_count":   tekion_count,
        "imported":       imported,
        "skipped":        validation["total_skip"],
        "pct_captured":   count_check["pct_captured"],
        "count_status":   count_check["status"],
        "message":        count_check["recommendation"],
        "skipped_detail": validation["skipped"][:10],
    }


def _parse_leads_json(text: str) -> dict:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    for pattern in [r'```json\s*(\{.*?\})\s*```', r'```\s*(\{.*?\})\s*```', r'(\{"leads".*?\})']:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                continue
    s, e = text.find('{'), text.rfind('}')
    if s != -1 and e > s:
        try:
            return json.loads(text[s:e+1])
        except Exception:
            pass
    return None


if __name__ == "__main__":
    from database import init_db
    init_db()
    result = asyncio.run(run_scrape())
    print(result)
