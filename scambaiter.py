#!/usr/bin/env python3
"""
Scambaiter — multi-persona scam engagement bot.

Personas are defined in personas.py.  Each has its own IMAP mailbox.
The bot monitors all persona mailboxes, routes incoming scam mail to the
right character, generates Claude replies, and optionally "refers" the
scammer to a second persona after a few turns (cross-pollination).
"""

import imaplib
import logging
import os
import random
import re
import subprocess
import time
from datetime import datetime, timedelta
from email import message_from_bytes
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid, parseaddr
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

import database as db
from personas import PERSONAS, get_persona_by_email, random_referral_persona, build_messages_for

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env")

IMAP_HOST = os.getenv("IMAP_HOST", "127.0.0.1")
IMAP_PORT = int(os.getenv("IMAP_PORT", "143"))

SCAM_FOLDER   = os.getenv("SCAM_FOLDER", "Scambaiter")
WATCH_FOLDERS = [SCAM_FOLDER, "INBOX", "Junk"]

# Timing (hours)
FIRST_DELAY_MIN  = int(os.getenv("FIRST_DELAY_MIN",  "2"))
FIRST_DELAY_MAX  = int(os.getenv("FIRST_DELAY_MAX",  "8"))
FOLLOWUP_DELAY_MIN = int(os.getenv("FOLLOWUP_DELAY_MIN", "8"))
FOLLOWUP_DELAY_MAX = int(os.getenv("FOLLOWUP_DELAY_MAX", "28"))

MAX_TURNS      = int(os.getenv("MAX_TURNS",    "25"))
ABANDON_DAYS   = int(os.getenv("ABANDON_DAYS", "14"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "600"))

# After this many turns, maybe refer a second persona
REFERRAL_AFTER_TURNS = int(os.getenv("REFERRAL_AFTER_TURNS", "3"))
REFERRAL_CHANCE      = float(os.getenv("REFERRAL_CHANCE", "0.6"))  # 60% probability

SCAM_SA_TESTS = [
    "ADVANCE_FEE", "MILLION_USD", "INHERITANCE", "LOTTERY",
    "NIGERIAN", "BENEFICIARY", "MONEY_TRANSFER", "NEXT_OF_KIN",
    "ROMANCE_SCAM", "FROM_NIGERIA", "LOCAL_SCAM",
]

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).parent / "scambaiter.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("scambaiter")

# ── IMAP credentials per persona ──────────────────────────────────────────────

def get_imap_creds(persona_key: str) -> tuple[str, str]:
    """Return (imap_user, imap_pass) from env for a given persona key."""
    user = os.getenv(f"IMAP_USER_{persona_key.upper()}")
    pw   = os.getenv(f"IMAP_PASS_{persona_key.upper()}")
    if not user or not pw:
        raise ValueError(
            f"Missing env vars IMAP_USER_{persona_key.upper()} / IMAP_PASS_{persona_key.upper()}"
        )
    return user, pw


def imap_connect(persona_key: str) -> imaplib.IMAP4:
    user, pw = get_imap_creds(persona_key)
    imap = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
    imap.login(user, pw)
    return imap

# ── Email helpers ─────────────────────────────────────────────────────────────

def extract_text(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                html = part.get_payload(decode=True).decode("utf-8", errors="replace")
                return re.sub(r"<[^>]+>", " ", html).strip()
    else:
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode(charset, errors="replace")
    return ""


def parse_address(header: str) -> tuple[str, str]:
    name, addr = parseaddr(header or "")
    return name.strip(), addr.strip().lower()


def thread_ids(msg) -> list[str]:
    ids = []
    for h in ("References", "In-Reply-To"):
        ids.extend(re.findall(r"<[^>]+>", msg.get(h, "")))
    return ids


def is_scam_email(msg) -> bool:
    if "YES" not in msg.get("X-Spam-Flag", "").upper():
        return False
    status = msg.get("X-Spam-Status", "")
    m = re.search(r"score=([\d.]+)", status)
    if not m or float(m.group(1)) < 8.0:
        return False
    return any(t in status.upper() for t in SCAM_SA_TESTS)


def reply_subject(original: str) -> str:
    s = original.strip()
    return s if s.lower().startswith("re:") else f"Re: {s}"


def random_delay(min_h: int, max_h: int) -> datetime:
    mins = random.randint(min_h * 60, max_h * 60)
    return datetime.utcnow() + timedelta(minutes=mins)


def fetch_unseen(imap: imaplib.IMAP4, folder: str) -> list[tuple[bytes, object]]:
    try:
        status, _ = imap.select(f'"{folder}"')
        if status != "OK":
            return []
    except Exception:
        return []
    _, data = imap.search(None, "UNSEEN")
    uids = data[0].split() if data[0] else []
    results = []
    for uid in uids:
        _, msg_data = imap.fetch(uid, "(RFC822)")
        if msg_data and msg_data[0]:
            results.append((uid, message_from_bytes(msg_data[0][1])))
    return results


def mark_seen(imap: imaplib.IMAP4, uid: bytes) -> None:
    imap.store(uid, "+FLAGS", "\\Seen")


def move_to_folder(imap: imaplib.IMAP4, uid: bytes, dest: str) -> None:
    imap.copy(uid, f'"{dest}"')
    imap.store(uid, "+FLAGS", "\\Deleted")
    imap.expunge()

# ── Claude ────────────────────────────────────────────────────────────────────

def generate_reply(persona_key: str, conversation_id: int, new_email_text: str) -> str:
    from personas import PERSONAS, build_messages_for
    history  = db.get_messages(conversation_id)
    persona  = PERSONAS[persona_key]
    messages = build_messages_for(persona, history, new_email_text)

    client   = Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=persona["system_prompt"],
        messages=messages,
    )
    return response.content[0].text.strip()

# ── Sendmail ──────────────────────────────────────────────────────────────────

def send_email(
    from_persona_key: str,
    to_addr: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str | None:
    from personas import PERSONAS
    persona = PERSONAS[from_persona_key]
    from_addr = persona["email"]
    from_name = persona["display_name"]
    domain    = from_addr.split("@")[1]

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"]       = f"{from_name} <{from_addr}>"
    msg["To"]         = to_addr
    msg["Subject"]    = subject
    msg["Date"]       = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=domain)
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    proc = subprocess.run(
        ["/usr/sbin/sendmail", "-f", from_addr, "-t"],
        input=msg.as_bytes(),
        capture_output=True,
    )
    if proc.returncode != 0:
        log.error("sendmail failed (%s): %s", from_addr, proc.stderr.decode())
        return None

    mid = msg["Message-ID"].strip("<>")
    log.info("%s -> %s  [%s]", from_name, to_addr, mid[:40])
    return mid

# ── Core conversation logic ───────────────────────────────────────────────────

def handle_new_scam(msg, uid, imap, folder, persona_key: str) -> None:
    scammer_name, scammer_email = parse_address(msg.get("From", ""))
    subject    = msg.get("Subject", "(no subject)")
    message_id = msg.get("Message-ID", "").strip().strip("<>")

    if db.find_conversation_by_sender(scammer_email):
        log.info("Already engaged with %s — skipping duplicate", scammer_email)
        mark_seen(imap, uid)
        return

    body       = extract_text(msg)
    next_reply = random_delay(FIRST_DELAY_MIN, FIRST_DELAY_MAX)
    conv_id    = db.create_conversation(
        scammer_email, scammer_name, subject, message_id, next_reply, persona_key
    )
    db.add_message(conv_id, "inbound", subject, body, message_id)
    mark_seen(imap, uid)

    if folder != SCAM_FOLDER:
        move_to_folder(imap, uid, SCAM_FOLDER)

    from personas import PERSONAS
    pname = PERSONAS[persona_key]["display_name"]
    log.info("NEW SCAM  from %-40s  -> %s  (reply ~%s UTC)",
             f"{scammer_name} <{scammer_email}>", pname,
             next_reply.strftime("%Y-%m-%d %H:%M"))


def handle_scammer_reply(conv: dict, msg, uid, imap) -> None:
    body       = extract_text(msg)
    subject    = msg.get("Subject", conv["subject"])
    message_id = msg.get("Message-ID", "").strip().strip("<>")

    if conv["turn_count"] >= MAX_TURNS:
        log.info("Convo %d maxed out — retiring %s", conv["id"], conv["scammer_email"])
        db.mark_complete(conv["id"])
        mark_seen(imap, uid)
        return

    next_reply = random_delay(FOLLOWUP_DELAY_MIN, FOLLOWUP_DELAY_MAX)
    db.add_message(conv["id"], "inbound", subject, body, message_id)
    db.schedule_next_reply(conv["id"], next_reply, message_id)
    mark_seen(imap, uid)

    log.info("REPLY     from %-40s  turn %d, Bob responds ~%s UTC",
             conv["scammer_email"], conv["turn_count"],
             next_reply.strftime("%Y-%m-%d %H:%M"))


def send_pending_replies() -> None:
    for conv in db.get_pending_replies():
        persona_key = conv.get("persona_key", "bob")
        history     = db.get_messages(conv["id"])
        inbound     = [m for m in history if m["direction"] == "inbound"]
        if not inbound:
            continue

        last_in = inbound[-1]
        all_ids = [m["message_id"] for m in history if m["message_id"]]
        refs    = " ".join(f"<{mid}>" for mid in all_ids)

        log.info("Composing reply for %s to %s (turn %d)...",
                 persona_key, conv["scammer_email"], conv["turn_count"])

        try:
            reply_text = generate_reply(persona_key, conv["id"], last_in["content"])
        except Exception as exc:
            log.error("Claude error: %s", exc)
            continue

        subject = reply_subject(conv["subject"])
        in_reply_to = (
            f"<{conv['last_inbound_message_id']}>"
            if conv.get("last_inbound_message_id") else None
        )
        sent_mid = send_email(
            from_persona_key=persona_key,
            to_addr=conv["scammer_email"],
            subject=subject,
            body=reply_text,
            in_reply_to=in_reply_to,
            references=refs,
        )
        if sent_mid:
            db.add_message(conv["id"], "outbound", subject, reply_text, sent_mid)
            db.schedule_next_reply(conv["id"], None)
            log.info("--- %s says ---\n%s\n---",
                     persona_key, reply_text[:400])

            # Cross-pollination: after REFERRAL_AFTER_TURNS, spawn a second persona
            if (conv["turn_count"] == REFERRAL_AFTER_TURNS
                    and random.random() < REFERRAL_CHANCE):
                spawn_referral(conv, persona_key)


def spawn_referral(conv: dict, from_persona_key: str) -> None:
    """Start a new conversation with a second persona for the same scammer."""
    ref_key, ref_persona = random_referral_persona(from_persona_key)
    if not ref_key:
        return
    if db.find_conversation_by_sender_and_persona(conv["scammer_email"], ref_key):
        return  # already engaged this scammer from this persona

    intro_prompt = (
        f"You just received an email from a scammer ({conv['scammer_email']}) "
        f"who was referred to you by your friend/colleague "
        f"{from_persona_key.title()}. "
        f"The original scam is about: {conv['subject']}. "
        f"Write your opening email to this person, expressing interest "
        f"and introducing yourself. Be warm, trusting, and enthusiastic. "
        f"150-200 words. End with a question."
    )

    from anthropic import Anthropic
    client = Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=ref_persona["system_prompt"],
        messages=[{"role": "user", "content": intro_prompt}],
    )
    intro_text = response.content[0].text.strip()

    # Schedule send with extra delay so it feels organic
    send_after = random_delay(4, 16)
    new_conv_id = db.create_conversation(
        conv["scammer_email"],
        conv.get("scammer_name", ""),
        f"Re: {conv['subject']}",
        f"referral-{conv['id']}-{ref_key}",
        send_after,
        ref_key,
    )
    db.add_message(new_conv_id, "outbound", f"Re: {conv['subject']}", intro_text)
    db.set_pending_intro(new_conv_id, intro_text, conv["scammer_email"])

    log.info("REFERRAL  spawning %s to engage %s (sends ~%s UTC)",
             ref_key, conv["scammer_email"], send_after.strftime("%Y-%m-%d %H:%M"))


def scan_persona(persona_key: str) -> None:
    """Scan one persona's IMAP mailboxes for scam mail and scammer replies."""
    try:
        imap = imap_connect(persona_key)
    except Exception as exc:
        log.warning("IMAP login failed for %s: %s", persona_key, exc)
        return

    from personas import PERSONAS
    persona_email = PERSONAS[persona_key]["email"].lower()

    for folder in WATCH_FOLDERS:
        for uid, msg in fetch_unseen(imap, folder):
            _, sender_email = parse_address(msg.get("From", ""))
            if not sender_email or sender_email == persona_email:
                continue

            refs = thread_ids(msg)
            conv = db.find_conversation_by_thread(refs) \
                or db.find_conversation_by_sender(sender_email)

            if conv:
                handle_scammer_reply(conv, msg, uid, imap)
            elif folder == SCAM_FOLDER or is_scam_email(msg):
                handle_new_scam(msg, uid, imap, folder, persona_key)

    imap.logout()


def send_pending_intros() -> None:
    """Send queued referral intro emails."""
    for item in db.get_pending_intros():
        sent_mid = send_email(
            from_persona_key=item["persona_key"],
            to_addr=item["scammer_email"],
            subject=item["subject"],
            body=item["body"],
        )
        if sent_mid:
            db.clear_pending_intro(item["id"], sent_mid)
            log.info("INTRO sent from %s to %s", item["persona_key"], item["scammer_email"])

# ── Main loop ─────────────────────────────────────────────────────────────────

def run() -> None:
    db.init_db()

    active_personas = [
        key for key in PERSONAS
        if os.getenv(f"IMAP_USER_{key.upper()}") and os.getenv(f"IMAP_PASS_{key.upper()}")
    ]
    if not active_personas:
        log.error("No persona IMAP credentials found in .env. Set IMAP_USER_BOB, IMAP_PASS_BOB, etc.")
        return

    log.info("Scambaiter started. Active personas: %s", active_personas)

    while True:
        try:
            for persona_key in active_personas:
                scan_persona(persona_key)

            send_pending_intros()
            send_pending_replies()

            abandoned = db.abandon_stale_conversations(ABANDON_DAYS)
            if abandoned:
                log.info("Abandoned %d stale conversation(s)", abandoned)

            stats = db.get_stats()
            log.info("Stats: %d active | %d total | %d turns wasted",
                     stats["active"], stats["total_conversations"], stats["total_turns_wasted"])

        except KeyboardInterrupt:
            log.info("Shutting down. The congregation is going home.")
            break
        except Exception as exc:
            log.exception("Unexpected error: %s", exc)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    run()
