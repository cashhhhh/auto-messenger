"""
dashboard.py — Cash's AI Agent Dashboard
Fully hardcoded — just open and run.
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import asyncio
import json
from datetime import datetime

from database import (
    init_db, get_leads_for_queue,
    mark_message_sent, update_learning_patterns, get_conn
)
from scorer import score_all_leads
from generator import generate_batch
from cost_estimator import get_actual_daily_cost, estimate_daily_cost, cost_per_draft
from lead_validator import build_pre_batch_report, filter_already_messaged_today

BG       = "#0e0e0e"
SURFACE  = "#1a1a1a"
SURFACE2 = "#242424"
GOLD     = "#c9a84c"
GOLD_DIM = "#8a6e2f"
WHITE    = "#ffffff"
GRAY     = "#888888"
GREEN    = "#4caf74"
RED      = "#e05555"


class AgentDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("Cash's AI Agent — Grubbs Infiniti")
        self.root.geometry("1150x780")
        self.root.configure(bg=BG)
        self.root.resizable(True, True)
        self.queue = []
        self.current_idx = 0
        init_db()
        self._build_ui()
        self._refresh_stats()

    def _build_ui(self):
        top = tk.Frame(self.root, bg=BG, pady=12)
        top.pack(fill="x", padx=20)
        tk.Label(top, text="⬡  GRUBBS INFINITI", font=("Helvetica", 11, "bold"), bg=BG, fg=GOLD).pack(side="left")
        tk.Label(top, text="AI Sales Agent", font=("Helvetica", 10), bg=BG, fg=GRAY).pack(side="left", padx=10)
        tk.Button(top, text="↻ Refresh", font=("Helvetica", 9), bg=SURFACE, fg=WHITE, relief="flat",
                  cursor="hand2", command=self._refresh_stats).pack(side="right", padx=4)
        tk.Button(top, text="✅ Mark Sold", font=("Helvetica", 9), bg=SURFACE, fg=GREEN, relief="flat",
                  cursor="hand2", command=self._mark_sold_dialog).pack(side="right", padx=4)
        tk.Frame(self.root, bg=GOLD, height=1).pack(fill="x")

        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True, padx=20, pady=16)
        left = tk.Frame(main, bg=SURFACE, width=270)
        left.pack(side="left", fill="y", padx=(0, 14))
        left.pack_propagate(False)
        self._build_left(left)
        right = tk.Frame(main, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        self._build_right(right)

    def _build_left(self, parent):
        tk.Label(parent, text="TODAY'S STATS", font=("Helvetica", 9, "bold"),
                 bg=SURFACE, fg=GOLD, pady=12).pack(fill="x", padx=16)
        self.stat_vars = {}
        for key, label in [
            ("total_leads",   "Active Leads"),
            ("quality_leads", "Textable Leads"),
            ("pending_texts", "Pending Drafts"),
            ("sent_today",    "Sent Today"),
            ("resp_today",    "Responses Today"),
            ("response_rate", "All-Time Response Rate"),
        ]:
            row = tk.Frame(parent, bg=SURFACE)
            row.pack(fill="x", padx=16, pady=2)
            tk.Label(row, text=label, font=("Helvetica", 8), bg=SURFACE, fg=GRAY).pack(side="left")
            var = tk.StringVar(value="—")
            self.stat_vars[key] = var
            tk.Label(row, textvariable=var, font=("Helvetica", 9, "bold"), bg=SURFACE, fg=WHITE).pack(side="right")

        tk.Frame(parent, bg=SURFACE2, height=1).pack(fill="x", padx=16, pady=10)

        for label, cmd in [
            ("🔄  Sync Tekion Leads",  self._sync_leads),
            ("🧠  Score All Leads",    self._score_leads),
            ("✍️   Generate Drafts",   self._generate_drafts),
        ]:
            tk.Button(parent, text=label, font=("Helvetica", 10), bg=GOLD_DIM, fg=WHITE,
                      relief="flat", cursor="hand2", pady=8, command=cmd).pack(fill="x", padx=16, pady=3)

        tk.Frame(parent, bg=SURFACE2, height=1).pack(fill="x", padx=16, pady=10)
        tk.Label(parent, text="DAILY COST ESTIMATOR", font=("Helvetica", 9, "bold"),
                 bg=SURFACE, fg=GOLD).pack(fill="x", padx=16)
        tk.Label(parent, text="Haiku 4.5  ·  $1.00/1M in  ·  $5.00/1M out",
                 font=("Helvetica", 7), bg=SURFACE, fg=GRAY).pack(fill="x", padx=16)

        tf = tk.Frame(parent, bg=SURFACE2, pady=5)
        tf.pack(fill="x", padx=16, pady=(5, 2))
        tk.Label(tf, text="TODAY (actual)", font=("Helvetica", 8, "bold"), bg=SURFACE2, fg=GRAY).pack(side="left", padx=6)
        self.cost_today_var = tk.StringVar(value="$0.0000")
        tk.Label(tf, textvariable=self.cost_today_var, font=("Helvetica", 11, "bold"), bg=SURFACE2, fg=GREEN).pack(side="right", padx=6)

        for key, label in [("drafts_today", "Drafts"), ("tokens_today", "Tokens")]:
            row = tk.Frame(parent, bg=SURFACE)
            row.pack(fill="x", padx=16, pady=1)
            tk.Label(row, text=label, font=("Helvetica", 8), bg=SURFACE, fg=GRAY).pack(side="left")
            var = tk.StringVar(value="0")
            setattr(self, f"{key}_var", var)
            tk.Label(row, textvariable=var, font=("Helvetica", 8, "bold"), bg=SURFACE, fg=WHITE).pack(side="right")

        tk.Frame(parent, bg=SURFACE2, height=1).pack(fill="x", padx=16, pady=5)
        tk.Label(parent, text="PROJECTIONS", font=("Helvetica", 8, "bold"), bg=SURFACE, fg=GRAY).pack(fill="x", padx=16)
        for n in [25, 50, 100, 125, 150]:
            proj = estimate_daily_cost(n)
            row = tk.Frame(parent, bg=SURFACE)
            row.pack(fill="x", padx=16, pady=1)
            tk.Label(row, text=f"{n} leads", font=("Helvetica", 8), bg=SURFACE, fg=GRAY).pack(side="left")
            tk.Label(row, text=f"{proj['total_cost_str']}/day  ${proj['monthly_proj']:.2f}/mo",
                     font=("Helvetica", 8, "bold"), bg=SURFACE, fg=WHITE).pack(side="right")

        row = tk.Frame(parent, bg=SURFACE)
        row.pack(fill="x", padx=16, pady=(4, 2))
        tk.Label(row, text="Per draft", font=("Helvetica", 8), bg=SURFACE, fg=GRAY).pack(side="left")
        tk.Label(row, text=f"${cost_per_draft():.6f}", font=("Helvetica", 8, "bold"), bg=SURFACE, fg=GOLD).pack(side="right")

        tk.Frame(parent, bg=SURFACE2, height=1).pack(fill="x", padx=16, pady=8)
        tk.Label(parent, text="LEARNING", font=("Helvetica", 9, "bold"), bg=SURFACE, fg=GOLD).pack(fill="x", padx=16)
        self.learning_text = tk.Text(parent, height=5, bg=SURFACE2, fg=GRAY,
                                     font=("Helvetica", 8), relief="flat", state="disabled", wrap="word")
        self.learning_text.pack(fill="x", padx=16, pady=6)

    def _build_right(self, parent):
        tk.Label(parent, text="MESSAGE REVIEW QUEUE", font=("Helvetica", 10, "bold"),
                 bg=BG, fg=WHITE).pack(anchor="w", pady=(0, 8))
        self.queue_label = tk.StringVar(value="No drafts. Generate drafts first.")
        tk.Label(parent, textvariable=self.queue_label, font=("Helvetica", 9), bg=BG, fg=GRAY).pack(anchor="w", pady=(0, 8))

        info = tk.Frame(parent, bg=SURFACE, pady=10, padx=14)
        info.pack(fill="x", pady=(0, 10))
        self.lead_vars = {}
        fields = [("name","Customer"),("vehicle","Vehicle"),("source","Source"),
                  ("score","Score"),("quality","Quality"),("followup","Follow-up #")]
        for i, (key, label) in enumerate(fields):
            f = tk.Frame(info, bg=SURFACE)
            f.grid(row=i//3, column=i%3, padx=10, pady=2, sticky="w")
            tk.Label(f, text=label.upper(), font=("Helvetica", 7), bg=SURFACE, fg=GRAY).pack(anchor="w")
            var = tk.StringVar(value="—")
            self.lead_vars[key] = var
            tk.Label(f, textvariable=var, font=("Helvetica", 10, "bold"), bg=SURFACE, fg=WHITE).pack(anchor="w")

        tk.Label(parent, text="DRAFT MESSAGE (edit before sending):",
                 font=("Helvetica", 9), bg=BG, fg=GRAY).pack(anchor="w", pady=(2, 2))
        self.msg_editor = scrolledtext.ScrolledText(
            parent, height=6, font=("Helvetica", 11),
            bg=SURFACE2, fg=WHITE, insertbackground=WHITE, relief="flat", wrap="word", padx=12, pady=10
        )
        self.msg_editor.pack(fill="x", pady=(0, 10))

        btns = tk.Frame(parent, bg=BG)
        btns.pack(fill="x")
        tk.Button(btns, text="✅  SEND THIS TEXT", font=("Helvetica", 11, "bold"),
                  bg=GREEN, fg=WHITE, relief="flat", cursor="hand2", pady=10,
                  command=self._approve).pack(side="left", expand=True, fill="x", padx=(0, 5))
        tk.Button(btns, text="⏭  SKIP", font=("Helvetica", 11),
                  bg=SURFACE, fg=WHITE, relief="flat", cursor="hand2", pady=10,
                  command=self._skip).pack(side="left", expand=True, fill="x", padx=(0, 5))
        tk.Button(btns, text="🔄  REGENERATE", font=("Helvetica", 11),
                  bg=SURFACE, fg=GOLD, relief="flat", cursor="hand2", pady=10,
                  command=self._regenerate).pack(side="left", expand=True, fill="x")

        tk.Label(parent, text="LOG", font=("Helvetica", 8, "bold"), bg=BG, fg=GRAY).pack(anchor="w", pady=(12, 2))
        self.log = scrolledtext.ScrolledText(parent, height=6, font=("Courier", 8),
                                              bg=SURFACE, fg=GRAY, relief="flat", state="disabled")
        self.log.pack(fill="both", expand=True)

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _refresh_stats(self):
        conn = get_conn()
        total   = conn.execute("SELECT COUNT(*) FROM leads WHERE status NOT IN ('sold','dead')").fetchone()[0]
        quality = conn.execute("SELECT COUNT(*) FROM leads WHERE status NOT IN ('sold','dead') AND quality_score >= 2 AND phone IS NOT NULL AND phone != ''").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM messages WHERE approved=0").fetchone()[0]
        sent_t  = conn.execute("SELECT COUNT(*) FROM messages WHERE sent_at >= date('now') AND approved=1").fetchone()[0]
        resp_t  = conn.execute("SELECT COUNT(*) FROM messages WHERE response_at >= date('now')").fetchone()[0]
        t_sent  = conn.execute("SELECT COUNT(*) FROM messages WHERE sent_at IS NOT NULL").fetchone()[0]
        t_resp  = conn.execute("SELECT COUNT(*) FROM messages WHERE got_response=1").fetchone()[0]
        conn.close()
        rate = f"{round(t_resp/t_sent*100)}%" if t_sent > 0 else "N/A"
        self.stat_vars["total_leads"].set(str(total))
        self.stat_vars["quality_leads"].set(str(quality))
        self.stat_vars["pending_texts"].set(str(pending))
        self.stat_vars["sent_today"].set(str(sent_t))
        self.stat_vars["resp_today"].set(str(resp_t))
        self.stat_vars["response_rate"].set(rate)
        cost = get_actual_daily_cost()
        self.cost_today_var.set(cost["total_cost_str"])
        self.drafts_today_var.set(str(cost["total_drafts"]))
        self.tokens_today_var.set(f"{cost['input_tokens']:,}in / {cost['output_tokens']:,}out")
        from database import get_learning_stats
        patterns = get_learning_stats()
        lines = [f"{p['key']}: {round(p['response_rate']*100)}% resp" for p in patterns[:6] if p["attempts"] > 0]
        text = "\n".join(lines) if lines else "No data yet.\nSend more texts to learn."
        self.learning_text.configure(state="normal")
        self.learning_text.delete("1.0", "end")
        self.learning_text.insert("end", text)
        self.learning_text.configure(state="disabled")

    def _sync_leads(self):
        self._log("Starting Tekion sync...")
        def run():
            from tekion import run_scrape
            result = asyncio.run(run_scrape())
            if result["status"] == "error":
                self._log(f"ERROR: {result['message']}")
            elif result["status"] == "aborted":
                self.root.after(0, lambda: messagebox.showwarning("Scrape Aborted", result['message']))
                self._log(f"ABORTED: {result['message']}")
            else:
                self._log(f"Sync done. Imported: {result['imported']} | Skipped: {result['skipped']} | Captured: {result['pct_captured']}%")
            self.root.after(0, self._refresh_stats)
        threading.Thread(target=run, daemon=True).start()

    def _score_leads(self):
        self._log("Scoring leads...")
        def run():
            count = score_all_leads()
            update_learning_patterns()
            self._log(f"Scored {count} leads.")
            self.root.after(0, self._refresh_stats)
        threading.Thread(target=run, daemon=True).start()

    def _generate_drafts(self):
        leads = get_leads_for_queue(limit=150)
        if not leads:
            self._log("No textable leads. Sync and score first.")
            return
        leads, dupes = filter_already_messaged_today(leads)
        if dupes:
            self._log(f"Skipped {dupes} already messaged today.")
        if not leads:
            self._log("All leads already messaged today.")
            return
        from cost_estimator import estimate_daily_cost
        proj = estimate_daily_cost(len(leads))
        report = build_pre_batch_report(leads, proj["total_cost"])
        msg = (f"ABOUT TO GENERATE DRAFTS\n\nLeads: {report['total_leads']}\n"
               f"Estimated cost: {proj['total_cost_str']}\n\nApprove?")
        if not messagebox.askyesno("Approve Batch", msg):
            self._log("Batch cancelled.")
            return
        self._log(f"Generating {len(leads)} drafts...")
        def run():
            results = generate_batch(leads)
            self._log(f"Generated {len(results)} drafts.")
            self.root.after(0, self._load_queue)
        threading.Thread(target=run, daemon=True).start()

    def _load_queue(self):
        conn = get_conn()
        rows = conn.execute("""
            SELECT m.*, l.name, l.vehicle_interest, l.source, l.quality_score, ls.score
            FROM messages m JOIN leads l ON l.id = m.lead_id
            LEFT JOIN (SELECT lead_id, MAX(scored_at) as mx, score FROM lead_scores GROUP BY lead_id) ls ON ls.lead_id = l.id
            WHERE m.approved=0 ORDER BY ls.score DESC
        """).fetchall()
        conn.close()
        self.queue = [dict(r) for r in rows]
        self.current_idx = 0
        self._log(f"{len(self.queue)} drafts in queue.")
        self._show_current()

    def _show_current(self):
        if self.current_idx >= len(self.queue):
            self.queue_label.set("✅ Queue empty.")
            self.msg_editor.delete("1.0", "end")
            for var in self.lead_vars.values():
                var.set("—")
            return
        msg = self.queue[self.current_idx]
        self.queue_label.set(f"Reviewing {self.current_idx + 1} of {len(self.queue)}")
        self.lead_vars["name"].set(msg.get("name") or "—")
        self.lead_vars["vehicle"].set((msg.get("vehicle_interest") or "—")[:30])
        self.lead_vars["source"].set(msg.get("source") or "—")
        self.lead_vars["score"].set(str(round(msg.get("score") or 0, 1)))
        self.lead_vars["quality"].set(f"{msg.get('quality_score', 0)}/4")
        self.lead_vars["followup"].set(str(msg.get("follow_up_num") or 1))
        self.msg_editor.delete("1.0", "end")
        self.msg_editor.insert("1.0", msg.get("draft") or "")

    def _approve(self):
        if not self.queue or self.current_idx >= len(self.queue):
            return
        msg = self.queue[self.current_idx]
        final = self.msg_editor.get("1.0", "end").strip()
        if not final:
            messagebox.showwarning("Empty", "Can't send an empty message.")
            return
        mark_message_sent(msg["id"], final)
        self._log(f"Sent to {msg.get('name')}: \"{final[:60]}\"")
        self.current_idx += 1
        self._show_current()
        self._refresh_stats()

    def _skip(self):
        if not self.queue:
            return
        self._log(f"Skipped {self.queue[self.current_idx].get('name')}")
        self.current_idx += 1
        self._show_current()

    def _regenerate(self):
        if not self.queue or self.current_idx >= len(self.queue):
            return
        msg = self.queue[self.current_idx]
        self._log(f"Regenerating for {msg.get('name')}...")
        def run():
            conn = get_conn()
            lead = dict(conn.execute("SELECT * FROM leads WHERE id=?", (msg["lead_id"],)).fetchone())
            conn.close()
            from generator import generate_message
            result = generate_message(lead, follow_up_num=msg.get("follow_up_num", 1))
            self.queue[self.current_idx]["draft"] = result["draft"]
            self.queue[self.current_idx]["id"] = result["msg_id"]
            self.root.after(0, self._show_current)
            self._log("Regenerated.")
        threading.Thread(target=run, daemon=True).start()

    def _mark_sold_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("Mark Lead as Sold")
        win.geometry("360x200")
        win.configure(bg=BG)
        win.grab_set()
        tk.Label(win, text="Enter customer name:", font=("Helvetica", 10), bg=BG, fg=WHITE).pack(pady=14)
        entry = tk.Entry(win, font=("Helvetica", 11), bg=SURFACE2, fg=WHITE, insertbackground=WHITE, relief="flat")
        entry.pack(fill="x", padx=30, ipady=8)
        def do_mark():
            name = entry.get().strip()
            if not name:
                return
            conn = get_conn()
            lead = conn.execute("SELECT id FROM leads WHERE name LIKE ?", (f"%{name}%",)).fetchone()
            conn.close()
            if not lead:
                messagebox.showwarning("Not Found", f"No lead matching '{name}'")
                return
            from database import mark_converted
            mark_converted(lead["id"])
            update_learning_patterns()
            self._log(f"Marked {name} as SOLD.")
            self._refresh_stats()
            win.destroy()
        tk.Button(win, text="Mark as Sold", font=("Helvetica", 10, "bold"),
                  bg=GREEN, fg=WHITE, relief="flat", pady=10,
                  command=do_mark).pack(pady=14, padx=30, fill="x")


if __name__ == "__main__":
    root = tk.Tk()
    app = AgentDashboard(root)
    root.mainloop()
