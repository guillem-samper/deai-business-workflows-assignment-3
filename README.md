# Research Paper Pipeline

An Apache Airflow pipeline that scans a locally synchronized Google Drive
folder for new PDF papers, converts them to Markdown, extracts metadata with an
OpenAI-compatible LLM, saves the metadata to SQLite, generates a static HTML
library, and sends a Discord notification.

The pipeline reads PDFs from a **local folder**. It does not authenticate to or
download files from the Google Drive API itself; configure a Drive sync client
separately.

## Requirements

- Python 3.13
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- An OpenAI-compatible LLM service reachable from the Airflow processes
- A synchronized folder containing the PDFs to process
- A Discord webhook for end-to-end runs that add papers

The dependency versions are recorded in `uv.lock`. Keep this file committed so
new installations can recreate the same environment.

## Install

Run these commands from the repository root:

```bash
uv sync --frozen
```

`uv sync` creates `.venv` and installs the project, including Airflow and the
`paper_pipeline` package used by the DAG.

## Configure the pipeline

Create a local `.env` file in the repository root. It is ignored by Git; do not
commit secrets such as webhook URLs.

```dotenv
# Parent directory containing the synchronized "papers" directory.
GOOGLE_DRIVE_FOLDER_PATH=/absolute/path/to/synchronized-drive

# Local SQLite file path, not a SQLAlchemy URL.
DATABASE_URL=/absolute/path/to/repository/database/papers.db

# The YAML file containing the LLM system prompt.
SYSTEM_PROMPTS_FILE_PATH=/absolute/path/to/repository/prompts/prompts.yaml

# Base URL of a reachable OpenAI-compatible LLM service.
LOCAL_LLM_URL=http://localhost:8000/v1

# Optional; defaults to google/gemma-4-e2b.
LLM_MODEL_NAME=your-model-name

# Required for a successful notification when new papers are added.
# Use a test webhook for local development.
PRODUCTION_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Optional; defaults to data/markdown.
MARKDOWN_EXTRACTIONS_FOLDER=/absolute/path/to/repository/data/markdown
```

Replace the example paths and values with your own. Create the parent folder of
the SQLite file before running the DAG, for example:

```bash
mkdir -p database
```

`DATABASE_URL` is named as a URL for historical reasons, but the code passes it
to Python's `sqlite3.connect`; use a filesystem path such as
`/path/to/database/papers.db`, **not** `sqlite:///...`.

Put PDFs in:

```text
<GOOGLE_DRIVE_FOLDER_PATH>/papers/
```

The DAG stores Markdown files in `MARKDOWN_EXTRACTIONS_FOLDER` (default
`data/markdown/`) and writes the generated library to
`<GOOGLE_DRIVE_FOLDER_PATH>/output/index.html`.

The current code uses the synchronized local folder and does not read
`credentials.json` or `token.json`; those files are not needed to run this
pipeline.

## Run Airflow locally

Airflow needs its own metadata database and configuration, separate from the
pipeline's `DATABASE_URL`. Use a repository-local `AIRFLOW_HOME` for development
so Airflow state does not depend on a machine-specific global configuration.
The `airflow*` ignore rule excludes this local directory from Git.

From the repository root, run:

```bash
export AIRFLOW_HOME="$PWD/airflow"
export AIRFLOW__CORE__DAGS_FOLDER="$PWD/dags"
uv run airflow standalone
```

Keep this terminal open while using Airflow. On its first start, Airflow
initializes its local metadata database and prints the generated `admin`
password. Open [http://localhost:8080](http://localhost:8080) and sign in with
that password. If you need it again, it is stored in
`$AIRFLOW_HOME/simple_auth_manager_passwords.json.generated`; do not share or
commit it. Stop the local Airflow services with **Ctrl+C**.

In another terminal, from the repository root, the same Airflow environment
variables must be set to use the same local Airflow home:

```bash
export AIRFLOW_HOME="$PWD/airflow"
export AIRFLOW__CORE__DAGS_FOLDER="$PWD/dags"
uv run airflow dags list
uv run airflow dags list-import-errors
```

Confirm that `paper_pipeline` appears and that there are no import errors. In
the UI, unpause the DAG if it is paused, then trigger a run. It is scheduled
daily; unpausing it enables its schedule as well as manual runs.

## What a DAG run does

1. Creates the `papers_table` SQLite table if necessary.
2. Finds PDF files in the synchronized `papers/` folder that are not already
   recorded in the database.
3. Converts those PDFs to Markdown and requests structured metadata from the
   configured LLM.
4. Saves the extracted metadata to SQLite.
5. Regenerates the static HTML library if papers were added.
6. Sends a Discord notification if papers were added.

For a first test, use a small sample PDF, a disposable SQLite database, and a
test Discord webhook. The webhook is used only when new papers are saved, but
the notification task still needs a valid URL for a successful end-to-end run
that reaches it.

## Development notes

- The LLM helper currently truncates Markdown to 1,000 characters for
  debugging, so metadata from a local run may be based on only the beginning of
  a paper.
- Airflow's `standalone` command is for local development and evaluation, not
  production. A production deployment needs an appropriate Airflow executor
  and persistent metadata database, plus secure management of environment
  variables and secrets.
- Do not use a production Discord webhook or production paper database for
  local testing.