#!/usr/bin/env python
"""
Quick connection test for the IMAP/SMTP integration.

Verifies that the configured account (e.g. one.com) can log in via IMAP and
SMTP and lists the most recent unread emails.

Usage:
    python src/email_assistant/tools/imap/test_connection.py
"""

import smtplib
import ssl
import sys

from dotenv import load_dotenv

from email_assistant.tools.imap.imap_tools import (
    connect_imap,
    fetch_group_emails,
    load_imap_config,
)

load_dotenv()


def main() -> int:
    """Test IMAP and SMTP connectivity and show recent unread emails."""
    try:
        config = load_imap_config()
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        return 1

    print(f"Account: {config.email_address}")
    print(f"IMAP:    {config.imap_host}:{config.imap_port} (SSL)")
    print(f"SMTP:    {config.smtp_host}:{config.smtp_port} "
          f"({'STARTTLS' if config.smtp_starttls else 'SSL'})")
    print()

    # Test IMAP login
    try:
        conn = connect_imap(config)
        status, mailboxes = conn.list()
        print("✅ IMAP login successful")
        if status == "OK":
            print(f"   Found {len(mailboxes)} mailboxes")
        conn.logout()
    except Exception as e:
        print(f"❌ IMAP login failed: {e}")
        return 1

    # Test SMTP login
    try:
        context = ssl.create_default_context()
        if config.smtp_starttls:
            with smtplib.SMTP(config.smtp_host, config.smtp_port) as server:
                server.starttls(context=context)
                server.login(config.email_address, config.password)
        else:
            with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, context=context) as server:
                server.login(config.email_address, config.password)
        print("✅ SMTP login successful")
    except Exception as e:
        print(f"❌ SMTP login failed: {e}")
        return 1

    # Show recent unread emails (last 24h)
    print("\nUnread emails from the last 24 hours:")
    count = 0
    for email_data in fetch_group_emails(minutes_since=24 * 60, config=config):
        if email_data.get("user_respond"):
            continue
        count += 1
        print(f"  {count}. {email_data['from_email']} — {email_data['subject']}")
        if count >= 10:
            print("  ... (showing first 10)")
            break
    if count == 0:
        print("  (none)")

    print("\n✅ Connection test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
