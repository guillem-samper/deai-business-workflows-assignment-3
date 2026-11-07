import logging
import os
from pathlib import Path

from airflow.sdk import dag, task
from dotenv import load_dotenv
from pendulum import datetime
from discord_webhook import DiscordWebhook

from paper_pipeline.database import database_inserter, initialize_database
from paper_pipeline.drive import check_drive_folder
from paper_pipeline.parser import converter_pdf_to_markdown, get_llm_response
from paper_pipeline.reporter import generate_static_html

load_dotenv(".env")
logger = logging.getLogger(__name__)


@dag(
    schedule="@daily",
    start_date=datetime(2025, 1, 1),
    description=(
        "Checks for new research papers, extracts metadata, updates the library, "
        "and notifies Discord."
    ),
    tags=["team_a", "source_a"],
    catchup=False,
    max_consecutive_failed_dag_runs=3,
)
def paper_pipeline() -> None:
    """Define the daily workflow for processing new research papers.

    Args:
        None.

    Returns:
        None. The ``@dag`` decorator uses this function to construct the DAG.
    """

    @task
    def init_db() -> None:
        """Initialize the papers database table.

        Args:
            None.

        Returns:
            None.
        """
        logger.info("Initializing the papers database.")
        initialize_database(database_url=os.getenv("DATABASE_URL"))
        logger.info("Papers database initialization complete.")

    @task
    def check_new_papers() -> list[str]:
        """Find unprocessed PDF files in the synchronized papers folder.

        Args:
            None.

        Returns:
            list[str]: Names of new PDF files, including their extensions.
        """
        folder_path = Path(os.environ["GOOGLE_DRIVE_FOLDER_PATH"]) / "papers"
        new_files = check_drive_folder(folder_path=folder_path)
        logger.info("Found %d new paper(s).", len(new_files))
        return new_files

    @task
    def convert_papers_to_text(
        files_to_process: list[str],
    ) -> list[str] | None:
        """Convert new PDF files to Markdown.

        Args:
            files_to_process (list[str]): PDF filenames found by the Drive scan.

        Returns:
            list[str] | None: Generated Markdown file paths, or ``None`` when
            there are no files to convert.
        """
        if not files_to_process:
            logger.info("No new files to process.")
            return

        created_markdown_files = []
        for file_name in files_to_process:
            logger.info("Converting %s to text", file_name)
            full_path = (
                Path(os.getenv("GOOGLE_DRIVE_FOLDER_PATH")) / "papers" / file_name
            )
            output_file_path = converter_pdf_to_markdown(full_path)
            created_markdown_files.append(str(output_file_path))
        logger.info("Created %d Markdown file(s).", len(created_markdown_files))
        return created_markdown_files

    @task
    def call_llm(
        created_markdown_files: list[str],
    ) -> list[dict[str, str | list[str]]] | None:
        """Extract structured metadata from each Markdown file using the LLM.

        Args:
            created_markdown_files (list[str]): Paths to generated Markdown files.

        Returns:
            list[dict[str, str | list[str]]] | None: Paper metadata dictionaries,
            or ``None`` when there are no files to process. Each dictionary
            contains string values and a list of string keywords.
        """
        if not created_markdown_files:
            logger.info("No new files to process for LLM.")
            return

        extracted_paper_metadata = []

        for file_name in created_markdown_files:
            logger.info("Calling LLM for %s", file_name)
            paper_data = get_llm_response(file_name)
            if paper_data:
                extracted_paper_metadata.append(paper_data)

        logger.info(
            "Extracted metadata %s",
            (
                extracted_paper_metadata[0]
                if extracted_paper_metadata
                else "No metadata extracted"
            ),
        )
        logger.info(
            "Extracted metadata for %d of %d paper(s).",
            len(extracted_paper_metadata),
            len(created_markdown_files),
        )

        return extracted_paper_metadata

    @task
    def save_to_db(
        extracted_paper_metadata: list[dict[str, str | list[str]]],
    ) -> int:
        """Insert extracted paper metadata into the database.

        Args:
            extracted_paper_metadata (list[dict[str, str | list[str]]]): Metadata
                records returned by the LLM extraction task.

        Returns:
            int: Number of metadata records submitted for insertion, or ``0``
            when the input is empty.
        """
        if not extracted_paper_metadata:
            logger.info("No new metadata to save to the database.")
            return 0

        logger.info(
            "Saving metadata for %d paper(s) to the database.",
            len(extracted_paper_metadata),
        )

        database_inserter(
            extracted_paper_metadata, database_url=os.getenv("DATABASE_URL")
        )
        logger.info(
            "Saved %d paper(s) to the database.", len(extracted_paper_metadata)
        )
        return len(extracted_paper_metadata)

    @task
    def render_html(number_of_new_papers: int) -> int:
        """Regenerate the static HTML library when new papers were inserted.

        Args:
            number_of_new_papers (int): Number of papers inserted into the database.

        Returns:
            int: The number of new papers when the page is regenerated,
            otherwise ``0``.
        """

        if number_of_new_papers == 0:
            logger.info("No new papers to render in HTML.")
            return 0

        output_html_path = (
            Path(os.getenv("GOOGLE_DRIVE_FOLDER_PATH")) / "output" / "index.html"
        )
        generate_static_html(
            database_url=os.getenv("DATABASE_URL"), output_path=output_html_path
        )
        logger.info("Updated the static paper library at %s.", output_html_path)
        return number_of_new_papers

    @task
    def notify_discord(number_of_new_papers: int) -> None:
        """Send a Discord notification when new papers have been added.

        Args:
            number_of_new_papers (int): Number of papers added during this run.

        Returns:
            None.
        """
        if number_of_new_papers > 0:
            logger.info(
                "Notifying Discord about %d new paper(s).", number_of_new_papers
            )
            webhook_url = os.getenv("PRODUCTION_DISCORD_WEBHOOK_URL")
            webhook = DiscordWebhook(
                url=webhook_url,
                content=(
                    f"{number_of_new_papers} new papers have been added "
                    "to the database!"
                ),
            )
            webhook.execute()
            logger.info("Discord notification sent.")
        else:
            logger.info("No new papers to notify Discord about.")

    # Ensure database initialization completes before scanning Drive.
    db_ready = init_db()
    new_papers = check_new_papers()
    db_ready >> new_papers

    new_markdowns = convert_papers_to_text(new_papers)
    new_papers_metadata = call_llm(new_markdowns)

    saved_count = save_to_db(new_papers_metadata)
    html_updated = render_html(saved_count)
    notify_discord(html_updated)


paper_pipeline()
