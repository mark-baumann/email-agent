"""
IMAP/SMTP tools implementation module.

This module connects the email assistant to any standard IMAP/SMTP provider
(e.g. one.com) instead of the Gmail API. Emails are fetched over IMAP and
replies are sent over SMTP. The functions are exposed as LangChain tools so
they can be used interchangeably with the Gmail tools.

Configuration is read from environment variables (see load_imap_config):
    EMAIL_ADDRESS   - your full email address (e.g. kontakt@markb.de)
    EMAIL_PASSWORD  - your mailbox password
    IMAP_HOST       - IMAP server (default: imap.one.com)
    IMAP_PORT       - IMAP SSL port (default: 993)
    SMTP_HOST       - SMTP server (default: send.one.com)
    SMTP_PORT       - SMTP port (default: 465)
    SMTP_STARTTLS   - "true" to use STARTTLS (port 587) instead of SSL
    IMAP_MAILBOX    - mailbox/folder to read (default: INBOX)
    IMAP_SENT_MAILBOX - folder to store sent replies (default: Sent)
"""

import email
import email.utils
import imaplib
import logging
import os
import smtplib
import ssl
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Iterator, List, Optional

from dotenv import load_dotenv
from langchain_core.tools import tool
from pydantic import BaseModel, Field

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# IMAP requires English month abbreviations regardless of system locale
_IMAP_MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


@dataclass
class ImapConfig:
    """Connection settings for an IMAP/SMTP account."""

    email_address: str
    password: str
    imap_host: str = "imap.one.com"
    imap_port: int = 993
    smtp_host: str = "send.one.com"
    smtp_port: int = 465
    smtp_starttls: bool = False
    mailbox: str = "INBOX"
    sent_mailbox: str = "Sent"


def load_imap_config() -> ImapConfig:
    """Load IMAP/SMTP configuration from environment variables.

    Raises:
        ValueError: If EMAIL_ADDRESS or EMAIL_PASSWORD is not set.
    """
    email_address = os.getenv("EMAIL_ADDRESS", "").strip()
    password = os.getenv("EMAIL_PASSWORD", "").strip()

    if not email_address or not password:
        raise ValueError(
            "EMAIL_ADDRESS and EMAIL_PASSWORD must be set in the environment "
            "(or in your .env file) to connect to your IMAP account."
        )

    return ImapConfig(
        email_address=email_address,
        password=password,
        imap_host=os.getenv("IMAP_HOST", "imap.one.com"),
        imap_port=int(os.getenv("IMAP_PORT", "993")),
        smtp_host=os.getenv("SMTP_HOST", "send.one.com"),
        smtp_port=int(os.getenv("SMTP_PORT", "465")),
        smtp_starttls=os.getenv("SMTP_STARTTLS", "false").lower() in ("1", "true", "yes"),
        mailbox=os.getenv("IMAP_MAILBOX", "INBOX"),
        sent_mailbox=os.getenv("IMAP_SENT_MAILBOX", "Sent"),
    )


def connect_imap(config: Optional[ImapConfig] = None) -> imaplib.IMAP4_SSL:
    """Open an authenticated IMAP connection."""
    config = config or load_imap_config()
    conn = imaplib.IMAP4_SSL(config.imap_host, config.imap_port)
    conn.login(config.email_address, config.password)
    return conn


def _decode_header_value(value: Optional[str]) -> str:
    """Decode a possibly RFC 2047 encoded header into a readable string."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def extract_message_body(msg: Message) -> str:
    """Extract the body from an email.message.Message.

    Prefers text/plain parts and falls back to text/html.
    """

    def _decode_part(part: Message) -> str:
        payload = part.get_payload(decode=True)
        if payload is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except LookupError:
            return payload.decode("utf-8", errors="replace")

    if not msg.is_multipart():
        return _decode_part(msg)

    plain_parts: List[str] = []
    html_parts: List[str] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        content_type = part.get_content_type()
        disposition = str(part.get("Content-Disposition", ""))
        if "attachment" in disposition.lower():
            continue
        if content_type == "text/plain":
            plain_parts.append(_decode_part(part))
        elif content_type == "text/html":
            html_parts.append(_decode_part(part))

    if plain_parts:
        return "\n".join(plain_parts)
    if html_parts:
        return "\n".join(html_parts)
    return ""


def _parse_message(raw_bytes: bytes, uid: str) -> Dict[str, Any]:
    """Parse a raw RFC822 message into the email data dict used by the agent."""
    msg = email.message_from_bytes(raw_bytes)

    from_email = _decode_header_value(msg.get("From"))
    to_email = _decode_header_value(msg.get("To"))
    subject = _decode_header_value(msg.get("Subject")) or "No Subject"

    # Use Reply-To header if present (matches Gmail tool behavior)
    reply_to = _decode_header_value(msg.get("Reply-To")).strip()
    if reply_to:
        from_email = reply_to

    message_id = (msg.get("Message-ID") or "").strip() or f"uid:{uid}"

    # Determine a stable thread id: the first message id in References,
    # falling back to In-Reply-To, then to this message's own id.
    references = (msg.get("References") or "").split()
    in_reply_to = (msg.get("In-Reply-To") or "").strip()
    if references:
        thread_id = references[0]
    elif in_reply_to:
        thread_id = in_reply_to
    else:
        thread_id = message_id

    # Parse the send time from the Date header
    date_header = msg.get("Date")
    parsed_time = None
    if date_header:
        try:
            parsed_time = email.utils.parsedate_to_datetime(date_header)
        except (TypeError, ValueError):
            parsed_time = None
    if parsed_time is None:
        parsed_time = datetime.now(timezone.utc)

    return {
        "from_email": from_email,
        "to_email": to_email,
        "subject": subject,
        "page_content": extract_message_body(msg),
        "id": message_id,
        "thread_id": thread_id,
        "send_time": parsed_time.isoformat(),
        "_send_time_dt": parsed_time,
        "_uid": uid,
    }


def fetch_group_emails(
    email_address: Optional[str] = None,
    minutes_since: int = 30,
    include_read: bool = False,
    skip_filters: bool = False,
    config: Optional[ImapConfig] = None,
) -> Iterator[Dict[str, Any]]:
    """Fetch recent emails from the IMAP inbox.

    Args:
        email_address: Email address of the account owner. Defaults to the
            configured EMAIL_ADDRESS.
        minutes_since: Only retrieve emails newer than this many minutes.
        include_read: Whether to include already read (seen) emails.
        skip_filters: If True, also yield emails sent by the user themselves
            as regular messages instead of user_respond markers.
        config: Optional explicit ImapConfig (mainly for testing).

    Yields:
        Dict objects containing processed email information, in the same
        format as the Gmail implementation:
        {from_email, to_email, subject, page_content, id, thread_id, send_time}
    """
    config = config or load_imap_config()
    email_address = email_address or config.email_address

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes_since)

    conn = connect_imap(config)
    try:
        status, _ = conn.select(config.mailbox, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Could not select mailbox {config.mailbox!r}")

        # IMAP SINCE has day granularity; filter down to the minute afterwards
        since_str = f"{cutoff.day:02d}-{_IMAP_MONTHS[cutoff.month - 1]}-{cutoff.year}"
        criteria = ["SINCE", since_str]
        if not include_read:
            criteria.insert(0, "UNSEEN")
        logger.info(f"IMAP search criteria: {' '.join(criteria)}")

        status, data = conn.uid("SEARCH", None, *criteria)
        if status != "OK":
            raise RuntimeError(f"IMAP search failed: {data}")

        uids = data[0].split() if data and data[0] else []
        logger.info(f"Found {len(uids)} messages matching search")

        count = 0
        for uid_bytes in uids:
            uid = uid_bytes.decode()
            try:
                # BODY.PEEK[] fetches the message without marking it as read
                status, msg_data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
                if status != "OK" or not msg_data or msg_data[0] is None:
                    logger.warning(f"Failed to fetch message UID {uid}")
                    continue

                raw_bytes = msg_data[0][1]
                email_data = _parse_message(raw_bytes, uid)

                # Enforce the minutes_since cutoff at minute granularity
                send_time = email_data.pop("_send_time_dt")
                if send_time.tzinfo is None:
                    send_time = send_time.replace(tzinfo=timezone.utc)
                if send_time < cutoff:
                    logger.debug(f"Skipping UID {uid}: older than cutoff")
                    continue

                email_data.pop("_uid", None)

                # If the message was sent by the user themselves, mark it as
                # a user response instead of asking the agent to reply to it
                if email_address.lower() in email_data["from_email"].lower():
                    if skip_filters:
                        yield email_data
                    else:
                        yield {
                            "id": email_data["id"],
                            "thread_id": email_data["thread_id"],
                            "user_respond": True,
                        }
                    continue

                yield email_data
                count += 1

            except Exception as e:
                logger.warning(f"Failed to process message UID {uid}: {str(e)}")

        logger.info(f"Found {count} emails to process out of {len(uids)} total messages.")
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _find_uid_by_message_id(conn: imaplib.IMAP4_SSL, message_id: str) -> Optional[str]:
    """Find the IMAP UID for a given Message-ID (or 'uid:<n>' fallback id)."""
    if message_id.startswith("uid:"):
        return message_id[len("uid:"):]
    status, data = conn.uid("SEARCH", None, "HEADER", "Message-ID", message_id)
    if status == "OK" and data and data[0]:
        return data[0].split()[0].decode()
    return None


def _fetch_message_by_id(
    conn: imaplib.IMAP4_SSL, message_id: str
) -> Optional[Message]:
    """Fetch a full message by Message-ID from the selected mailbox."""
    uid = _find_uid_by_message_id(conn, message_id)
    if not uid:
        return None
    status, msg_data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
    if status != "OK" or not msg_data or msg_data[0] is None:
        return None
    return email.message_from_bytes(msg_data[0][1])


def mark_as_read(message_id: str, config: Optional[ImapConfig] = None) -> bool:
    """Mark a message as read (\\Seen) via IMAP.

    Args:
        message_id: The Message-ID header of the email (as returned by
            fetch_group_emails) or a 'uid:<n>' fallback identifier.
        config: Optional explicit ImapConfig.

    Returns:
        True if the message was found and marked as read.
    """
    config = config or load_imap_config()
    conn = connect_imap(config)
    try:
        status, _ = conn.select(config.mailbox)
        if status != "OK":
            logger.error(f"Could not select mailbox {config.mailbox!r}")
            return False
        uid = _find_uid_by_message_id(conn, message_id)
        if not uid:
            logger.warning(f"Could not find message with ID {message_id}")
            return False
        conn.uid("STORE", uid, "+FLAGS", "(\\Seen)")
        logger.info(f"Marked message {message_id} (UID {uid}) as read")
        return True
    except Exception as e:
        logger.error(f"Error marking message as read: {str(e)}")
        return False
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _send_via_smtp(msg: Message, config: ImapConfig, recipients: List[str]) -> None:
    """Send a fully constructed message over SMTP."""
    context = ssl.create_default_context()
    if config.smtp_starttls:
        with smtplib.SMTP(config.smtp_host, config.smtp_port) as server:
            server.starttls(context=context)
            server.login(config.email_address, config.password)
            server.sendmail(config.email_address, recipients, msg.as_string())
    else:
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, context=context) as server:
            server.login(config.email_address, config.password)
            server.sendmail(config.email_address, recipients, msg.as_string())


def _append_to_sent(msg: Message, config: ImapConfig) -> None:
    """Store a copy of the sent message in the Sent folder (best effort)."""
    try:
        conn = connect_imap(config)
        try:
            for folder in (config.sent_mailbox, "Sent", "INBOX.Sent", "Sent Items"):
                status, _ = conn.append(
                    folder,
                    "(\\Seen)",
                    imaplib.Time2Internaldate(datetime.now().timestamp()),
                    msg.as_bytes(),
                )
                if status == "OK":
                    logger.info(f"Stored copy of sent message in {folder!r}")
                    return
            logger.warning("Could not find a Sent folder to store the message copy")
        finally:
            conn.logout()
    except Exception as e:
        logger.warning(f"Could not store message in Sent folder: {str(e)}")


def send_email(
    email_id: str,
    response_text: str,
    email_address: Optional[str] = None,
    addn_receipients: Optional[List[str]] = None,
) -> bool:
    """Send a reply to an existing email thread or create a new email.

    Args:
        email_id: Message-ID of the email to reply to (from fetch_group_emails).
            If it can't be found (e.g. when creating a new email), a new
            message is created instead of a reply.
        response_text: Content of the reply or new email.
        email_address: Sender address; defaults to the configured account.
        addn_receipients: Optional additional recipients (added as Cc).

    Returns:
        True if the email was sent.
    """
    try:
        config = load_imap_config()
        email_address = email_address or config.email_address

        original: Optional[Message] = None
        if email_id and email_id != "NEW_EMAIL":
            conn = connect_imap(config)
            try:
                status, _ = conn.select(config.mailbox, readonly=True)
                if status == "OK":
                    original = _fetch_message_by_id(conn, email_id)
            finally:
                try:
                    conn.logout()
                except Exception:
                    pass

        if original is not None:
            subject = _decode_header_value(original.get("Subject")) or "Response"
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"
            reply_to = _decode_header_value(original.get("Reply-To")).strip()
            to_addr = reply_to or _decode_header_value(original.get("From"))
            original_msg_id = (original.get("Message-ID") or "").strip()
            references = (original.get("References") or "").strip()
        else:
            logger.warning(f"Could not retrieve original message with ID {email_id}")
            subject = "Response"
            to_addr = ""
            original_msg_id = ""
            references = ""

        msg = MIMEText(response_text, "plain", "utf-8")
        msg["From"] = email_address
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg["Message-ID"] = email.utils.make_msgid(domain=email_address.split("@")[-1])
        if original_msg_id:
            msg["In-Reply-To"] = original_msg_id
            msg["References"] = f"{references} {original_msg_id}".strip()
        if addn_receipients:
            msg["Cc"] = ", ".join(addn_receipients)

        recipients = [addr for addr in [to_addr] if addr] + (addn_receipients or [])
        if not recipients:
            logger.error("No recipients found for the email")
            return False

        _send_via_smtp(msg, config, recipients)
        _append_to_sent(msg, config)

        logger.info(f"Email sent to {', '.join(recipients)}: {subject}")
        return True

    except Exception as e:
        logger.error(f"Error sending email: {str(e)}")
        return False


class FetchEmailsInput(BaseModel):
    """Input schema for the fetch_emails_tool."""

    email_address: str = Field(
        description="Email address to fetch emails for"
    )
    minutes_since: int = Field(
        default=30,
        description="Only retrieve emails newer than this many minutes"
    )


@tool(args_schema=FetchEmailsInput)
def fetch_emails_tool(email_address: str, minutes_since: int = 30) -> str:
    """
    Fetches recent emails from the IMAP inbox for the specified email address.

    Args:
        email_address: Email address to fetch messages for
        minutes_since: Only retrieve emails newer than this many minutes (default: 30)

    Returns:
        String summary of fetched emails
    """
    try:
        emails = list(fetch_group_emails(email_address, minutes_since))
    except Exception as e:
        return f"Failed to fetch emails: {str(e)}"

    if not emails:
        return "No new emails found."

    result = f"Found {len(emails)} new emails:\n\n"

    for i, email_data in enumerate(emails, 1):
        if email_data.get("user_respond", False):
            result += f"{i}. You already responded to this email (Thread ID: {email_data['thread_id']})\n\n"
            continue

        result += f"{i}. From: {email_data['from_email']}\n"
        result += f"   To: {email_data['to_email']}\n"
        result += f"   Subject: {email_data['subject']}\n"
        result += f"   Time: {email_data['send_time']}\n"
        result += f"   ID: {email_data['id']}\n"
        result += f"   Thread ID: {email_data['thread_id']}\n"
        result += f"   Content: {email_data['page_content'][:200]}...\n\n"

    return result


class SendEmailInput(BaseModel):
    """Input schema for the send_email_tool."""

    email_id: str = Field(
        description="Message-ID of the email to reply to. This must be a valid Message-ID obtained from the fetch_emails_tool. If you're creating a new email (not replying), use the string 'NEW_EMAIL'."
    )
    response_text: str = Field(
        description="Content of the reply"
    )
    email_address: str = Field(
        description="Current user's email address"
    )
    additional_recipients: Optional[List[str]] = Field(
        default=None,
        description="Optional additional recipients to include"
    )


@tool(args_schema=SendEmailInput)
def send_email_tool(
    email_id: str,
    response_text: str,
    email_address: str,
    additional_recipients: Optional[List[str]] = None
) -> str:
    """
    Send a reply to an existing email thread (or a new email) via SMTP.

    Args:
        email_id: Message-ID of the email to reply to, obtained from the fetch_emails_tool.
                 If creating a new email rather than replying, use the string "NEW_EMAIL".
        response_text: Content of the reply or new email
        email_address: Current user's email address (the sender)
        additional_recipients: Optional additional recipients to include

    Returns:
        Confirmation message
    """
    try:
        success = send_email(
            email_id,
            response_text,
            email_address,
            addn_receipients=additional_recipients
        )
        if success:
            return f"Email reply sent successfully to message ID: {email_id}"
        else:
            return "Failed to send email due to an SMTP/IMAP error"
    except Exception as e:
        return f"Failed to send email: {str(e)}"


class CheckCalendarInput(BaseModel):
    """Input schema for the check_calendar_tool."""

    dates: List[str] = Field(
        description="List of dates to check in DD-MM-YYYY format"
    )


@tool(args_schema=CheckCalendarInput)
def check_calendar_tool(dates: List[str]) -> str:
    """
    Check calendar availability for specific dates.

    Note: plain IMAP/SMTP accounts (like one.com mailboxes) do not expose a
    calendar API, so this returns full availability during working hours.
    Meeting invites are still sent as real iCalendar emails.

    Args:
        dates: List of dates to check in DD-MM-YYYY format

    Returns:
        Formatted calendar availability for the specified dates
    """
    result = "Calendar events:\n\n"
    for date_str in dates:
        result += f"Events for {date_str}:\n"
        result += "  No connected calendar backend for this IMAP account.\n"
        result += "  Assume availability during working hours: 9:00 AM - 5:00 PM\n\n"
    return result


class ScheduleMeetingInput(BaseModel):
    """Input schema for the schedule_meeting_tool."""

    attendees: List[str] = Field(
        description="Email addresses of meeting attendees"
    )
    title: str = Field(
        description="Meeting title/subject"
    )
    start_time: str = Field(
        description="Meeting start time in ISO format (YYYY-MM-DDTHH:MM:SS)"
    )
    end_time: str = Field(
        description="Meeting end time in ISO format (YYYY-MM-DDTHH:MM:SS)"
    )
    organizer_email: str = Field(
        description="Email address of the meeting organizer"
    )
    timezone: str = Field(
        default="Europe/Berlin",
        description="Timezone for the meeting"
    )


def send_calendar_invite(
    attendees: List[str],
    title: str,
    start_time: str,
    end_time: str,
    organizer_email: Optional[str] = None,
    timezone_name: str = "Europe/Berlin",
) -> bool:
    """Send a meeting invite as an iCalendar (.ics) email via SMTP.

    Args:
        attendees: Email addresses of meeting attendees
        title: Meeting title/subject
        start_time: Meeting start time in ISO format (YYYY-MM-DDTHH:MM:SS)
        end_time: Meeting end time in ISO format (YYYY-MM-DDTHH:MM:SS)
        organizer_email: Email address of the organizer; defaults to the account
        timezone_name: IANA timezone name for the meeting times

    Returns:
        True if the invite was sent.
    """
    try:
        from zoneinfo import ZoneInfo

        config = load_imap_config()
        organizer_email = organizer_email or config.email_address

        tz = ZoneInfo(timezone_name)
        start_dt = datetime.fromisoformat(start_time).replace(tzinfo=tz)
        end_dt = datetime.fromisoformat(end_time).replace(tzinfo=tz)

        fmt = "%Y%m%dT%H%M%SZ"
        start_utc = start_dt.astimezone(timezone.utc).strftime(fmt)
        end_utc = end_dt.astimezone(timezone.utc).strftime(fmt)
        now_utc = datetime.now(timezone.utc).strftime(fmt)
        event_uid = f"{uuid.uuid4()}@{organizer_email.split('@')[-1]}"

        attendee_lines = "\n".join(
            f"ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{a}"
            for a in attendees
        )
        ics_content = f"""BEGIN:VCALENDAR
PRODID:-//email-assistant//EN
VERSION:2.0
METHOD:REQUEST
BEGIN:VEVENT
UID:{event_uid}
DTSTAMP:{now_utc}
DTSTART:{start_utc}
DTEND:{end_utc}
SUMMARY:{title}
ORGANIZER;CN={organizer_email}:mailto:{organizer_email}
{attendee_lines}
STATUS:CONFIRMED
SEQUENCE:0
END:VEVENT
END:VCALENDAR
"""

        msg = MIMEMultipart("mixed")
        msg["From"] = organizer_email
        msg["To"] = ", ".join(attendees)
        msg["Subject"] = f"Invitation: {title}"
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg["Message-ID"] = email.utils.make_msgid(domain=organizer_email.split("@")[-1])

        body = (
            f"You have been invited to: {title}\n"
            f"Start: {start_dt.isoformat()}\n"
            f"End: {end_dt.isoformat()}\n"
        )
        msg.attach(MIMEText(body, "plain", "utf-8"))

        ics_part = MIMEText(ics_content, "calendar", "utf-8")
        ics_part.set_param("method", "REQUEST")
        ics_part.add_header("Content-Disposition", "attachment", filename="invite.ics")
        msg.attach(ics_part)

        _send_via_smtp(msg, config, list(attendees))
        _append_to_sent(msg, config)

        logger.info(f"Calendar invite sent for '{title}' to {', '.join(attendees)}")
        return True

    except Exception as e:
        logger.error(f"Error sending calendar invite: {str(e)}")
        return False


@tool(args_schema=ScheduleMeetingInput)
def schedule_meeting_tool(
    attendees: List[str],
    title: str,
    start_time: str,
    end_time: str,
    organizer_email: str,
    timezone: str = "Europe/Berlin"
) -> str:
    """
    Schedule a meeting by sending an iCalendar invite email to all attendees.

    Args:
        attendees: Email addresses of meeting attendees
        title: Meeting title/subject
        start_time: Meeting start time in ISO format (YYYY-MM-DDTHH:MM:SS)
        end_time: Meeting end time in ISO format (YYYY-MM-DDTHH:MM:SS)
        organizer_email: Email address of the meeting organizer
        timezone: IANA timezone name for the meeting (default: Europe/Berlin)

    Returns:
        Success or failure message
    """
    try:
        success = send_calendar_invite(
            attendees,
            title,
            start_time,
            end_time,
            organizer_email,
            timezone_name=timezone,
        )
        if success:
            return f"Meeting '{title}' scheduled successfully from {start_time} to {end_time} with {len(attendees)} attendees"
        else:
            return "Failed to schedule meeting"
    except Exception as e:
        return f"Error scheduling meeting: {str(e)}"
