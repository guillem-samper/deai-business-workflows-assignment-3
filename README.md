# Research Paper Pipeline

An Apache Airflow workflow that scans a locally synchronized Google Drive folder for new PDF papers, converts them to Markdown, extracts metadata with a locally served LLM, stores records in SQLite, generates a searchable static HTML library, and sends a Discord notification.

The DAG is in `dags/paper_pipeline_dag.py`. The processing code is in
`src/paper_pipeline/`.

## Requirements

- Python 3.13 and [uv](https://docs.astral.sh/uv/getting-started/installation/).
- An OpenAI-compatible LLM service (e.g., LM Studio) reachable from the Airflow processes
- A Google Drive folder accessible through the local filesystem.
- A Discord webhook URL if notifications are enabled.

Run the terminal commands below from the repository root.

## Setup

### 1. Install the dependencies

```bash
uv sync --frozen
```

This creates a `.venv` virtual environment and installs the dependencies, including Airflow and the `paper_pipeline` package used by the DAG.

### 2. Set up the environment variables

Create a file called `.env` in the repository root. Set `PROJECT_ROOT` to the
absolute path printed by `pwd`, then fill in the model and webhook settings.

```dotenv
PROJECT_ROOT=/absolute/path/to/this/repository

# These are local directories for testing
# Replace them with your Google Drive synced directories
PAPERS_GOOGLE_DRIVE_FOLDER_PATH=${PROJECT_ROOT}/data/dev/ResearchLibrary/papers
OUTPUTS_GOOGLE_DRIVE_FOLDER_PATH=${PROJECT_ROOT}/data/dev/ResearchLibrary/output

DATABASE_URL=${PROJECT_ROOT}/data/dev/papers.db
MARKDOWN_EXTRACTIONS_FOLDER=${PROJECT_ROOT}/data/dev/markdown
SYSTEM_PROMPTS_FILE_PATH=${PROJECT_ROOT}/prompts/prompts.yaml

# Set based on your local LLM, where it is hosted and its name
LOCAL_LLM_URL=http://localhost:1234/v1
LLM_MODEL_NAME=google/gemma-4-e2b
# Maximum paper text sent to the model; 0 sends the full text
LLM_MAX_INPUT_CHARS=16000

# Leave blank for manual runs. Set to @daily for the scheduled workflow.
PAPER_PIPELINE_SCHEDULE=@daily

# Set to false to disable Discord; otherwise fill in the webhook URL
DISCORD_NOTIFICATIONS_ENABLED=true
PRODUCTION_DISCORD_WEBHOOK_URL=your_webhook
```

The `${PROJECT_ROOT}` references are expanded by `python-dotenv`. Use absolute
paths so the Airflow processes can find the same files.

The example starts with a local test library. Create its directories:

```bash
mkdir -p data/dev/ResearchLibrary/papers data/dev/ResearchLibrary/output data/dev/markdown
```

`DATABASE_URL` is a SQLite file path, despite its name. Its parent directory must
exist; Airflow creates the database and table on the first run.

### 3. Start LM Studio (or another local LLM server)

We used `google/gemma-4-e2b`, but any other model is fine if it support structured JSON responses.
1. Open LM Studio and download the model if needed.
2. Load it, then open the Developer tab and start the server.
3. Check the server's port and list the available model IDs:

   ```bash
   curl -fsS http://localhost:1234/v1/models
   ```

4. Set `LOCAL_LLM_URL` to the server's base URL, including `/v1`, and set
   `LLM_MODEL_NAME` to the exact ID returned for your chosen model.

Keep the model server running while processing papers.

### 4. Connect the Google Drive folders

The paths in the example `.env` are ordinary local directories. Replace
`PAPERS_GOOGLE_DRIVE_FOLDER_PATH` and `OUTPUTS_GOOGLE_DRIVE_FOLDER_PATH` with the
actual mounted or synchronized paths. Keep `DATABASE_URL` outside the Drive folder.

### 5. Set up Discord

Choose a Discord channel and copy its URL into
`PRODUCTION_DISCORD_WEBHOOK_URL` in `.env`.

For a run without Discord, set `DISCORD_NOTIFICATIONS_ENABLED=false`. Papers
processed while it is disabled stay pending and will be notified when it is
enabled again.

## Run the pipeline

Put a PDF in the configured `papers/` folder, ensure the local LLM is ready, then run:

```bash
export AIRFLOW_HOME="$PWD/airflow"
export AIRFLOW__CORE__DAGS_FOLDER="$PWD/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES=False
uv run --frozen airflow standalone
```

Keep the terminal open. Open [localhost:8080](http://localhost:8080) and log in as
`admin` with the generated password shown in the terminal. On later starts, the
password is available in:

```bash
cat "$PWD/airflow/simple_auth_manager_passwords.json.generated"
```

Find `paper_pipeline`, unpause it, and trigger a run.

With `PAPER_PIPELINE_SCHEDULE=@daily` runs are automatic. To enable manual scheduling, set
`PAPER_PIPELINE_SCHEDULE=` and keep the DAG unpaused. If the setting is
absent, the code also defaults to `@daily`.

Restart Airflow after editing `.env`. Stop it with **Ctrl+C**.

## Check the result

Open the run in Airflow and inspect its task logs. After a successful run:

- Markdown files are in `MARKDOWN_EXTRACTIONS_FOLDER`.
- Metadata is in `papers_table` in the database at `DATABASE_URL`.
- The catalog is `<OUTPUTS_GOOGLE_DRIVE_FOLDER_PATH>/index.html`.
- If notifications are enabled and papers are pending, Discord receives a
  message with their count. Failed deliveries stay pending for later runs.
