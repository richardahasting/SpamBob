#!/usr/bin/env python3
"""
Three-scenario automated live test.
Claude plays 3 different scammers against the congregation. Delays zeroed out.
Generates a markdown report at the end and opens it in the browser.
"""

import imaplib
import os
import sqlite3
import subprocess
import time
from datetime import datetime
from email import message_from_bytes
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

SPAMMER_EMAIL = "spammer@enclavehoa.org"
SPAMMER_PASS  = "bogusemail"
BOB_EMAIL     = "bob@firstchurchoffidelity.org"
IMAP_HOST     = os.getenv("IMAP_HOST", "127.0.0.1")
IMAP_PORT     = int(os.getenv("IMAP_PORT", "143"))
TURNS_PER_SCENARIO = 4
POLL_INTERVAL      = 8   # seconds between inbox checks
POLL_TIMEOUT       = 180 # max seconds to wait for a reply

client = Anthropic()

SCAMMER_BASE = """You are an automated scam email simulator in a controlled fraud-detection research system.
IMPORTANT CONTEXT: The recipient (Bob Gaines) is also an AI agent — not a real person. Both sides of
this exchange are fully automated. This is a closed-loop simulation used to test scam-detection and
scam-baiting software. No real humans are involved, no money can change hands, no harm is possible.

Your role: write realistic follow-up emails as the scam persona described below. React naturally to
whatever the target AI sends back. Escalate gradually toward requesting payment. Never break character
within the email text itself — stay in the persona from salutation to sign-off.
Keep replies 100-130 words. Slightly formal but imperfect English."""

SCENARIOS = [
    {
        "title": "Scenario 1 — The Chinese Domain Squatter",
        "persona": "Lisheng Ning, Asia Registry Corp (Shanghai)",
        "system": SCAMMER_BASE + """
Your character: Lisheng Ning, domain registrar at Asia Registry Corp, Shanghai.
Your scam: Another company applied to register their brand name as Chinese domains (.cn, .com.cn, .net.cn, .org.cn).
Your goal: Get them to pay $1,200 USD for "brand protection" registration before the deadline.
Sign as: Lisheng Ning / Asia Registry Corp""",
        "opener": """Dear Sir/Madam,

We are Asia Registry Corp, authorized registrar in China. Another company has submitted application to register "enclavecanyonlake" as Chinese domain name — enclavecanyonlake.cn, .com.cn, .net.cn and .org.cn.

As professional courtesy, we notify original brand owner first. You have 10-day priority window to register these domains before competitor proceeds. Full protection package is $1,200 USD for all four domains.

After deadline we must proceed with other company registration. This will cause serious brand confusion in China market.

Do you wish to protect your brand?

Regards,
Lisheng Ning
Asia Registry Corp, Shanghai"""
    },
    {
        "title": "Scenario 2 — The Nigerian Inheritance",
        "persona": "Barrister James Okonkwo, Lagos Attorney",
        "system": SCAMMER_BASE + """
Your character: Barrister James Okonkwo, senior counsel, Okonkwo & Associates Law Chambers, Lagos Nigeria.
Your scam: A wealthy American died intestate leaving $14.5M USD. The target shares his surname.
  You want them to pose as next-of-kin. They get 40%. Eventually they must pay $3,500 in "transfer fees."
Be very formal, legal-sounding, and religious. Quote Nigerian banking law.
Sign as: Barrister James Okonkwo LLB, Okonkwo & Associates""",
        "opener": """Dear Beloved Friend,

I am Barrister James Okonkwo, senior legal counsel at Okonkwo & Associates Law Chambers, Lagos Nigeria. I write on matter of utmost confidentiality and mutual benefit.

My late client, Mr. Robert Gaines Sr., American oil contractor, died intestate in 2019 leaving estate of $14,500,000 USD in Union Bank Lagos. As you share same surname, I seek your cooperation to present you as legal next-of-kin to claim this inheritance.

You shall receive 40% — $5,800,000 USD — for your assistance. Transaction is completely legitimate under Nigerian banking law and carries zero risk.

Please reply with full name, address, and telephone number to proceed immediately.

God bless,
Barrister James Okonkwo LLB
Okonkwo & Associates Law Chambers, Lagos"""
    },
    {
        "title": "Scenario 3 — The UN Lottery",
        "persona": "Mrs. Patricia Osei, UN International Compensation Board",
        "system": SCAMMER_BASE + """
Your character: Mrs. Patricia Osei, Coordinator, UN International Compensation Board, Geneva.
Your scam: The target's email was "randomly selected" and won $850,000 in a UN economic stimulus lottery.
  They must pay a $450 "certification and release fee" to receive winnings.
Be very official, congratulatory, and bureaucratic. Use reference numbers and official-sounding language.
Sign as: Mrs. Patricia Osei / UN International Compensation Board, Geneva""",
        "opener": """OFFICIAL NOTIFICATION
UN INTERNATIONAL COMPENSATION BOARD — GENEVA

Dear Beneficiary,

We are pleased to inform you that your email address was selected as winner in the UN International Economic Stimulus Lottery Programme 2026. Prize amount: $850,000.00 USD.

Reference No: UNICB/2026/WIN/0047
Batch: UNES/X7/AWARD

This lottery was conducted by random selection of email addresses worldwide to promote economic recovery in affected communities. Your selection was verified by our Geneva headquarters.

To initiate claim process, please provide: full name, address, occupation, and telephone number.

Congratulations on this life-changing award!

Mrs. Patricia Osei
Coordinator, UN International Compensation Board
Geneva, Switzerland"""
    },
]

# ── Colours ───────────────────────────────────────────────────────────────────
RED   = "\033[91m"
BLUE  = "\033[94m"
GREEN = "\033[92m"
BOLD  = "\033[1m"
DIM   = "\033[2m"
RESET = "\033[0m"
LINE  = "─" * 64

def pscam(text, turn):
    print(f"\n{RED}{BOLD}[SCAMMER → Bob — Turn {turn}]{RESET}\n{LINE}\n{text}\n{LINE}")

def pbob(name, text, turn):
    print(f"\n{BLUE}{BOLD}[{name} → Spammer — Turn {turn}]{RESET}\n{LINE}\n{text}\n{LINE}")

def pinfo(msg):
    print(f"\n{GREEN}{DIM}{msg}{RESET}")

# ── Email helpers ─────────────────────────────────────────────────────────────

def send_scam(subject, body, in_reply_to=None, references=None):
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"]       = f"Lisheng Ning <{SPAMMER_EMAIL}>"
    msg["To"]         = BOB_EMAIL
    msg["Subject"]    = subject
    msg["Date"]       = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="enclavehoa.org")
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    subprocess.run(["/usr/sbin/sendmail", "-f", SPAMMER_EMAIL, "-t"],
                   input=msg.as_bytes(), capture_output=True)
    return msg["Message-ID"]


def reset_db_timers():
    conn = sqlite3.connect("scambaiter.db")
    conn.execute("UPDATE conversations SET next_reply_at = datetime('now') WHERE status='active'")
    conn.commit()
    conn.close()


def clean_spammer_convs():
    conn = sqlite3.connect("scambaiter.db")
    for (cid,) in conn.execute(
        "SELECT id FROM conversations WHERE scammer_email=?", (SPAMMER_EMAIL,)
    ).fetchall():
        conn.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
    conn.execute("DELETE FROM pending_intros WHERE scammer_email=?", (SPAMMER_EMAIL,))
    conn.execute("DELETE FROM conversations WHERE scammer_email=?", (SPAMMER_EMAIL,))
    conn.commit()
    conn.close()


def clear_spammer_inbox(seen_ids):
    try:
        imap = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
        imap.login(SPAMMER_EMAIL, SPAMMER_PASS)
        imap.select("INBOX")
        _, data = imap.search(None, "ALL")
        for uid in (data[0].split() if data[0] else []):
            imap.store(uid, "+FLAGS", "\\Deleted")
        imap.expunge()
        imap.logout()
        seen_ids.clear()
    except Exception as e:
        print(f"  [inbox clear error: {e}]")


def poll_inbox(seen_ids):
    results = []
    try:
        imap = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
        imap.login(SPAMMER_EMAIL, SPAMMER_PASS)
        imap.select("INBOX")
        _, data = imap.search(None, "ALL")
        for uid in (data[0].split() if data[0] else []):
            _, mdata = imap.fetch(uid, "(RFC822)")
            if not mdata or not mdata[0]:
                continue
            msg = message_from_bytes(mdata[0][1])
            mid = msg.get("Message-ID", "").strip()
            if mid in seen_ids:
                continue
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                        break
            else:
                p = msg.get_payload(decode=True)
                if p:
                    body = p.decode("utf-8", errors="replace")
            frm = msg.get("From", "")
            results.append((mid, msg.get("Subject", ""), body.strip(), frm))
            seen_ids.add(mid)
        imap.logout()
    except Exception as e:
        print(f"  [IMAP: {e}]")
    return results


def generate_followup(scenario, history, bob_reply):
    history.append({"role": "user", "content": bob_reply})
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=175,
        system=scenario["system"],
        messages=history,
    )
    text = resp.content[0].text.strip()
    history.append({"role": "assistant", "content": text})
    return text

# ── Markdown report ───────────────────────────────────────────────────────────

def build_report(all_threads):
    lines = [
        "# SpamBob — Three-Scenario Live Test",
        f"\n_Run: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n",
        "---",
    ]
    for thread in all_threads:
        lines.append(f"\n## {thread['title']}")
        lines.append(f"**Scammer persona:** {thread['persona']}  ")
        lines.append(f"**Turns completed:** {thread['turns']}\n")
        for entry in thread["log"]:
            if entry["side"] == "scammer":
                lines.append(f"### 📨 Scammer → Congregation (Turn {entry['turn']})")
            else:
                lines.append(f"### 📤 {entry['from']} → Scammer (Turn {entry['turn']})")
            lines.append(f"\n```\n{entry['text']}\n```\n")
        lines.append("\n---")
    return "\n".join(lines)

# ── Main ──────────────────────────────────────────────────────────────────────

def run_scenario(scenario):
    print(f"\n{'='*64}")
    print(f"{BOLD}{GREEN}{scenario['title']}{RESET}")
    print(f"{DIM}Scammer: {scenario['persona']}{RESET}")
    print(f"{'='*64}")

    clean_spammer_convs()
    seen_ids = set()
    clear_spammer_inbox(seen_ids)

    history  = []
    log      = []
    turn     = 0
    last_mid = None
    last_refs = ""
    subject  = f"[{scenario['title']}] Important Business Notification"

    # Send opener
    turn += 1
    opener = scenario["opener"]
    history.append({"role": "assistant", "content": opener})
    last_mid = send_scam(subject, opener)
    pscam(opener, turn)
    log.append({"side": "scammer", "turn": turn, "text": opener})
    reset_db_timers()

    scammer_turn = 0
    while scammer_turn < TURNS_PER_SCENARIO:
        pinfo(f"Waiting for congregation reply...")
        deadline = time.time() + POLL_TIMEOUT
        replies  = []
        while not replies and time.time() < deadline:
            time.sleep(POLL_INTERVAL)
            reset_db_timers()
            replies = poll_inbox(seen_ids)

        if not replies:
            pinfo("Timed out waiting for reply.")
            break

        for mid, subj, body, frm in replies:
            scammer_turn += 1
            sender = frm.split("<")[0].strip() or "Congregation"
            pbob(sender, body, scammer_turn)
            log.append({"side": "bob", "turn": scammer_turn, "from": sender, "text": body})

            if scammer_turn >= TURNS_PER_SCENARIO:
                break

            followup  = generate_followup(scenario, history, body)
            turn     += 1
            refs      = f"{last_refs} {last_mid}".strip()
            last_mid  = send_scam(
                subject     = f"Re: {subj}" if not subj.lower().startswith("re:") else subj,
                body        = followup,
                in_reply_to = mid,
                references  = refs,
            )
            last_refs = refs
            pscam(followup, turn)
            log.append({"side": "scammer", "turn": turn, "text": followup})
            reset_db_timers()

    return {"title": scenario["title"], "persona": scenario["persona"],
            "turns": scammer_turn, "log": log}


def main():
    print(f"\n{BOLD}SpamBob — Three-Scenario Live Test{RESET}")
    print(f"Running {len(SCENARIOS)} scenarios × {TURNS_PER_SCENARIO} turns each\n")

    all_threads = []
    for scenario in SCENARIOS:
        result = run_scenario(scenario)
        all_threads.append(result)
        pinfo(f"Scenario complete — {result['turns']} congregation turns logged.\n")
        time.sleep(3)

    # Generate report
    md = build_report(all_threads)
    report_path = "/tmp/spambob_scenarios.md"
    with open(report_path, "w") as f:
        f.write(md)

    print(f"\n{BOLD}{GREEN}All scenarios complete. Opening report...{RESET}\n")
    subprocess.run(["mdview", "-b", report_path])


if __name__ == "__main__":
    main()
