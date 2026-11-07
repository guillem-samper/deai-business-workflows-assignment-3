"""PDF-to-Markdown conversion and LLM metadata extraction."""

import logging
import os
import yaml
from pathlib import Path

import pymupdf
import pymupdf4llm
from dotenv import load_dotenv

from paper_pipeline.utils.llm_utils import get_llm_client, get_structured_response

load_dotenv(".env")

logger: logging.Logger = logging.getLogger(__name__)


def converter_pdf_to_markdown(file_path: Path) -> Path | None:
    """Convert a PDF file to Markdown and write the result to disk.

    Args:
        file_path (Path): Path to the source PDF.

    Returns:
        Path | None: Path to the generated Markdown file, or ``None`` if the
        PDF is corrupted or unreadable.

    Raises:
        FileNotFoundError: If ``file_path`` does not identify a file.
        Exception: Re-raises unexpected errors encountered during conversion
            or writing.
    """
    if not file_path.is_file():
        logger.error("PDF file does not exist: %s", file_path)
        raise FileNotFoundError(f"PDF file does not exist: {file_path}")

    try:
        logger.info("Converting %s to Markdown format", file_path)
        markdown_text = pymupdf4llm.to_markdown(str(file_path))
        output_dir = Path(os.getenv("MARKDOWN_EXTRACTIONS_FOLDER", "data/markdown"))
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{file_path.stem}.md"
        output_file.write_text(markdown_text, encoding="utf-8")

        logger.info("Markdown file created at %s.", output_file)

        return output_file

    except pymupdf.FileDataError:
        logger.warning(
            "Skipping corrupted or unreadable PDF file: %s",
            file_path.name,
            exc_info=True,
        )
        return None
    except Exception:
        logger.exception("Unexpected error while processing PDF: %s", file_path.name)
        raise


def get_llm_response(file_name: str) -> dict[str, str | list[str]]:
    """Extract structured paper metadata from a Markdown file.

    Args:
        file_name (str): Path to the Markdown file to process.

    Returns:
        dict[str, str | list[str]]: Extracted title, summary, category, keywords,
        and filename. Text fields are strings; ``keywords`` is a list of strings.

    Raises:
        FileNotFoundError: If the Markdown file or configured prompt file is
            missing.
        ValueError: If the prompt configuration does not contain a system prompt.
    """
    logger.info("Opening file: %s", file_name)
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            markdown_text = f.read()

        with open(os.getenv("SYSTEM_PROMPTS_FILE_PATH"), "r") as file:
            prompts = yaml.safe_load(file)
        system_prompt = prompts.get("system_prompt", "")
        if not system_prompt:
            raise ValueError("System prompt is missing in the prompts file.")

        client = get_llm_client()
        messages = [{"role": "system", "content": system_prompt}]
        paper_info, messages = get_structured_response(
            markdown_text=markdown_text,
            messages=messages,
            client=client,
            system_prompt=system_prompt,
        )
        paper_info["filename"] = str(Path(file_name).stem)
        logger.info("Extracted paper metadata from %s.", file_name)
        logger.debug("LLM response for %s: %s", file_name, paper_info)
        return paper_info

    except FileNotFoundError:
        logger.error("File not found: %s", file_name)
        raise
