#!/usr/bin/env python3
"""
Interactive test harness for SpamBob personas.

Usage:
  python test_convo.py                  # You play the scammer, pick a persona
  python test_convo.py --persona bob    # Start with a specific persona
  python test_convo.py --auto           # Claude plays both sides (watch it run)
  python test_convo.py --auto --turns 6 # Auto mode, N turns
"""

import argparse
import os
import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from personas import PERSONAS, build_messages_for

load_dotenv(Path(__file__).parent / ".env")

client = Anthropic()

SCAMMER_SYSTEM = """You are playing the role of a generic email scammer — Nigerian prince style.
You are trying to extract money or personal banking details from your target.
Keep emails 100-150 words. Be urgent, flattering, and vague about details.
Each reply should escalate pressure slightly — ask for more commitment, hint at fees,
request account information. Vary your approach each turn."""

DIVIDER      = "─" * 60
SCAM_COLOR   = "\033[91m"   # red
PERSONA_COLOR = "\033[94m"  # blue
RESET        = "\033[0m"
BOLD         = "\033[1m"


def pick_persona() -> str:
    print(f"\n{BOLD}Available personas:{RESET}")
    keys = list(PERSONAS.keys())
    for i, key in enumerate(keys, 1):
        p = PERSONAS[key]
        print(f"  {i}. {p['display_name']} <{p['email']}>")
    while True:
        choice = input("\nPick a persona (number or name): ").strip().lower()
        if choice in PERSONAS:
            return choice
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(keys):
                return keys[idx]
        except ValueError:
            pass
        print("  Invalid choice, try again.")


def generate_persona_reply(persona_key: str, history: list[dict], scammer_text: str) -> str:
    persona  = PERSONAS[persona_key]
    messages = build_messages_for(persona, history, scammer_text)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=persona["system_prompt"],
        messages=messages,
    )
    return response.content[0].text.strip()


def generate_scammer_reply(history: list[dict], persona_reply: str) -> str:
    # Build scammer's view of the conversation (reversed roles)
    messages = []
    for msg in history:
        if msg["direction"] == "outbound":
            messages.append({"role": "user", "content": msg["content"]})
        else:
            messages.append({"role": "assistant", "content": msg["content"]})
    messages.append({"role": "user", "content": persona_reply})

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=SCAMMER_SYSTEM,
        messages=messages,
    )
    return response.content[0].text.strip()


def print_scammer(text: str, turn: int) -> None:
    print(f"\n{SCAM_COLOR}{BOLD}[SCAMMER — Turn {turn}]{RESET}")
    print(DIVIDER)
    print(text)
    print(DIVIDER)


def print_persona(name: str, text: str, turn: int) -> None:
    print(f"\n{PERSONA_COLOR}{BOLD}[{name} — Turn {turn}]{RESET}")
    print(DIVIDER)
    print(text)
    print(DIVIDER)


def run_interactive(persona_key: str) -> None:
    persona = PERSONAS[persona_key]
    name    = persona["display_name"]
    history: list[dict] = []
    turn = 0

    print(f"\n{BOLD}Playing as: {name} <{persona['email']}>{RESET}")
    print("Type the scammer's email at each prompt. 'quit' to exit.\n")

    # Seed with a classic opener if desired
    seed = input("Paste a scam opener (or press Enter for a sample): ").strip()
    if not seed:
        seed = (
            "Dear Beloved Friend,\n\n"
            "I am Dr. Emmanuel Okafor, legal adviser to the late Mr. James Henderson, "
            "an American citizen who passed away intestate leaving the sum of $14.5 million USD. "
            "As you share the same surname, I am contacting you to stand as next-of-kin. "
            "This transaction is 100% risk free and you shall receive 40% of the total sum. "
            "Please reply urgently with your full name, address, and telephone number.\n\n"
            "God bless,\nDr. Emmanuel Okafor"
        )
        print(f"\n{SCAM_COLOR}[Using sample scam opener]{RESET}\n")

    while True:
        turn += 1
        print_scammer(seed, turn)

        history.append({"direction": "inbound", "content": seed})

        print(f"\n{PERSONA_COLOR}[{name} is thinking...]{RESET}", end="", flush=True)
        reply = generate_persona_reply(persona_key, history[:-1], seed)
        print("\r" + " " * 40 + "\r", end="")

        history.append({"direction": "outbound", "content": reply})
        print_persona(name, reply, turn)

        if input(f"\n{BOLD}Continue? (Enter=yes / q=quit):{RESET} ").strip().lower() in ("q", "quit"):
            break

        next_scam = input(f"\n{SCAM_COLOR}Your reply as scammer:{RESET}\n> ").strip()
        if next_scam.lower() in ("q", "quit"):
            break
        seed = next_scam

    print(f"\n{BOLD}Conversation ended after {turn} turn(s).{RESET}\n")


def run_auto(persona_key: str, max_turns: int) -> None:
    persona = PERSONAS[persona_key]
    name    = persona["display_name"]
    history: list[dict] = []

    print(f"\n{BOLD}AUTO MODE — {name} vs. Claude Scammer — {max_turns} turns{RESET}\n")

    # Opening scam email
    opener_response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=250,
        system=SCAMMER_SYSTEM,
        messages=[{"role": "user", "content": "Write your opening scam email to a random target."}],
    )
    scammer_text = opener_response.content[0].text.strip()

    for turn in range(1, max_turns + 1):
        print_scammer(scammer_text, turn)
        history.append({"direction": "inbound", "content": scammer_text})

        print(f"\n{PERSONA_COLOR}[{name} is composing...]{RESET}", end="", flush=True)
        persona_reply = generate_persona_reply(persona_key, history[:-1], scammer_text)
        print("\r" + " " * 40 + "\r", end="")

        history.append({"direction": "outbound", "content": persona_reply})
        print_persona(name, persona_reply, turn)

        if turn < max_turns:
            input(f"\n{BOLD}[Press Enter for next turn]{RESET}")
            print(f"\n{SCAM_COLOR}[Scammer is composing...]{RESET}", end="", flush=True)
            scammer_text = generate_scammer_reply(history[:-1], persona_reply)
            print("\r" + " " * 40 + "\r", end="")

    print(f"\n{BOLD}Auto-run complete — {max_turns} turns wasted.{RESET}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="SpamBob conversation tester")
    parser.add_argument("--persona", choices=list(PERSONAS.keys()), help="Persona to use")
    parser.add_argument("--auto",    action="store_true", help="Claude plays both sides")
    parser.add_argument("--turns",   type=int, default=5, help="Turns in auto mode (default 5)")
    args = parser.parse_args()

    persona_key = args.persona or pick_persona()

    if args.auto:
        run_auto(persona_key, args.turns)
    else:
        run_interactive(persona_key)


if __name__ == "__main__":
    main()
