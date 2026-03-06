#!/bin/bash
# Sets up firstchurchoffidelity.org on this mail server.
# Run AFTER pointing the domain's MX record to mail.hastingtx.org.
#
# What this does:
#   1. Generates a DKIM keypair
#   2. Adds the domain to Postfix virtual domains + mailboxes
#   3. Adds to OpenDKIM key/signing tables
#   4. Creates Dovecot virtual user passwords
#   5. Reloads all services
#   6. Prints DNS records you need to add

set -euo pipefail
DOMAIN="firstchurchoffidelity.org"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "======================================================"
echo "  First Church of Fidelity — mail server setup"
echo "======================================================"

# ── 1. DKIM keypair ───────────────────────────────────────
echo ""
echo "[1/5] Generating DKIM keypair for $DOMAIN..."
sudo mkdir -p /etc/opendkim/keys/$DOMAIN
sudo opendkim-genkey -b 2048 -d $DOMAIN \
    -D /etc/opendkim/keys/$DOMAIN -s mail -v
sudo chown -R opendkim:opendkim /etc/opendkim/keys/$DOMAIN
sudo chmod 600 /etc/opendkim/keys/$DOMAIN/mail.private
echo "  Done."

# ── 2. OpenDKIM tables ────────────────────────────────────
echo ""
echo "[2/5] Updating OpenDKIM tables..."

# Add to key.table if not already present
if ! sudo grep -q "^$DOMAIN " /etc/opendkim/key.table; then
    echo "$DOMAIN $DOMAIN:mail:/etc/opendkim/keys/$DOMAIN/mail.private" \
        | sudo tee -a /etc/opendkim/key.table > /dev/null
fi

# Add to signing.table if not already present
if ! sudo grep -q "@$DOMAIN" /etc/opendkim/signing.table; then
    echo "*@$DOMAIN $DOMAIN" \
        | sudo tee -a /etc/opendkim/signing.table > /dev/null
fi
echo "  Done."

# ── 3. Postfix virtual domain ─────────────────────────────
echo ""
echo "[3/5] Adding $DOMAIN to Postfix..."

DOMAINS_FILE=/etc/postfix/virtual/domains
if ! sudo grep -q "^$DOMAIN " $DOMAINS_FILE; then
    echo "$DOMAIN OK" | sudo tee -a $DOMAINS_FILE > /dev/null
fi

# Add mailboxes
MAILBOXES_FILE=/etc/postfix/virtual/mailboxes
for USER in pastor secretary harold ruthanne info; do
    ADDR="$USER@$DOMAIN"
    MBOX="$DOMAIN/$USER/"
    if ! sudo grep -q "^$ADDR " $MAILBOXES_FILE; then
        echo "$ADDR $MBOX" | sudo tee -a $MAILBOXES_FILE > /dev/null
    fi
done

sudo postmap $DOMAINS_FILE
sudo postmap $MAILBOXES_FILE
echo "  Done."

# ── 4. Dovecot maildir directories ────────────────────────
echo ""
echo "[4/5] Creating Maildir directories..."
VMAIL_BASE=/var/mail/vhosts/$DOMAIN
for USER in pastor secretary harold ruthanne info; do
    sudo mkdir -p $VMAIL_BASE/$USER/{cur,new,tmp}
    sudo mkdir -p $VMAIL_BASE/$USER/.Scambaiter/{cur,new,tmp}
    sudo mkdir -p $VMAIL_BASE/$USER/.Junk/{cur,new,tmp}
done
sudo chown -R 5000:5000 $VMAIL_BASE
echo "  Done."

# ── 5. Dovecot passwords ──────────────────────────────────
echo ""
echo "[5/5] Setting mailbox passwords..."
echo "Enter a password for the church mailboxes (same for all personas):"
read -s -r CHURCH_PASS

PASSWD_FILE=/etc/dovecot/users
for USER in pastor secretary harold ruthanne info; do
    ADDR="$USER@$DOMAIN"
    # Remove existing entry if present
    sudo sed -i "/^$ADDR:/d" $PASSWD_FILE 2>/dev/null || true
    # Generate and append new entry
    HASH=$(doveadm pw -s SHA512-CRYPT -p "$CHURCH_PASS")
    echo "$ADDR:$HASH" | sudo tee -a $PASSWD_FILE > /dev/null
done
echo "  Done."

# ── Reload services ───────────────────────────────────────
echo ""
echo "Reloading services..."
sudo systemctl reload postfix
sudo systemctl restart opendkim
sudo systemctl reload dovecot
echo "  Services reloaded."

# ── Print DNS records ─────────────────────────────────────
echo ""
echo "======================================================"
echo "  DNS RECORDS TO ADD AT YOUR REGISTRAR"
echo "======================================================"
echo ""
echo "  MX record:"
echo "    $DOMAIN.   MX  10  mail.hastingtx.org."
echo ""
echo "  SPF record (TXT on $DOMAIN.):"
echo "    v=spf1 mx a:mail.hastingtx.org ~all"
echo ""
echo "  DMARC record (TXT on _dmarc.$DOMAIN.):"
echo "    v=DMARC1; p=quarantine; rua=mailto:richard@hastingtx.org"
echo ""
echo "  DKIM record (TXT on mail._domainkey.$DOMAIN.):"
DKIM_TXT=$(sudo cat /etc/opendkim/keys/$DOMAIN/mail.txt \
    | grep -o '".*"' | tr -d '"' | tr -d '\n' | tr -d ' ')
echo "    $DKIM_TXT"
echo ""
echo "  (Full mail.txt is at /etc/opendkim/keys/$DOMAIN/mail.txt)"
echo ""
echo "======================================================"
echo "  Now update .env with the church password, then"
echo "  run:  sudo python3 sieve-setup.py"
echo "======================================================"

touch "$SCRIPT_DIR/runme-church-setup.complete"
