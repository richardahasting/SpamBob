#!/bin/bash
# Final install step — enable and start the scambaiter service.
# Run this once after filling in your IMAP password in .env

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Enabling and starting scambaiter..."
sudo systemctl enable scambaiter
sudo systemctl start scambaiter
sudo systemctl status scambaiter --no-pager

echo ""
echo "Verify SpamAssassin picked up custom rules:"
sudo spamassassin --lint 2>&1 | grep -i "local_scam\|error\|warn" || echo "  (no warnings — rules loaded cleanly)"

touch "$SCRIPT_DIR/runme.complete"
echo ""
echo "Done. Bob is on duty."
