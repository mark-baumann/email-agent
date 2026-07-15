"""Tool prompt templates for the IMAP/SMTP integration."""

# IMAP tools prompt for insertion into agent system prompts
IMAP_TOOLS_PROMPT = """
1. fetch_emails_tool(email_address, minutes_since) - Fetch recent emails from the IMAP inbox
2. send_email_tool(email_id, response_text, email_address, additional_recipients) - Send a reply to an email thread via SMTP
3. check_calendar_tool(dates) - Check calendar availability for specific dates
4. schedule_meeting_tool(attendees, title, start_time, end_time, organizer_email, timezone) - Schedule a meeting by sending an iCalendar invite email
5. triage_email(ignore, notify, respond) - Triage emails into one of three categories
6. Done - E-mail has been sent
"""
