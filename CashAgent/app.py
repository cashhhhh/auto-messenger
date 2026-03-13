"""
Cash's AI Agent — Streamlit Web Dashboard
Web-based version of the Tkinter dashboard for Codespace compatibility
"""

import streamlit as st
import asyncio
import subprocess
from datetime import datetime
from pathlib import Path

from database import (
    init_db, get_leads_for_queue, mark_message_sent,
    update_learning_patterns, get_conn, get_learning_stats, mark_converted
)
from scorer import score_all_leads
from generator import generate_batch
from cost_estimator import get_actual_daily_cost, estimate_daily_cost, cost_per_draft
from lead_validator import build_pre_batch_report, filter_already_messaged_today

# Page config
st.set_page_config(
    page_title="Cash's AI Agent — Grubbs Infiniti",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS
st.markdown("""
<style>
    [data-testid="stMetricValue"] { font-size: 24px; }
    .stButton > button { width: 100%; padding: 12px; font-weight: bold; }
    .log-box { font-family: 'Courier New'; font-size: 12px; max-height: 200px; overflow-y: auto; }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "logs" not in st.session_state:
    st.session_state.logs = []
    st.session_state.queue = []
    st.session_state.current_idx = 0
    init_db()

def log_msg(msg: str):
    """Add message to log"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.logs.append(f"[{timestamp}] {msg}")

def get_stats():
    """Fetch current dashboard stats"""
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM leads WHERE status NOT IN ('sold','dead')").fetchone()[0]
    quality = conn.execute("SELECT COUNT(*) FROM leads WHERE status NOT IN ('sold','dead') AND quality_score >= 2 AND phone IS NOT NULL AND phone != ''").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM messages WHERE approved=0").fetchone()[0]
    sent_t = conn.execute("SELECT COUNT(*) FROM messages WHERE sent_at >= date('now') AND approved=1").fetchone()[0]
    resp_t = conn.execute("SELECT COUNT(*) FROM messages WHERE response_at >= date('now')").fetchone()[0]
    t_sent = conn.execute("SELECT COUNT(*) FROM messages WHERE sent_at IS NOT NULL").fetchone()[0]
    t_resp = conn.execute("SELECT COUNT(*) FROM messages WHERE got_response=1").fetchone()[0]
    conn.close()

    rate = f"{round(t_resp/t_sent*100)}%" if t_sent > 0 else "N/A"
    cost = get_actual_daily_cost()

    return {
        "total_leads": total,
        "quality_leads": quality,
        "pending_texts": pending,
        "sent_today": sent_t,
        "resp_today": resp_t,
        "response_rate": rate,
        "cost": cost
    }

# Header
st.markdown("# ⬡ GRUBBS INFINITI — AI Sales Agent")

# Top action buttons
col1, col2, col3, col4 = st.columns(4)

with col1:
    if st.button("🔄 Sync Tekion Leads", use_container_width=True):
        log_msg("Starting Tekion sync...")
        try:
            from tekion import run_scrape
            result = asyncio.run(run_scrape())
            if result["status"] == "error":
                log_msg(f"ERROR: {result['message']}")
            elif result["status"] == "aborted":
                log_msg(f"ABORTED: {result['message']}")
            else:
                log_msg(f"✓ Sync done. Imported: {result['imported']} | Skipped: {result['skipped']} | Captured: {result['pct_captured']}%")
        except Exception as e:
            log_msg(f"Sync error: {str(e)}")

with col2:
    if st.button("🧠 Score All Leads", use_container_width=True):
        log_msg("Scoring leads...")
        try:
            count = score_all_leads()
            update_learning_patterns()
            log_msg(f"✓ Scored {count} leads.")
        except Exception as e:
            log_msg(f"Scoring error: {str(e)}")

with col3:
    if st.button("✍️ Generate Drafts", use_container_width=True):
        leads = get_leads_for_queue(limit=150)
        if not leads:
            log_msg("No textable leads. Sync and score first.")
        else:
            leads, dupes = filter_already_messaged_today(leads)
            if dupes:
                log_msg(f"Skipped {dupes} already messaged today.")
            if not leads:
                log_msg("All leads already messaged today.")
            else:
                proj = estimate_daily_cost(len(leads))
                report = build_pre_batch_report(leads, proj["total_cost"])
                st.session_state.confirm_batch = {
                    "leads": leads,
                    "count": len(leads),
                    "cost": proj["total_cost_str"]
                }

with col4:
    if st.button("✅ Mark Sold", use_container_width=True):
        st.session_state.show_mark_sold = True

# Batch confirmation dialog
if "confirm_batch" in st.session_state:
    with st.container(border=True):
        st.warning(f"**About to generate {st.session_state.confirm_batch['count']} drafts**\nEstimated cost: {st.session_state.confirm_batch['cost']}")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Approve", use_container_width=True):
                log_msg(f"Generating {len(st.session_state.confirm_batch['leads'])} drafts...")
                try:
                    results = generate_batch(st.session_state.confirm_batch["leads"])
                    log_msg(f"✓ Generated {len(results)} drafts.")

                    # Load queue
                    conn = get_conn()
                    rows = conn.execute("""
                        SELECT m.*, l.name, l.vehicle_interest, l.source, l.quality_score, ls.score
                        FROM messages m JOIN leads l ON l.id = m.lead_id
                        LEFT JOIN (SELECT lead_id, MAX(scored_at) as mx, score FROM lead_scores GROUP BY lead_id) ls ON ls.lead_id = l.id
                        WHERE m.approved=0 ORDER BY ls.score DESC
                    """).fetchall()
                    conn.close()
                    st.session_state.queue = [dict(r) for r in rows]
                    st.session_state.current_idx = 0
                    log_msg(f"{len(st.session_state.queue)} drafts in queue.")
                except Exception as e:
                    log_msg(f"Generation error: {str(e)}")
                del st.session_state.confirm_batch
                st.rerun()
        with col2:
            if st.button("❌ Cancel", use_container_width=True):
                log_msg("Batch cancelled.")
                del st.session_state.confirm_batch
                st.rerun()

# Mark sold dialog
if st.session_state.get("show_mark_sold"):
    with st.container(border=True):
        name = st.text_input("Enter customer name:")
        if st.button("Mark as Sold", use_container_width=True):
            if name:
                conn = get_conn()
                lead = conn.execute("SELECT id FROM leads WHERE name LIKE ?", (f"%{name}%",)).fetchone()
                conn.close()
                if lead:
                    mark_converted(lead["id"])
                    update_learning_patterns()
                    log_msg(f"✓ Marked {name} as SOLD.")
                    st.session_state.show_mark_sold = False
                    st.rerun()
                else:
                    st.error(f"No lead matching '{name}'")

st.divider()

# Main content
left_col, right_col = st.columns([1, 2.5])

with left_col:
    st.subheader("📊 Today's Stats")

    stats = get_stats()
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Active Leads", stats["total_leads"])
        st.metric("Pending Drafts", stats["pending_texts"])
        st.metric("Responses Today", stats["resp_today"])
    with col2:
        st.metric("Textable Leads", stats["quality_leads"])
        st.metric("Sent Today", stats["sent_today"])
        st.metric("Response Rate", stats["response_rate"])

    st.divider()

    st.subheader("💰 Daily Cost Estimator")
    st.caption("Haiku 4.5 · $1.00/1M in · $5.00/1M out")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Today (Actual)", stats["cost"]["total_cost_str"])
        st.metric("Drafts Today", stats["cost"]["total_drafts"])
    with col2:
        st.metric("Per Draft", f"${cost_per_draft():.6f}")
        st.metric("Tokens Today", f"{stats['cost']['input_tokens']:,}in / {stats['cost']['output_tokens']:,}out")

    st.subheader("📈 Projections")
    for n in [25, 50, 100, 125, 150]:
        proj = estimate_daily_cost(n)
        st.metric(f"{n} leads", f"{proj['total_cost_str']}/day · ${proj['monthly_proj']:.2f}/mo")

    st.divider()

    st.subheader("🧠 Learning Patterns")
    patterns = get_learning_stats()
    if patterns:
        for p in patterns[:6]:
            if p["attempts"] > 0:
                st.caption(f"{p['key']}: {round(p['response_rate']*100)}% resp")
    else:
        st.caption("No data yet. Send more texts to learn.")

with right_col:
    st.subheader("📨 Message Review Queue")

    if st.session_state.queue:
        msg = st.session_state.queue[st.session_state.current_idx]
        st.info(f"Reviewing {st.session_state.current_idx + 1} of {len(st.session_state.queue)}")

        # Lead info
        info_col1, info_col2, info_col3 = st.columns(3)
        with info_col1:
            st.metric("Customer", msg.get("name", "—"))
            st.metric("Score", f"{round(msg.get('score', 0), 1)}")
        with info_col2:
            st.metric("Vehicle", (msg.get("vehicle_interest", "—"))[:30])
            st.metric("Quality", f"{msg.get('quality_score', 0)}/4")
        with info_col3:
            st.metric("Source", msg.get("source", "—"))
            st.metric("Follow-up #", msg.get("follow_up_num", 1))

        # Message editor
        st.markdown("**DRAFT MESSAGE** (edit before sending):")
        draft = st.text_area(
            "Message draft",
            value=msg.get("draft", ""),
            height=150,
            label_visibility="collapsed"
        )

        # Action buttons
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("✅ SEND THIS TEXT", use_container_width=True):
                if draft.strip():
                    mark_message_sent(msg["id"], draft)
                    log_msg(f"✓ Sent to {msg.get('name')}: \"{draft[:60]}\"")
                    st.session_state.current_idx += 1
                    st.rerun()
                else:
                    st.error("Can't send an empty message.")
        with col2:
            if st.button("⏭ SKIP", use_container_width=True):
                log_msg(f"Skipped {st.session_state.queue[st.session_state.current_idx].get('name')}")
                st.session_state.current_idx += 1
                st.rerun()
        with col3:
            if st.button("🔄 REGENERATE", use_container_width=True):
                log_msg(f"Regenerating for {msg.get('name')}...")
                try:
                    conn = get_conn()
                    lead = dict(conn.execute("SELECT * FROM leads WHERE id=?", (msg["lead_id"],)).fetchone())
                    conn.close()
                    from generator import generate_message
                    result = generate_message(lead, follow_up_num=msg.get("follow_up_num", 1))
                    st.session_state.queue[st.session_state.current_idx]["draft"] = result["draft"]
                    st.session_state.queue[st.session_state.current_idx]["id"] = result["msg_id"]
                    log_msg("✓ Regenerated.")
                    st.rerun()
                except Exception as e:
                    log_msg(f"Regeneration error: {str(e)}")
    else:
        st.info("No drafts. Generate drafts first.")

# Log section
st.divider()
st.subheader("📋 Log")
with st.container(border=True, height=180):
    for log_entry in st.session_state.logs[-20:]:  # Show last 20 entries
        st.text(log_entry)

# Auto-refresh button
if st.button("🔄 Refresh All", use_container_width=True):
    st.rerun()
