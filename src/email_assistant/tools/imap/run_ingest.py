#!/usr/bin/env python
"""
IMAP ingestion script for the email assistant.

Fetches unread emails from an IMAP account (e.g. one.com) and ingests them
into a running LangGraph server, mirroring the Gmail ingestion script.

Usage:
    python src/email_assistant/tools/imap/run_ingest.py --minutes-since 120

Requires EMAIL_ADDRESS / EMAIL_PASSWORD (and optionally IMAP_HOST etc.)
in the environment or a .env file.
"""

import argparse
import asyncio
import hashlib
import uuid

from dotenv import load_dotenv
from langgraph_sdk import get_client

from email_assistant.tools.imap.imap_tools import fetch_group_emails, load_imap_config

load_dotenv()


async def ingest_email_to_langgraph(email_data, graph_name, url="http://127.0.0.1:2024"):
    """Ingest an email to LangGraph."""
    # Connect to LangGraph server
    client = get_client(url=url)

    # Create a consistent UUID for the thread
    raw_thread_id = email_data["thread_id"]
    thread_id = str(
        uuid.UUID(hex=hashlib.md5(raw_thread_id.encode("UTF-8")).hexdigest())
    )
    print(f"IMAP thread ID: {raw_thread_id} → LangGraph thread ID: {thread_id}")

    thread_exists = False
    try:
        # Try to get existing thread info
        await client.threads.get(thread_id)
        thread_exists = True
        print(f"Found existing thread: {thread_id}")
    except Exception:
        # If thread doesn't exist, create it
        print(f"Creating new thread: {thread_id}")
        await client.threads.create(thread_id=thread_id)

    # If thread exists, clean up previous runs
    if thread_exists:
        try:
            runs = await client.runs.list(thread_id)
            for run_info in runs:
                run_id = run_info.id
                print(f"Deleting previous run {run_id} from thread {thread_id}")
                try:
                    await client.runs.delete(thread_id, run_id)
                except Exception as e:
                    print(f"Failed to delete run {run_id}: {str(e)}")
        except Exception as e:
            print(f"Error listing/deleting runs: {str(e)}")

    # Update thread metadata with current email ID
    await client.threads.update(thread_id, metadata={"email_id": email_data["id"]})

    # Create a fresh run for this email
    print(f"Creating run for thread {thread_id} with graph {graph_name}")

    run = await client.runs.create(
        thread_id,
        graph_name,
        input={"email_input": {
            "from": email_data["from_email"],
            "to": email_data["to_email"],
            "subject": email_data["subject"],
            "body": email_data["page_content"],
            "id": email_data["id"]
        }},
        multitask_strategy="rollback",
    )

    print(f"Run created successfully with thread ID: {thread_id}")

    return thread_id, run


async def fetch_and_process_emails(args):
    """Fetch emails via IMAP and process them through LangGraph."""
    config = load_imap_config()
    email_address = args.email or config.email_address

    print(f"Fetching emails for {email_address} from {config.imap_host}")

    processed_count = 0
    try:
        emails = list(fetch_group_emails(
            email_address,
            minutes_since=args.minutes_since,
            include_read=args.include_read,
            skip_filters=args.skip_filters,
        ))

        if not emails:
            print("No emails found matching the criteria")
            return 0

        print(f"Found {len(emails)} emails")

        for i, email_data in enumerate(emails):
            # Stop early if requested
            if args.early and i > 0:
                print(f"Early stop after processing {i} emails")
                break

            if email_data.get("user_respond", False):
                print(f"Skipping email {email_data['id']}: sent by the user")
                continue

            print(f"\nProcessing email {i + 1}/{len(emails)}:")
            print(f"From: {email_data['from_email']}")
            print(f"Subject: {email_data['subject']}")

            await ingest_email_to_langgraph(
                email_data,
                args.graph_name,
                url=args.url
            )

            processed_count += 1

        print(f"\nProcessed {processed_count} emails successfully")
        return 0

    except Exception as e:
        print(f"Error processing emails: {str(e)}")
        return 1


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="IMAP ingestion for LangGraph")

    parser.add_argument(
        "--email",
        type=str,
        default=None,
        help="Email address to fetch messages for (default: EMAIL_ADDRESS from env)"
    )
    parser.add_argument(
        "--minutes-since",
        type=int,
        default=120,
        help="Only retrieve emails newer than this many minutes"
    )
    parser.add_argument(
        "--graph-name",
        type=str,
        default="email_assistant_hitl_memory_imap",
        help="Name of the LangGraph to use"
    )
    parser.add_argument(
        "--url",
        type=str,
        default="http://127.0.0.1:2024",
        help="URL of the LangGraph deployment"
    )
    parser.add_argument(
        "--early",
        action="store_true",
        help="Early stop after processing one email"
    )
    parser.add_argument(
        "--include-read",
        action="store_true",
        help="Include emails that have already been read"
    )
    parser.add_argument(
        "--skip-filters",
        action="store_true",
        help="Skip filtering of emails sent by the user themselves"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    exit(asyncio.run(fetch_and_process_emails(args)))
