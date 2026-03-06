#!/usr/bin/env python3
"""Quick stats and conversation viewer for scambaiter."""

import sys
import database as db

def print_stats():
    s = db.get_stats()
    print("\n  Scambaiter Stats")
    print("  ────────────────")
    print(f"  Total scammers baited : {s['total_conversations']}")
    print(f"  Currently active      : {s['active']}")
    print(f"  Total turns wasted    : {s['total_turns_wasted']}")
    print(f"  Avg turns per scammer : {s['avg_turns_per_scammer']}")
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
        print(f"    Subject : {r['subject']}")
        print(f"    Turns   : {r['turn_count']}")
        print(f"    Started : {r['created_at']}")
        print(f"    Last    : {r['last_activity_at']}")
        if r['next_reply_at']:
            print(f"    Bob replies at: {r['next_reply_at']} UTC")

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
        who = "SCAMMER" if msg["direction"] == "inbound" else "BOB    "
        print(f"  [{msg['timestamp']}] {who}:")
        print("  " + msg["content"].replace("\n", "\n  "))
        print()

if __name__ == "__main__":
    db.init_db()
    if len(sys.argv) == 1:
        print_stats()
        print_conversations()
    elif sys.argv[1] == "thread" and len(sys.argv) == 3:
        print_thread(int(sys.argv[2]))
    else:
        print("Usage: stats.py [thread <id>]")
