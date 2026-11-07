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
        For debugging, Markdown longer than 1000 characters is truncated before
        it is sent to the LLM.
    """
    logger.debug("Calling LLM with system prompt: %s", system_prompt)
    logger.debug("Calling LLM with %d characters of Markdown.", len(markdown_text))

    # Keep local LLM requests short while debugging.
    # TODO: DELETE THIS DEBUGGING CODE
    if len(markdown_text) > 1000:
        logger.debug("Markdown text is too long, truncating for debugging purposes.")
        markdown_text = markdown_text[:1000] + " ... [truncated]"
    
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
    logger.info("Received structured metadata from the LLM.")
    messages.append({"role": "assistant", "content": paper_info})

    return dict(paper_info), messages
