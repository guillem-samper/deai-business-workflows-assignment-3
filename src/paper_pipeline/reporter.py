"""Static HTML report generation for the paper database."""

import json
import logging
from pathlib import Path
import sqlite3

from paper_pipeline.utils.database_utils import create_database_connection

logger: logging.Logger = logging.getLogger(__name__)


def generate_static_html(database_url: str, output_path: str | Path) -> Path:
    """Generate a static HTML research library with search and category filters.

    Args:
        database_url (str): SQLite database path or connection URL.
        output_path (str | Path): Destination path for the generated HTML file.

    Returns:
        Path: Path to the generated HTML file.

    Raises:
        sqlite3.Error: If the papers table cannot be read.
        OSError: If the output directory or HTML file cannot be created or written.
    """
    logger.info("Generating the static research library.")
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Read all paper records from the database.
    cursor, conn = create_database_connection(database_url)
    try:
        cursor.execute(
            "SELECT filename, title, summary, keywords, category FROM" " papers_table"
        )
        rows = cursor.fetchall()
    finally:
        conn.close()
    logger.debug("Loaded %d paper record(s) for the HTML library.", len(rows))

    # Collect categories and prepare records for rendering.
    categories = set()
    papers_data = []

    for row in rows:
        filename, title, summary, raw_keywords, category = row
        try:
            keywords = json.loads(raw_keywords) if raw_keywords else []
        except json.JSONDecodeError:
            keywords = []

        cat = category if category else "Uncategorized"
        categories.add(cat)

        papers_data.append(
            {
                "filename": filename,
                "title": title or filename,
                "summary": summary or "Without Summary",
                "keywords": keywords,
                "category": cat,
            }
        )

    # Build the category selector options.
    category_options = "\n".join(
        f'<option value="{c}">{c}</option>' for c in sorted(categories)
    )

    # Render one HTML card for each paper.
    cards_html = []
    for p in papers_data:
        kw_badges = " ".join(f'<span class="badge">{k}</span>' for k in p["keywords"])
        card = f"""
        <div class="paper-card" data-category="{p['category']}" data-search="{p['title'].lower()} {p['summary'].lower()} {' '.join(p['keywords']).lower()}">
            <h3>{p['title']}</h3>
            <p class="category"><strong>Categoria:</strong> {p['category']}</p>
            <p class="summary">{p['summary']}</p>
            <div class="keywords">{kw_badges}</div>
            <p class="filename"><small>Fitxer: {p['filename']}</small></p>
        </div>
        """
        cards_html.append(card)

    # Complete the HTML template, including client-side search and filtering.
    html_content = f"""<!DOCTYPE html>
    <html lang="ca">
    <head>
    <meta charset="UTF-8">
    <title>Research Library</title>
    <style>
        body {{ font-family: sans-serif; max-width: 900px; margin: 30px auto; padding: 0 20px; background: #f8f9fa; color: #333; }}
        h1 {{ text-align: center; }}
        .controls {{ display: flex; gap: 15px; margin-bottom: 25px; }}
        .controls input, .controls select {{ padding: 10px; font-size: 15px; border: 1px solid #ccc; border-radius: 6px; flex: 1; }}
        .paper-card {{ background: white; padding: 20px; margin-bottom: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.08); }}
        .paper-card h3 {{ margin-top: 0; color: #1a73e8; }}
        .badge {{ background: #e8f0fe; color: #1967d2; padding: 4px 8px; border-radius: 4px; font-size: 12px; margin-right: 5px; }}
        .category {{ color: #5f6368; }}
    </style>
    </head>
    <body>
    <h1>Research Library</h1>
    <div class="controls">
        <input type="text" id="searchInput" placeholder="Cercar per títol, resum o paraules clau..." onkeyup="filterPapers()">
        <select id="categoryFilter" onchange="filterPapers()">
            <option value="ALL">Totes les categories</option>
            {category_options}
        </select>
    </div>

    <div id="papersList">
        {''.join(cards_html) if cards_html else '<p>No hi ha documents a la biblioteca.</p>'}
    </div>

    <script>
        function filterPapers() {{
            const search = document.getElementById("searchInput").value.toLowerCase();
            const category = document.getElementById("categoryFilter").value;
            const cards = document.querySelectorAll(".paper-card");

            cards.forEach(card => {{
                const matchesSearch = card.getAttribute("data-search").includes(search);
                const matchesCategory = (category === "ALL") || (card.getAttribute("data-category") === category);

                if (matchesSearch && matchesCategory) {{
                    card.style.display = "block";
                }} else {{
                    card.style.display = "none";
                }}
            }});
        }}
    </script>
    </body>
    </html>
    """

    output_file.write_text(html_content, encoding="utf-8")
    logger.info("Static HTML generated successfully at %s.", output_file)
    return output_file
