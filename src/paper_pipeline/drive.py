"""Discovery of new PDF files in the synchronized Drive folder."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from paper_pipeline.utils.database_utils import create_database_connection

load_dotenv(".env")

logger: logging.Logger = logging.getLogger(__name__)


def check_drive_folder(folder_path: str | Path) -> list[str]:
    """Find PDF files in a synchronized Drive folder that are not in the database.

    Args:
        folder_path (str | Path): Local path to the synchronized Drive folder.

    Returns:
        list[str]: Names of PDF files that are not yet represented in the
        database. The returned filenames include their ``.pdf`` extension.

    Raises:
        FileNotFoundError: If ``folder_path`` does not exist or is not a directory.
    """
    logger.info(
        "Checking synchronized Drive folder for new papers: %s", folder_path
    )

    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(
            f"The specified folder path '{folder_path}' does not exist or is not a"
            " directory."
        )

    pdf_files = [
        file.name
        for file in folder.iterdir()
        if file.is_file() and file.suffix.lower() == ".pdf"
    ]
    if not pdf_files:
        logger.info("No PDF files found in folder: %s", folder_path)
        return []

    logger.debug("Found %d PDF file(s) in %s.", len(pdf_files), folder_path)
    database_target = os.getenv("DATABASE_URL")
    cursor, conn = create_database_connection(database_url=database_target)
    try:
        sql_statement = "SELECT filename FROM papers_table"
        cursor.execute(sql_statement)
        present_files_clean = {
            row[0].strip().lower() for row in cursor.fetchall() if row[0]
        }
        logger.debug(
            "Files already present in the database: %s", present_files_clean
        )
    finally:
        conn.close()

    new_files = []
    for file in pdf_files:
        stem_name = (
            file[:-4] if file.lower().endswith(".pdf") else file
        ).strip().lower()
        if stem_name not in present_files_clean:
            new_files.append(file)

    logger.debug("New PDF files to add: %s", new_files)
    logger.info("Found %d new PDF file(s)", len(new_files))
    return new_files