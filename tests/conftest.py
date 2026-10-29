#!/usr/bin/env python

import os
import pytest
import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

# Keep the inbox tests independent of a deployed .env: on a machine that serves
# the UI under a domain, INBOX_PASSWORD and INBOX_ALLOWED_HOSTS would otherwise
# turn every test request into 401 or 400. Setting them here wins, because
# load_dotenv() never overrides variables that already exist.
os.environ["INBOX_ALLOWED_HOSTS"] = "127.0.0.1,localhost,testserver"
os.environ["INBOX_PASSWORD"] = ""

def pytest_addoption(parser):
    """Add command-line options to pytest."""
    parser.addoption(
        "--agent-module", 
        action="store", 
        default="email_assistant_hitl_memory",
        help="Specify which email assistant module to test"
    )

@pytest.fixture(scope="session")
def agent_module_name(request):
    """Return the agent module name from command line."""
    return request.config.getoption("--agent-module")