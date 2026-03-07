# SpamBob 🎣

**SpamBob** is an automated scam-baiting system. It monitors email inboxes for scam emails
and responds using a cast of fictional characters from First Church of Fidelity, Lubbock, TX —
all played by Claude AI. The congregation's job is to keep scammers writing for as long as
possible without ever sending money.

---

## The Congregation

| Persona | Email | Role | Brokerage |
|---|---|---|---|
| **Bob Gaines** | `bob@firstchurchoffidelity.org` | Retired postal worker, widower, original target | ~$127K at Edward Jones |
| **Pastor Dale Worthy** | `pastor@firstchurchoffidelity.org` | Senior pastor, runs a capital campaign | ~$215K at Fidelity |
| **Edna Mae Pickler** | `secretary@firstchurchoffidelity.org` | Church secretary, very chatty | ~$83K at Schwab |
| **Deacon Harold Briggs** | `harold@firstchurchoffidelity.org` | Finance Committee Chair, former wheat farmer | ~$540K at Merrill Lynch |
| **Ruthanne Kowalski** | `ruthanne@firstchurchoffidelity.org` | Ladies' Auxiliary President, 7 grandchildren | ~$91K at Edward Jones |
| **Gary Kowalski** | `gary@firstchurchoffidelity.org` | Ruthanne's suspicious son-in-law, insurance adjuster | ~$38K at TD Ameritrade |
| **Sister Agnes Threadgill** | `agnes@firstchurchoffidelity.org` | Church Treasurer, recovering from hip surgery | ~$156K at Vanguard |

All personas are warm and trusting, enthusiastically excited about every opportunity. They stall
constantly but always snap back with determination and near-miss almost-commits to keep the scammer hooked.

**Scam type routing** — new scams are automatically routed to the best-matched persona:
- Inheritance / legal / barrister → **Pastor Dale**
- Lottery / prize / compensation → **Ruthanne**
- Domain / brand / Chinese registrar → **Harold**
- Romance / loneliness → **Bob**
- Everything else → **Bob** (default)

**Cash pickup / in-person agent requests:** All personas direct couriers to `1205 Texas Ave,
Lubbock, TX 79401 / (806) 765-8571` — the FBI Resident Agency. They have no idea.

---

## Architecture

```
Scam email arrives
       │
       ▼
Postfix (MTA) → SpamAssassin tags it → Sieve filter routes it
       │
       ├─ Auto-detected scam → Scambaiter folder (bob@firstchurchoffidelity.org)
       │
       └─ Manually forwarded by any *hasting* address → Scambaiter folder
              (bot detects trusted forwarder, extracts real scammer address)
       │
       ▼
scambaiter.py polls all 7 persona IMAP inboxes every CHECK_INTERVAL seconds
       │
       ▼
New email → route_scam_to_persona() picks best match → Claude Haiku generates reply
       │
       ├─ Reply sent via local sendmail (no SMTP auth needed)
       ├─ Conversation saved to scambaiter.db (SQLite)
       ├─ After REFERRAL_AFTER_TURNS turns → spawns a second persona (cross-pollination)
       └─ Daily digest emailed to richard@hastingtx.org at DIGEST_HOUR UTC
```

---

## Email Infrastructure

### Domains and Mailboxes

| Domain | Purpose |
|---|---|
| `firstchurchoffidelity.org` | All 7 congregation personas |
| `enclavehoa.org` | `spammer@enclavehoa.org` — test/simulation sender |

**Dovecot virtual users:** `/etc/dovecot/virtual-users`
Format: `email:{SHA512-CRYPT}hash:5000:5000::/var/mail/vhosts/domain/mailbox::`

All mailbox passwords: `bogusemail`

**Maildirs:** `/var/mail/vhosts/<domain>/<mailbox>/Maildir/`

### Trusted Forwarders

Any email where the sender address contains `hasting` is treated as a manual forward from
richard. The bot extracts the real scammer address from the forwarded body and opens a
conversation. Additional exact addresses can be added via `TRUSTED_FORWARDERS` in `.env`.

### Sieve Filters

**richard@hastingtx.org** routes scam emails to Bob:
- SpamAssassin `X-Spam-Flag: YES` + scam keyword rules → redirect copy to `bob@firstchurchoffidelity.org`

**bob@firstchurchoffidelity.org** routes to Scambaiter folder:
- From any `*hasting*` address → `Scambaiter/`
- From `spammer@enclavehoa.org` → `Scambaiter/`

Bot watch folders: `Scambaiter`, `INBOX`, `Junk`

### DKIM

`firstchurchoffidelity.org` outbound is DKIM-signed.
Key: `/etc/opendkim/keys/firstchurchoffidelity.org/default.private`

**Required:** `RequireSafeKeys no` in `/etc/opendkim.conf` — do not remove.

---

## Files

| File | Purpose |
|---|---|
| `scambaiter.py` | Main daemon — IMAP poll loop, reply logic, routing, referral spawning, digest trigger |
| `personas.py` | All 7 persona prompts + `build_messages_for()` history builder |
| `database.py` | SQLite ORM — conversations, messages, pending_intros tables |
| `stats.py` | Terminal stats + daily digest email builder/sender |
| `show_convo.py` | Full conversation viewer — terminal or markdown/browser |
| `run_scenarios.py` | Automated 3-scenario test (Claude plays the scammer) |
| `live_test.py` | Interactive test — you type the scammer emails |
| `test_convo.py` | Terminal test — no email, no DB, pure Claude conversation |
| `sieve-setup.py` | Helper to install/compile Sieve filters |
| `scambaiter.service` | systemd unit file |
| `scambaiter.db` | SQLite database (auto-created on first run) |
| `scambaiter.log` | Service log (rotated daily by `/etc/logrotate.d/scambaiter`) |
| `.env` | All secrets and tuning knobs |

---

## Configuration — .env

```ini
# Anthropic
ANTHROPIC_API_KEY=sk-ant-api03-...

# IMAP (Dovecot on localhost)
IMAP_HOST=127.0.0.1
IMAP_PORT=143

# Per-persona IMAP credentials
IMAP_USER_BOB=bob@firstchurchoffidelity.org
IMAP_PASS_BOB=bogusemail
IMAP_USER_PASTOR=pastor@firstchurchoffidelity.org
IMAP_PASS_PASTOR=bogusemail
IMAP_USER_SECRETARY=secretary@firstchurchoffidelity.org
IMAP_PASS_SECRETARY=bogusemail
IMAP_USER_HAROLD=harold@firstchurchoffidelity.org
IMAP_PASS_HAROLD=bogusemail
IMAP_USER_RUTHANNE=ruthanne@firstchurchoffidelity.org
IMAP_PASS_RUTHANNE=bogusemail
IMAP_USER_GARY=gary@firstchurchoffidelity.org
IMAP_PASS_GARY=bogusemail
IMAP_USER_AGNES=agnes@firstchurchoffidelity.org
IMAP_PASS_AGNES=bogusemail

# Folder Sieve routes scam mail into
SCAM_FOLDER=Scambaiter

# Timing (hours) — set all to 0 for testing
FIRST_DELAY_MIN=2
FIRST_DELAY_MAX=8
FOLLOWUP_DELAY_MIN=8
FOLLOWUP_DELAY_MAX=28

# Limits
MAX_TURNS=25
ABANDON_DAYS=14

# Poll interval
CHECK_INTERVAL=600       # seconds (600 = 10 min production, 60 for testing)

# Cross-pollination referrals
REFERRAL_AFTER_TURNS=3
REFERRAL_CHANCE=0.6

# Daily digest
DIGEST_HOUR=7            # UTC hour to send digest to richard@hastingtx.org
```

**Testing mode:** Set all delays to `0`, `CHECK_INTERVAL=60`, `REFERRAL_AFTER_TURNS=1`, `REFERRAL_CHANCE=1.0`

---

## Database Schema

```sql
conversations
  id, persona_key, scammer_email, scammer_name, subject,
  original_message_id, last_inbound_message_id,
  status (active / completed / abandoned),
  turn_count, created_at, last_activity_at, next_reply_at

messages
  id, conversation_id, direction (inbound / outbound),
  subject, content, message_id, timestamp

pending_intros
  id, conversation_id, persona_key, scammer_email,
  subject, body, send_after, sent, sent_message_id
```

`pending_intros` is the referral queue. When Bob refers the scammer to Pastor Dale,
an intro email from Dale is generated, queued here, and sent after a random human-like delay.

---

## Service Management

```bash
# Status
sudo systemctl status scambaiter

# Start / Stop / Restart
sudo systemctl restart scambaiter

# Enable on boot
sudo systemctl enable scambaiter

# Live logs
tail -f /home/richard/projects/SpamBob/scambaiter.log

# Log rotation: daily, 14 days, configured in /etc/logrotate.d/scambaiter
```

---

## Stats and Conversation Viewing

```bash
# Terminal stats summary
python3 stats.py

# Preview daily digest email
python3 stats.py digest

# Send digest now
python3 stats.py digest --send

# Full thread for a specific message ID
python3 stats.py thread <id>

# List all active conversations
python3 show_convo.py

# List all conversations including completed/abandoned
python3 show_convo.py --all

# Show full thread with a scammer
python3 show_convo.py scammer@example.com

# Open thread as markdown in browser
python3 show_convo.py --md scammer@example.com
```

---

## Testing

### Pure conversation test (no email, no DB)
```bash
python3 test_convo.py                    # pick persona, you type scam emails
python3 test_convo.py --persona bob
python3 test_convo.py --auto --turns 6
```

### Live email test (you control the scammer)
```bash
# Set delays to 0 in .env first
python3 live_test.py
```

### Automated 3-scenario test
```bash
# Set delays to 0, CHECK_INTERVAL=60 in .env first
python3 -u run_scenarios.py
# Scenarios: Chinese Domain Squatter, Nigerian Inheritance, UN Lottery
```

### Manually forwarding a scam to Bob
Forward any scam email from any address containing `hasting` to `bob@firstchurchoffidelity.org`.
The bot detects it as a trusted forward, extracts the real scammer address, and starts a conversation.

---

## How Replies Are Generated

`personas.py → build_messages_for()` builds the Claude message list:

1. History older than the last 2 exchanges is summarised into one line.
2. Last 2 exchanges sent verbatim.
3. Instruction appended: keep under 180 words, include a near-miss almost-commit obstacle, end with an eager question.

**Model:** `claude-haiku-4-5-20251001`
**max_tokens:** 200 (persona replies), 200 (referral intros)

---

## Cross-Pollination (Referral Chains)

```
bob       → pastor, ruthanne
pastor    → harold, secretary
secretary → pastor, ruthanne
harold    → ruthanne, agnes
ruthanne  → pastor, harold, gary
gary      → harold, agnes
agnes     → pastor, harold
```

---

## Persona Design Philosophy

Two-part formula every email follows:

1. **Near-miss almost-commit** — describe getting tantalizingly close before something mundane goes wrong.
   *"I had the wire form filled out and my coat on, then the car wouldn't start."*
   *"I got all the way to the bank teller window, had my checkbook out — system was down."*

2. **Snap back with determination** — after every stall, return enthusiasm.
   *"But I am NOT giving up on this. Come heck or high water."*

Every email should leave the scammer thinking: *one more reply and we have them.*

---

## Known Issues

- **Haiku breaks character** playing the scammer in `run_scenarios.py` (UN Lottery scenario especially).
  Bob handles it gracefully — assumes the scammer's account got hacked.

- **REFERRAL_CHANCE=1.0 in testing** — set back to `0.6` for production.
