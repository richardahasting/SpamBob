#!/usr/bin/env python3
"""
Conversation viewer for SpamBob.

Usage:
  python3 show_convo.py                          # list all conversations
  python3 show_convo.py scammer@example.com      # show full thread
  python3 show_convo.py --all                    # list including completed/abandoned
  python3 show_convo.py --md scammer@example.com # dump to markdown, open in mdview
"""

import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import database as db

RED    = "\033[91m"
BLUE   = "\033[94m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"
LINE   = "═" * 64
DASH   = "─" * 64


def status_color(status):
    return {
        "active":    GREEN,
        "completed": BLUE,
        "abandoned": DIM,
    }.get(status, RESET)


def list_conversations(show_all=False):
    db.init_db()
    with db.get_conn() as conn:
        where = "" if show_all else "WHERE status = 'active'"
        rows = conn.execute(
            f"SELECT * FROM conversations {where} ORDER BY last_activity_at DESC"
        ).fetchall()

    if not rows:
        print("\n  No conversations found.")
        return

    s = db.get_stats()
    print(f"\n{BOLD}  SpamBob — Conversation List{RESET}")
    print(f"  {DASH[:50]}")
    print(f"  Active: {GREEN}{s['active']}{RESET}  |  "
          f"Total: {s['total_conversations']}  |  "
          f"Turns wasted: {BOLD}{s['total_turns_wasted']}{RESET}  |  "
          f"Avg turns: {s['avg_turns_per_scammer']}")
    print(f"  {DASH[:50]}\n")

    for r in rows:
        col = status_color(r["status"])
        print(f"  {col}{BOLD}[{r['status'].upper():10}]{RESET}  "
              f"{r['scammer_email']}")
        print(f"  {'':14}{DIM}Persona: {r['persona_key']:12}  "
              f"Turns: {r['turn_count']:3}  "
              f"Last: {r['last_activity_at'][:16]}{RESET}")
        print(f"  {'':14}{DIM}Subject: {(r['subject'] or '')[:60]}{RESET}\n")


def show_thread(email: str, as_markdown: bool = False):
    db.init_db()
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE scammer_email = ? ORDER BY created_at",
            (email.lower(),),
        ).fetchall()

    if not rows:
        print(f"\n  No conversations found for {email}")
        return

    if as_markdown:
        _show_thread_md(email, rows)
    else:
        _show_thread_terminal(email, rows)


def _show_thread_terminal(email, rows):
    for conv in rows:
        col = status_color(conv["status"])
        print(f"\n{LINE}")
        print(f"{BOLD}SCAMMER : {email}{RESET}")
        print(f"Persona : {conv['persona_key']}  |  "
              f"Status: {col}{conv['status'].upper()}{RESET}  |  "
              f"Turns: {conv['turn_count']}")
        print(f"Started : {conv['created_at'][:16]}  |  "
              f"Last: {conv['last_activity_at'][:16]}")
        print(f"Subject : {conv['subject']}")
        print(LINE)

        messages = db.get_messages(conv["id"])
        for i, msg in enumerate(messages, 1):
            if msg["direction"] == "inbound":
                prefix = f"{RED}{BOLD}[SCAMMER → Turn {i}]{RESET}"
            else:
                prefix = f"{BLUE}{BOLD}[{conv['persona_key'].title()} → Turn {i}]{RESET}"
            print(f"\n{prefix}  {DIM}{msg['timestamp'][:16]}{RESET}")
            print(DASH)
            print(msg["content"])
            print(DASH)


def _show_thread_md(email, rows):
    lines = [f"# SpamBob — Thread with {email}\n"]
    for conv in rows:
        lines.append(f"## {conv['persona_key'].title()} ({conv['status'].upper()})")
        lines.append(f"**Turns:** {conv['turn_count']}  |  "
                     f"**Started:** {conv['created_at'][:16]}  |  "
                     f"**Last:** {conv['last_activity_at'][:16]}\n")
        messages = db.get_messages(conv["id"])
        for i, msg in enumerate(messages, 1):
            if msg["direction"] == "inbound":
                lines.append(f"### 📨 Scammer → {conv['persona_key'].title()} (Turn {i})")
            else:
                lines.append(f"### 📤 {conv['persona_key'].title()} → Scammer (Turn {i})")
            lines.append(f"\n```\n{msg['content']}\n```\n")
        lines.append("---\n")

    md = "\n".join(lines)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md",
                                     prefix="spambob_thread_",
                                     delete=False) as f:
        f.write(md)
        path = f.name

    print(f"Opening {path} in browser...")
    subprocess.run(["mdview", "-b", path])


def main():
    args = sys.argv[1:]
    as_md  = "--md" in args
    show_all = "--all" in args
    args = [a for a in args if not a.startswith("--")]

    db.init_db()
    if not args:
        list_conversations(show_all=show_all)
    else:
        show_thread(args[0], as_markdown=as_md)


if __name__ == "__main__":
    main()
