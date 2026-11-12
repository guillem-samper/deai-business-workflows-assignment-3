"""LLM client setup, response schema, and structured completion utilities."""

import logging
import os

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

load_dotenv(".env")
logger: logging.Logger = logging.getLogger(__name__)


def get_llm_client() -> OpenAI:
    """Create an OpenAI client configured for the local LLM service.

    Args:
        None.

    Returns:
        OpenAI: Client configured with the ``LOCAL_LLM_URL`` environment value.
    """
    client = OpenAI(api_key="your-api-key", base_url=os.getenv("LOCAL_LLM_URL"))
    logger.info("Initialized the LLM client.")
    return client


class PaperSummary(BaseModel):
    """Structured fields expected from an LLM-generated paper summary.

    Attributes:
        title (str): Paper title.
        summary (str): Concise summary of the paper.
        keywords (list[str]): Keywords describing the paper.
        category (str): Assigned paper category.
    """

    title: str
    summary: str
    keywords: list[str]
    category: str


def get_structured_response(
    markdown_text: str,
    messages: list[dict[str, object]],
    client: OpenAI,
    system_prompt: str,
) -> tuple[dict[str, str | list[str]], list[dict[str, object]]]:
    """Request structured paper metadata from the configured LLM.

    Args:
        markdown_text (str): Markdown content to summarize.
        messages (list[dict[str, object]]): Conversation history to append the
            user content and parsed assistant response to.
        client (OpenAI): Configured OpenAI-compatible client.
        system_prompt (str): Instructions defining the expected summary.

    Returns:
        tuple[dict[str, str | list[str]], list[dict[str, object]]]: Parsed
        ``title``, ``summary``, ``keywords``, and ``category`` fields plus the
        updated conversation history.

    Notes:
        LLM_MAX_INPUT_CHARS optionally limits the paper text. Its default of 0
        sends the complete Markdown; configure it for the local model's context.
    """
    logger.debug("Calling LLM with system prompt: %s", system_prompt)
    logger.debug("Calling LLM with %d characters of Markdown.", len(markdown_text))

    max_input_chars = int(os.getenv("LLM_MAX_INPUT_CHARS", "0"))
    if max_input_chars < 0:
        raise ValueError("LLM_MAX_INPUT_CHARS must be 0 or a positive integer.")
    if max_input_chars and len(markdown_text) > max_input_chars:
        logger.warning(
            "Limiting LLM input from %d to %d characters.",
            len(markdown_text), max_input_chars,
        )
        markdown_text = markdown_text[:max_input_chars] + "\n[Paper text truncated]"

    messages.append({"role": "user", "content": markdown_text})
    response = client.beta.chat.completions.parse(
        model=os.getenv("LLM_MODEL_NAME", "google/gemma-4-e2b"),
        response_format=PaperSummary,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": markdown_text},
        ],
    )
    logger.debug("LLM response: %s", response)

    paper_info = response.choices[0].message.parsed
    if paper_info is None:
        raise ValueError("The LLM did not return structured paper metadata.")
    logger.info("Received structured metadata from the LLM.")
    messages.append({"role": "assistant", "content": paper_info})

    return dict(paper_info), messages
