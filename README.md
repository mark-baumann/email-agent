# Agents From Scratch 

The repo is a guide to building agents from scratch. It builds up to an ["ambient"](https://blog.langchain.dev/introducing-ambient-agents/) agent that can manage your email with connection to the Gmail API. It's grouped into 4 sections, each with a notebook and accompanying code in the `src/email_assistant` directory. These section build from the basics of agents, to agent evaluation, to human-in-the-loop, and finally to memory. These all come together in an agent that you can deploy, and the principles can be applied to other agents across a wide range of tasks. 

![overview](notebooks/img/overview.png)

## Environment Setup 

### Python Version

* Ensure you're using Python 3.11 or later. 
* This version is required for optimal compatibility with LangGraph. 

```shell
python3 --version
```

### API Keys

* If you don't have an OpenAI API key, you can sign up [here](https://openai.com/index/openai-api/).
* Sign up for LangSmith [here](https://smith.langchain.com/).
* Generate a LangSmith API key.

### Set Environment Variables

* Create a `.env` file in the root directory:
```shell
# Copy the .env.example file to .env
cp .env.example .env
```

* Edit the `.env` file with the following:
```shell
LANGSMITH_API_KEY=your_langsmith_api_key
LANGSMITH_TRACING=true
LANGSMITH_PROJECT="interrupt-workshop"
OPENAI_API_KEY=your_openai_api_key
```

* You can also set the environment variables in your terminal:
```shell
export LANGSMITH_API_KEY=your_langsmith_api_key
export LANGSMITH_TRACING=true
export OPENAI_API_KEY=your_openai_api_key
```

### Package Installation

**Recommended: Using uv (faster and more reliable)**

```shell
# Install uv if you haven't already
pip install uv

# Install the package with development dependencies
uv sync --extra dev

# Activate the virtual environment
source .venv/bin/activate
```

**Alternative: Using pip**

```shell
$ python3 -m venv .venv
$ source .venv/bin/activate
# Ensure you have a recent version of pip (required for editable installs with pyproject.toml)
$ python3 -m pip install --upgrade pip
# Install the package in editable mode
$ pip install -e .
```

> **⚠️ IMPORTANT**: Do not skip the package installation step! This editable install is **required** for the notebooks to work correctly. The package is installed as `interrupt_workshop` with import name `email_assistant`, allowing you to import from anywhere with `from email_assistant import ...`

## Structure 

The repo is organized into the 4 sections, with a notebook for each and accompanying code in the `src/email_assistant` directory.

### Preface: LangGraph 101
For a brief introduction to LangGraph and some of the concepts used in this repo, see the [LangGraph 101 notebook](notebooks/langgraph_101.ipynb). This notebook explains the basics of chat models, tool calling, agents vs workflows, LangGraph nodes / edges / memory, and LangGraph Studio.

### Building an agent 
* Notebook: [notebooks/agent.ipynb](/notebooks/agent.ipynb)
* Code: [src/email_assistant/email_assistant.py](/src/email_assistant/email_assistant.py)

![overview-agent](notebooks/img/overview_agent.png)

This notebook shows how to build the email assistant, combining an [email triage step](https://langchain-ai.github.io/langgraph/tutorials/workflows/) with an agent that handles the email response. You can see the linked code for the full implementation in `src/email_assistant/email_assistant.py`.

![Screenshot 2025-04-04 at 4 06 18 PM](notebooks/img/studio.png)

### Evaluation 
* Notebook: [notebooks/evaluation.ipynb](/notebooks/evaluation.ipynb)

![overview-eval](notebooks/img/overview_eval.png)

This notebook introduces evaluation with an email dataset in [eval/email_dataset.py](/eval/email_dataset.py). It shows how to run evaluations using Pytest and the LangSmith `evaluate` API. It runs evaluation for emails responses using LLM-as-a-judge as well as evaluations for tools calls and triage decisions.

![Screenshot 2025-04-08 at 8 07 48 PM](notebooks/img/eval.png)

### Human-in-the-loop 
* Notebook: [notebooks/hitl.ipynb](/notebooks/hitl.ipynb)
* Code: [src/email_assistant/email_assistant_hitl.py](/src/email_assistant/email_assistant_hitl.py)

![overview-hitl](notebooks/img/overview_hitl.png)

This notebooks shows how to add human-in-the-loop (HITL), allowing the user to review specific tool calls (e.g., send email, schedule meeting). For this, we use [Agent Inbox](https://github.com/langchain-ai/agent-inbox) as an interface for human in the loop. You can see the linked code for the full implementation in [src/email_assistant/email_assistant_hitl.py](/src/email_assistant/email_assistant_hitl.py).

![Agent Inbox showing email threads](notebooks/img/agent-inbox.png)

### Memory  
* Notebook: [notebooks/memory.ipynb](/notebooks/memory.ipynb)
* Code: [src/email_assistant/email_assistant_hitl_memory.py](/src/email_assistant/email_assistant_hitl_memory.py)

![overview-memory](notebooks/img/overview_memory.png)  

This notebook shows how to add memory to the email assistant, allowing it to learn from user feedback and adapt to preferences over time. The memory-enabled assistant ([email_assistant_hitl_memory.py](/src/email_assistant/email_assistant_hitl_memory.py)) uses the [LangGraph Store](https://langchain-ai.github.io/langgraph/concepts/memory/#long-term-memory) to persist memories. You can see the linked code for the full implementation in [src/email_assistant/email_assistant_hitl_memory.py](/src/email_assistant/email_assistant_hitl_memory.py).

## Connecting to APIs  

The above notebooks using mock email and calendar tools. 

### Gmail Integration and Deployment

Set up Google API credentials following the instructions in [Gmail Tools README](src/email_assistant/tools/gmail/README.md).

The README also explains how to deploy the graph to LangGraph Platform.

The full implementation of the Gmail integration is in [src/email_assistant/email_assistant_hitl_memory_gmail.py](/src/email_assistant/email_assistant_hitl_memory_gmail.py).

### IMAP/SMTP Integration (one.com and other providers)

To connect a regular IMAP/SMTP mailbox (e.g. a one.com account) instead of Gmail, follow the instructions in the [IMAP Tools README](src/email_assistant/tools/imap/README.md). No OAuth setup is required — only your email address, password, and server settings in `.env`.

The full implementation of the IMAP integration is in [src/email_assistant/email_assistant_hitl_memory_imap.py](/src/email_assistant/email_assistant_hitl_memory_imap.py).

## Lokale Postfach-Oberfläche

Für den Dauerbetrieb unter `email-agent.markb.de`:
[Windows-Anleitung](deploy/windows/README.md) oder
[Raspberry Pi](deploy/pi/README.md).
Die UI bietet pro E-Mail einen Input-Export als YAML und kopierbares JSON für
LangSmith Studio (unter „Input für LangSmith / Studio“).

Die eigene Oberfläche verbindet sich mit dem IMAP-Assistenten und benötigt keinen
LangSmith-Key. Zugangsdaten bleiben in `.env` auf dem Rechner.

Zum Starten beider Dienste und Öffnen des Browsers reicht im Projektordner:

```powershell
.\Start-Inbox.cmd
```

Alternativ kann `Start-Inbox.cmd` per Doppelklick gestartet werden. Die
PowerShell-Ausführungsrichtlinie wird nur für diesen Starter-Prozess gesetzt;
die Systemeinstellungen bleiben erhalten.

Der Starter verwendet bereits laufende Dienste. Neue Dienste laufen im
Hintergrund; ihre Prozessnummern werden ausgegeben, Logs liegen in `.inbox-logs`.
`Stop-Process -Id <Prozessnummer>` beendet einen so gestarteten Dienst.

Alternativ starte im Projektordner in zwei PowerShell-Terminals:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\langgraph.exe dev --config langgraph.imap.json --no-browser
```

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m email_assistant.inbox
```

Öffne **http://127.0.0.1:8080**. Während die Oberfläche läuft, ruft sie alle
30 Sekunden ungelesene Mails der letzten 24 Stunden ab. Der Abruf läuft auch bei
geschlossenem Browser weiter, solange der Python-Prozess läuft. Eigene Testmails
können in der Seitenleiste eingeschaltet werden. Die Ansicht aktualisiert sich
alle fünf Sekunden und zeigt bis zu 100 Threads.

Bereits importierte Nachrichten werden anhand ihrer Message-ID erkannt; jeder
neue Eingang erhält einen eigenen Vorgang. Die lokale Importliste liegt in
`.local-inbox.sqlite3`. Auch Automatik und Testmodus bleiben nach einem Neustart
erhalten. Beim allerersten Start ist die Automatik an und der Testmodus aus.

Antworten und Termine warten auf **Freigeben & senden** bzw. **Einladung senden**.
Entwürfe können vorher bearbeitet oder mit Feedback zurückgegeben werden.
Die Oberfläche ist nur lokal gebunden. Für die ausführliche Fehlersuche steht
weiterhin der Studio-Link zur Verfügung.

Prüfung ohne echte E-Mails oder Modellaufrufe:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_inbox.py -q
```

## Running Tests

The repository includes an automated test suite to evaluate the email assistant. 

Tests verify correct tool usage and response quality using LangSmith for tracking.

### Running Tests with [run_all_tests.py](/tests/run_all_tests.py)

```shell
python tests/run_all_tests.py
```

### Test Results

Test results are logged to LangSmith under the project name specified in your `.env` file (`LANGSMITH_PROJECT`). This provides:
- Visual inspection of agent traces
- Detailed evaluation metrics
- Comparison of different agent implementations

### Available Test Implementations

The available implementations for testing are:
- `email_assistant` - Basic email assistant

### Testing Notebooks

You can also run tests to verify all notebooks execute without errors:

```shell
# Run all notebook tests
python tests/test_notebooks.py

# Or run via pytest
pytest tests/test_notebooks.py -v
```

## Future Extensions

Add [LangMem](https://langchain-ai.github.io/langmem/) to manage memories:
* Manage a collection of background memories. 
* Add memory tools that can look up facts in the background memories. 



