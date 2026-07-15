"""IMAP/SMTP tools for the email assistant (e.g. for one.com accounts)."""

from email_assistant.tools.imap.imap_tools import (
    fetch_emails_tool,
    send_email_tool,
    check_calendar_tool,
    schedule_meeting_tool,
)
from email_assistant.tools.imap.prompt_templates import IMAP_TOOLS_PROMPT

__all__ = [
    "fetch_emails_tool",
    "send_email_tool",
    "check_calendar_tool",
    "schedule_meeting_tool",
    "IMAP_TOOLS_PROMPT",
]
