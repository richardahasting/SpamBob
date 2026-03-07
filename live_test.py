#!/usr/bin/env python3
"""
Live end-to-end test: Claude plays the spammer via real email.

Sends from spammer@enclavehoa.org -> bob@firstchurchoffidelity.org.
The scambaiter service handles Bob's side. This script polls the spammer's
inbox for replies, generates follow-ups with Claude, and shows everything live.
"""

import imaplib
import os
import subprocess
import sys
import time
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
MAX_TURNS     = 8
POLL_INTERVAL = 10  # seconds between inbox checks

SCAMMER_SYSTEM = """You are a Chinese domain registrar scammer running a classic brand-squatting scam.
You contacted someone claiming another company wants to register their brand name as Chinese domains.
Your goal is to get them to pay a "brand protection" fee of $500-$2000 USD.

Each reply should:
- Escalate slightly — more urgency, mention fees, deadlines
- React to whatever they said (confused elderly person = perfect target, be more encouraging)
- Keep it 80-120 words
- Sound like broken but professional English from a Chinese business
- Sign as: Lisheng Ning, Asia Registry Corp."""

client  = Anthropic()
history = []  # (role, text) pairs for Claude scammer context

DIVIDER       = "─" * 62
SCAM_COLOR    = "\033[91m"
PERSONA_COLOR = "\033[94m"
RESET         = "\033[0m"
BOLD          = "\033[1m"


def send_email(subject: str, body: str, in_reply_to: str = None, references: str = None) -> str:
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

    proc = subprocess.run(
        ["/usr/sbin/sendmail", "-f", SPAMMER_EMAIL, "-t"],
        input=msg.as_bytes(), capture_output=True,
    )
    if proc.returncode != 0:
        print(f"sendmail error: {proc.stderr.decode()}")
    return msg["Message-ID"]


def poll_inbox(seen_ids: set) -> list[tuple[str, str, str]]:
    """Return list of (message_id, subject, body) for new messages."""
    results = []
    try:
        imap = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
        imap.login(SPAMMER_EMAIL, SPAMMER_PASS)
        imap.select("INBOX")
        _, data = imap.search(None, "ALL")
        for uid in (data[0].split() if data[0] else []):
            _, msg_data = imap.fetch(uid, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            msg    = message_from_bytes(msg_data[0][1])
            mid    = msg.get("Message-ID", "").strip()
            if mid in seen_ids:
                continue
            subj   = msg.get("Subject", "")
            body   = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                        break
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="replace")
            results.append((mid, subj, body.strip()))
            seen_ids.add(mid)
        imap.logout()
    except Exception as e:
        print(f"  [IMAP error: {e}]")
    return results


def generate_scammer_reply(bob_reply: str) -> str:
    history.append({"role": "user", "content": bob_reply})
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=250,
        system=SCAMMER_SYSTEM,
        messages=history,
    )
    text = response.content[0].text.strip()
    history.append({"role": "assistant", "content": text})
    return text


def print_scammer(text: str, turn: int) -> None:
    print(f"\n{SCAM_COLOR}{BOLD}[SPAMMER → Bob — Turn {turn}]{RESET}")
    print(DIVIDER)
    print(text)
    print(DIVIDER)


def print_bob(name: str, text: str, turn: int) -> None:
    print(f"\n{PERSONA_COLOR}{BOLD}[{name} → Spammer — Turn {turn}]{RESET}")
    print(DIVIDER)
    print(text)
    print(DIVIDER)


def main():
    print(f"\n{BOLD}SpamBob Live Test{RESET}")
    print(f"Spammer: {SPAMMER_EMAIL}")
    print(f"Target:  {BOB_EMAIL}")
    print(f"Polling every {POLL_INTERVAL}s for replies...\n")

    seen_ids      = set()
    turn          = 0
    last_msg_id   = None
    last_refs     = ""

    # Opening scam email — you write it
    print(f"{SCAM_COLOR}{BOLD}Write your opening scam email (blank line + Enter to send):{RESET}")
    lines = []
    while True:
        line = input()
        if line == "" and lines and lines[-1] == "":
            break
        lines.append(line)
    opener = "\n".join(lines).strip()

    turn += 1
    subject    = "Concern Regarding enclavecanyonlake — Chinese Domain Registration"
    last_msg_id = send_email(subject, opener)
    print_scammer(opener, turn)
    print(f"\n{BOLD}[Email sent. Waiting for Bob...]{RESET}\n")

    bob_turn = 0
    while bob_turn < MAX_TURNS:
        time.sleep(POLL_INTERVAL)
        replies = poll_inbox(seen_ids)

        for mid, subj, body in replies:
            bob_turn += 1
            sender_name = "Bob / Congregation"
            print_bob(sender_name, body, bob_turn)

            if bob_turn >= MAX_TURNS:
                print(f"\n{BOLD}[Max turns reached — test complete]{RESET}\n")
                return

            # You play the scammer
            print(f"\n{SCAM_COLOR}{BOLD}Your reply as the scammer (blank line + Enter to send):{RESET}")
            lines = []
            while True:
                line = input()
                if line == "" and lines and lines[-1] == "":
                    break
                lines.append(line)
            follow_up = "\n".join(lines).strip()
            if not follow_up:
                print("  [Empty reply — skipping]")
                continue
            turn       += 1
            refs        = f"{last_refs} {last_msg_id}".strip() if last_msg_id else ""
            last_msg_id = send_email(
                subject     = f"Re: {subj}" if not subj.lower().startswith("re:") else subj,
                body        = follow_up,
                in_reply_to = mid,
                references  = refs,
            )
            last_refs = refs
            print_scammer(follow_up, turn)
            print(f"\n{BOLD}[Reply sent. Waiting for response...]{RESET}\n")


if __name__ == "__main__":
    main()
