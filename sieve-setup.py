#!/usr/bin/env python3
"""
Install Sieve filters for all church personas.
Run this after runme-church-setup.sh completes.
"""
import subprocess
import sys

CHURCH_PERSONAS = [
    "pastor@firstchurchoffidelity.net",
    "secretary@firstchurchoffidelity.net",
    "harold@firstchurchoffidelity.net",
    "ruthanne@firstchurchoffidelity.net",
]

SIEVE_SCRIPT = """\
require ["fileinto", "mailbox", "imap4flags"];

# ── Scambaiter: high-confidence scam emails ───────────────────────────────────
if allof(
    header :contains "X-Spam-Flag" "YES",
    anyof(
        header :contains "X-Spam-Status" "ADVANCE_FEE",
        header :contains "X-Spam-Status" "MILLION_USD",
        header :contains "X-Spam-Status" "INHERITANCE",
        header :contains "X-Spam-Status" "LOTTERY",
        header :contains "X-Spam-Status" "NIGERIAN",
        header :contains "X-Spam-Status" "BENEFICIARY",
        header :contains "X-Spam-Status" "NEXT_OF_KIN",
        header :contains "X-Spam-Status" "MONEY_TRANSFER",
        header :contains "X-Spam-Status" "ROMANCE_SCAM",
        header :contains "X-Spam-Status" "LOCAL_SCAM"
    )
) {
    fileinto :create "Scambaiter";
    stop;
}

# ── General spam to Junk ──────────────────────────────────────────────────────
if header :contains "X-Spam-Flag" "YES" {
    fileinto :create "Junk";
    stop;
}
"""

def run_doveadm(cmd: list[str]) -> bool:
    result = subprocess.run(
        ["sudo", "doveadm"] + cmd,
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}")
        return False
    return True


def main():
    print("Installing Sieve filters for First Church of Fidelity personas...")
    for email in CHURCH_PERSONAS:
        print(f"\n  {email}")
        # Write sieve script via doveadm
        result = subprocess.run(
            ["sudo", "doveadm", "sieve", "put", "-u", email, "main"],
            input=SIEVE_SCRIPT.encode(),
            capture_output=True,
        )
        if result.returncode != 0:
            print(f"    FAILED: {result.stderr.decode().strip()}")
            continue

        # Activate it
        ok = run_doveadm(["sieve", "activate", "-u", email, "main"])
        if ok:
            print(f"    OK — Sieve filter installed and activated")
        else:
            print(f"    WARNING — install succeeded but activation failed (may already be active)")

    print("\nDone. All church members are on scam watch duty.")


if __name__ == "__main__":
    main()
