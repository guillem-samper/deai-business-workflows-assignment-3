"""Shared SQLite connection utilities."""

import logging
import sqlite3

logger: logging.Logger = logging.getLogger(__name__)


def create_database_connection(
    database_url: str,
) -> tuple[sqlite3.Cursor, sqlite3.Connection]:
    """Open a SQLite database connection and create its cursor.

    Args:
        database_url (str): SQLite database path or connection URL.

    Returns:
        tuple[sqlite3.Cursor, sqlite3.Connection]: Cursor and open connection.
        The caller is responsible for closing the connection.

    Raises:
        sqlite3.Error: If the database connection cannot be opened.
    """
    try:
        conn = sqlite3.connect(database_url)
        logger.debug("Opened database connection to %s.", database_url)
        return conn.cursor(), conn
    except sqlite3.Error:
        logger.exception("Failed to connect to the database at %s", database_url)
        raise