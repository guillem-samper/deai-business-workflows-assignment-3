"""Database setup and persistence for extracted paper metadata."""

import logging
import sqlite3
import json

from paper_pipeline.utils.database_utils import create_database_connection

logger: logging.Logger = logging.getLogger(__name__)


def initialize_database(database_url: str) -> None:
    """Create the papers table if it does not already exist.

    Args:
        database_url (str): SQLite database path or connection URL.

    Returns:
        None.

    Raises:
        sqlite3.Error: If creating the table or committing the transaction fails.
    """
    logger.info("Initializing the papers database.")
    cursor, conn = create_database_connection(database_url=database_url)
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS papers_table (
                filename TEXT UNIQUE NOT NULL,
                title TEXT,
                summary TEXT,
                keywords TEXT,
                category TEXT
            )
            """)
        conn.commit()
        logger.info("Ensured papers_table exists in the database.")
    except sqlite3.Error:
        logger.exception("Failed to initialize the papers database")
        raise
    finally:
        conn.close()


def database_inserter(
    papers_metadata: list[dict[str, str | list[str]]], database_url: str
) -> None:
    """Insert extracted paper metadata into the database.

    Args:
        papers_metadata (list[dict[str, str | list[str]]]): Paper records with
            ``filename``, ``title``, ``summary``, ``keywords``, and ``category``
            fields. Text fields are strings; ``keywords`` is a list of strings.
        database_url (str): SQLite database path or connection URL.

    Returns:
        None.

    Raises:
        sqlite3.Error: If insertion or transaction commit fails. The transaction
            is rolled back before the error is re-raised.
    """
    if not papers_metadata:
        logger.warning("No paper metadata provided to insert into the database.")
        return

    conn = None
    try:
        cursor, conn = create_database_connection(database_url=database_url)
        records_to_insert = [
            (
                item["filename"],
                item["title"],
                item["summary"],
                json.dumps(
                    item["keywords"]
                ),
                item["category"],
            )
            for item in papers_metadata
        ]
        logger.debug("Prepared records for insertion: %s", records_to_insert)

        sql_insert_statement = """
            INSERT INTO papers_table (filename, title, summary, keywords, category)
            VALUES (?, ?, ?, ?, ?)
        """
        cursor.executemany(sql_insert_statement, records_to_insert)
        conn.commit()
        logger.info(
            "Inserted %d new paper record(s) into the database.",
            len(records_to_insert),
        )
    except sqlite3.Error:
        logger.exception(
            "Error during block insertion into the database in %s", database_url
        )
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()
