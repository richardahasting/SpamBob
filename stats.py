#!/usr/bin/env python3
"""Stats, conversation viewer, and daily digest emailer for scambaiter."""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import database as db

DIGEST_TO = "richard@hastingtx.org"
DIGEST_FROM = "spambob@firstchurchoffidelity.org"


# ── Terminal stats ────────────────────────────────────────────────────────────

def print_stats():
    s = db.get_stats()
    print("\n  Scambaiter Stats")
    print("  ────────────────")
    print(f"  Total scammers baited : {s['total_conversations']}")
    print(f"  Currently active      : {s['active']}")
    print(f"  Total turns wasted    : {s['total_turns_wasted']}")
    print(f"  Avg turns per scammer : {s['avg_turns_per_scammer']}")
    if s["by_persona"]:
        print()
        for p in s["by_persona"]:
            print(f"    {p['persona_key']:12} {p['cnt']:3} convos  {p['turns'] or 0:4} turns")
    print()


def print_conversations():
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM conversations ORDER BY last_activity_at DESC"
        ).fetchall()
    if not rows:
        print("  No conversations yet.")
        return
    for r in rows:
        print(f"\n  [{r['status'].upper()}] {r['scammer_email']}")
        print(f"    Persona : {r['persona_key']}")
        print(f"    Subject : {r['subject']}")
        print(f"    Turns   : {r['turn_count']}")
        print(f"    Started : {r['created_at']}")
        print(f"    Last    : {r['last_activity_at']}")
        if r["next_reply_at"]:
            print(f"    Replies : {r['next_reply_at']} UTC")


def print_thread(conv_id: int):
    with db.get_conn() as conn:
        conv = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conv_id,)
        ).fetchone()
    if not conv:
        print(f"  No conversation #{conv_id}")
        return
    print(f"\n  Thread with {conv['scammer_email']}")
    print(f"  Subject: {conv['subject']}\n")
    for msg in db.get_messages(conv_id):
        who = "SCAMMER" if msg["direction"] == "inbound" else conv["persona_key"].upper()
        print(f"  [{msg['timestamp']}] {who}:")
        print("  " + msg["content"].replace("\n", "\n  "))
        print()


# ── Daily digest email ────────────────────────────────────────────────────────

def build_digest() -> str:
    s = db.get_stats()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    with db.get_conn() as conn:
        active_rows = conn.execute(
            "SELECT * FROM conversations WHERE status='active' ORDER BY last_activity_at DESC"
        ).fetchall()
        recent_abandoned = conn.execute(
            """SELECT * FROM conversations WHERE status='abandoned'
               AND last_activity_at >= datetime('now', '-7 days')
               ORDER BY last_activity_at DESC"""
        ).fetchall()
        longest = conn.execute(
            """SELECT scammer_email, persona_key, turn_count
               FROM conversations WHERE status='active'
               ORDER BY turn_count DESC LIMIT 1"""
        ).fetchone()

    lines = [
        f"SpamBob Daily Digest — {now}",
        "=" * 50,
        "",
        f"  Total scammers engaged : {s['total_conversations']}",
        f"  Currently active       : {s['active']}",
        f"  Total turns wasted     : {s['total_turns_wasted']}",
        f"  Avg turns per scammer  : {s['avg_turns_per_scammer']}",
        "",
    ]

    if longest:
        lines += [
            f"  Longest active thread  : {longest['scammer_email']}",
            f"                           {longest['turn_count']} turns as {longest['persona_key']}",
            "",
        ]

    if s["by_persona"]:
        lines.append("  By persona:")
        for p in s["by_persona"]:
            lines.append(f"    {p['persona_key']:12} {p['cnt']:3} convos   {p['turns'] or 0:4} turns wasted")
        lines.append("")

    if active_rows:
        lines.append("  Active conversations:")
        lines.append("  " + "-" * 48)
        for r in active_rows:
            lines.append(f"  [{r['persona_key']:12}] {r['scammer_email']}")
            lines.append(f"    Turns: {r['turn_count']}  |  Last: {r['last_activity_at'][:16]}")
            lines.append(f"    Subject: {(r['subject'] or '')[:60]}")
            if r["next_reply_at"]:
                lines.append(f"    Next reply: {r['next_reply_at'][:16]} UTC")
            lines.append("")

    if recent_abandoned:
        lines.append("  Recently abandoned (last 7 days):")
        for r in recent_abandoned:
            lines.append(f"  {r['scammer_email']}  ({r['turn_count']} turns)")
        lines.append("")

    lines += [
        "─" * 50,
        "The congregation is on the job.",
        "",
    ]
    return "\n".join(lines)


def send_digest():
    """Build and email the daily digest via local sendmail."""
    db.init_db()
    body = build_digest()
    subject = f"SpamBob Digest — {datetime.now().strftime('%Y-%m-%d')}"

    from email.mime.text import MIMEText
    from email.utils import formatdate, make_msgid

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"]       = DIGEST_FROM
    msg["To"]         = DIGEST_TO
    msg["Subject"]    = subject
    msg["Date"]       = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="firstchurchoffidelity.org")

    proc = subprocess.run(
        ["/usr/sbin/sendmail", "-f", DIGEST_FROM, "-t"],
        input=msg.as_bytes(),
        capture_output=True,
    )
    if proc.returncode == 0:
        print(f"Digest sent to {DIGEST_TO}")
    else:
        print(f"sendmail error: {proc.stderr.decode()}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    if len(sys.argv) == 1:
        print_stats()
        print_conversations()
    elif sys.argv[1] == "thread" and len(sys.argv) == 3:
        print_thread(int(sys.argv[2]))
    elif sys.argv[1] == "digest":
        if "--send" in sys.argv:
            send_digest()
        else:
            print(build_digest())
    else:
        print("Usage:")
        print("  stats.py                  — summary + active conversations")
        print("  stats.py thread <id>      — full message thread")
        print("  stats.py digest           — preview digest email")
        print("  stats.py digest --send    — email digest to richard@hastingtx.org")
