"""
debug_scraper.py — Test the Tekion scraper with detailed logging
Run this from command line to see what's happening step-by-step.
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()

os.environ["BROWSER_USE_VERSION_CHECK"] = "false"
os.environ["ANONYMIZED_TELEMETRY"] = "false"

print("✓ Env vars set")

from langchain_anthropic import ChatAnthropic
from browser_use import Agent
from browser_use.browser.session import BrowserSession
from pydantic import BaseModel
from typing import Optional

print("✓ Imports successful")

# Load credentials
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
TEKION_URL = os.getenv("TEKION_URL", "https://app.tekioncloud.com/login?redirectTo=/")
TEKION_USER = os.getenv("TEKION_USERNAME")
TEKION_PASS = os.getenv("TEKION_PASSWORD")

if not CLAUDE_API_KEY:
    print("ERROR: CLAUDE_API_KEY not set in .env")
    sys.exit(1)
if not TEKION_USER or not TEKION_PASS:
    print("ERROR: TEKION_USERNAME or TEKION_PASSWORD not set in .env")
    sys.exit(1)

print(f"✓ Credentials loaded (user: {TEKION_USER})")

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

class HaikuLLM(ChatAnthropic):
    provider: str = "anthropic"

async def test_scrape():
    print("\n=== TESTING TEKION SCRAPER ===\n")

    print("Step 1: Creating LLM...")
    try:
        llm = HaikuLLM(
            model="claude-haiku-4-5",
            api_key=CLAUDE_API_KEY,
            timeout=60,
            max_retries=2,
        )
        print("✓ LLM created")
    except Exception as e:
        print(f"✗ LLM creation failed: {e}")
        return

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

    print("Step 2: Opening browser session...")
    try:
        browser_session = BrowserSession(headless=False, disable_security=True)
        print("✓ Browser session created (Chrome should open now...)")
    except Exception as e:
        print(f"✗ Browser session failed: {e}")
        return

    print("Step 3: Creating agent...")
    try:
        agent = Agent(
            task=task,
            llm=llm,
            browser_session=browser_session,
            use_vision=True,
            max_failures=5,
            output_model_schema=ScrapedLeads,
        )
        print("✓ Agent created (about to run...)")
    except Exception as e:
        print(f"✗ Agent creation failed: {e}")
        return

    print("Step 4: Running agent (watch for Chrome window)...")
    print("(This may take 2-5 minutes. If Chrome opens, the agent is working.)\n")

    try:
        result = await asyncio.wait_for(agent.run(max_steps=60), timeout=600)
        print(f"\n✓ Agent completed!")
        print(f"Result preview: {str(result)[:500]}")
    except asyncio.TimeoutError:
        print("✗ Agent timed out (10 minutes elapsed)")
        return
    except Exception as e:
        print(f"✗ Agent failed with error: {e}")
        import traceback
        traceback.print_exc()
        return

if __name__ == "__main__":
    asyncio.run(test_scrape())
