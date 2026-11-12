"""Local regression checks. No LLM server or Discord webhook is contacted."""

import os
import runpy
import sqlite3
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pymupdf

from paper_pipeline.database import (
    database_inserter,
    get_pending_discord_papers,
    initialize_database,
    mark_discord_papers_notified,
)
from paper_pipeline.drive import check_drive_folder
from paper_pipeline.parser import converter_pdf_to_markdown
from paper_pipeline.reporter import generate_static_html
from paper_pipeline.utils.llm_utils import PaperSummary, get_structured_response


class CatalogParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = []
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        attributes = dict(attrs)
        if tag == "div" and attributes.get("class") == "paper-card":
            self.cards.append(attributes)


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.airflow_directory = tempfile.TemporaryDirectory(prefix="paper-airflow-test-")
        cls.addClassCleanup(cls.airflow_directory.cleanup)
        environment = patch.dict(os.environ, {
            "AIRFLOW_HOME": cls.airflow_directory.name,
            "AIRFLOW__CORE__LOAD_EXAMPLES": "False",
        })
        environment.start()
        cls.addClassCleanup(environment.stop)
        namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "dags/paper_pipeline_dag.py"))
        cls.dag_factory = staticmethod(namespace["paper_pipeline"])
        cls.dag = cls.dag_factory()

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="paper-pipeline-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.database = self.root / "papers.db"
        self.papers = self.root / "papers"
        self.papers.mkdir()
        environment = patch.dict(os.environ, {
            "DATABASE_URL": str(self.database),
            "PAPERS_GOOGLE_DRIVE_FOLDER_PATH": str(self.papers),
            "OUTPUTS_GOOGLE_DRIVE_FOLDER_PATH": str(self.root / "output"),
            "MARKDOWN_EXTRACTIONS_FOLDER": str(self.root / "markdown"),
            "SYSTEM_PROMPTS_FILE_PATH": str(Path(__file__).resolve().parents[1] / "prompts/prompts.yaml"),
            "DISCORD_NOTIFICATIONS_ENABLED": "false",
            "LLM_MAX_INPUT_CHARS": "0",
        })
        environment.start()
        self.addCleanup(environment.stop)
        initialize_database(str(self.database))
        self.metadata = {
            "filename": "paper",
            "title": 'A "Quoted" Study <example>',
            "summary": "Research & results",
            "keywords": ["data", 'a "keyword"'],
            "category": 'Methods "A" & B',
        }

    def make_pdf(self, name="paper.pdf"):
        path = self.papers / name
        with pymupdf.open() as document:
            page = document.new_page()
            page.insert_text((72, 72), "A scientific paper about data workflows.")
            document.save(str(path))
        return path

    def fake_client(self):
        parsed = PaperSummary(**{key: value for key, value in self.metadata.items() if key != "filename"})
        client = Mock()
        client.beta.chat.completions.parse.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))]
        )
        return client

    def test_pdf_conversion(self):
        markdown = converter_pdf_to_markdown(self.make_pdf())
        self.assertIsNotNone(markdown)
        self.assertIn("data workflows", markdown.read_text())

    def test_repeat_scan_finds_no_new_papers(self):
        self.make_pdf()
        (self.papers / "renamed.pdf").write_text("This is not a PDF.")
        self.assertEqual(check_drive_folder(self.papers), ["paper.pdf"])
        database_inserter([self.metadata], str(self.database))
        self.assertEqual(check_drive_folder(self.papers), [])

    def test_failed_batch_is_rolled_back(self):
        database_inserter([self.metadata], str(self.database))
        with self.assertRaises(sqlite3.IntegrityError):
            database_inserter([{**self.metadata, "filename": "new"}, self.metadata], str(self.database))
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM papers_table").fetchone()[0], 1)
        self.assertEqual(get_pending_discord_papers(str(self.database)), ["paper"])

    def test_legacy_database_migration_preserves_papers_and_delivery_state(self):
        legacy = str(self.root / "legacy.db")
        with sqlite3.connect(legacy) as connection:
            connection.execute(
                "CREATE TABLE papers_table (filename TEXT UNIQUE NOT NULL, "
                "title TEXT, summary TEXT, keywords TEXT, category TEXT)"
            )
            connection.execute(
                "INSERT INTO papers_table VALUES (?, ?, ?, ?, ?)",
                ("legacy", "Existing title", "Existing summary", "[]", "Research"),
            )

        initialize_database(legacy)
        self.assertEqual(get_pending_discord_papers(legacy), ["legacy"])
        mark_discord_papers_notified(["legacy"], legacy)
        initialize_database(legacy)
        self.assertEqual(get_pending_discord_papers(legacy), [])
        with sqlite3.connect(legacy) as connection:
            self.assertEqual(
                connection.execute("SELECT title FROM papers_table").fetchall(),
                [("Existing title",)],
            )

    def test_catalog_preserves_quotes_and_treats_metadata_as_text(self):
        database_inserter([self.metadata], str(self.database))
        html = generate_static_html(str(self.database), self.root / "output/index.html").read_text()
        parser = CatalogParser()
        parser.feed(html)
        self.assertEqual(parser.cards[0]["data-category"], self.metadata["category"])
        self.assertIn(self.metadata["title"].lower(), parser.cards[0]["data-search"])
        self.assertNotIn("example", parser.tags)

    def test_corrupted_pdf_does_not_reach_llm(self):
        self.make_pdf()
        (self.papers / "broken.pdf").write_bytes(b"%PDF-broken")
        paths = self.dag.get_task("convert_papers_to_text").python_callable(["broken.pdf", "paper.pdf"])
        self.assertEqual(paths, [str(self.root / "markdown/paper.md")])

    def test_pdf_without_extracted_text_is_skipped(self):
        pdf = self.make_pdf()
        with patch("paper_pipeline.parser.pymupdf4llm.to_markdown", return_value="  \n"):
            self.assertIsNone(converter_pdf_to_markdown(pdf))
        self.assertFalse((self.root / "markdown/paper.md").exists())

    def test_empty_run_does_not_render_or_notify(self):
        self.assertEqual(self.dag.get_task("check_new_papers").python_callable(), [])
        render = self.dag.get_task("render_html").python_callable
        notify = self.dag.get_task("notify_discord").python_callable
        with patch.dict(os.environ, {"DISCORD_NOTIFICATIONS_ENABLED": "true"}):
            with patch.dict(render.__globals__, {"generate_static_html": Mock(), "DiscordWebhook": Mock()}):
                self.assertEqual(render(0), 0)
                notify(0)
                render.__globals__["generate_static_html"].assert_not_called()
                render.__globals__["DiscordWebhook"].assert_not_called()

    def test_development_mode_does_not_send_discord_messages(self):
        database_inserter([self.metadata], str(self.database))
        notify = self.dag.get_task("notify_discord").python_callable
        webhook = Mock()
        with patch.dict(notify.__globals__, {"DiscordWebhook": webhook}):
            notify(1)
        webhook.assert_not_called()
        self.assertEqual(get_pending_discord_papers(str(self.database)), ["paper"])

    def test_enabled_notification_checks_http_status(self):
        database_inserter([self.metadata], str(self.database))
        notify = self.dag.get_task("notify_discord").python_callable
        webhook = Mock()
        webhook.return_value.execute.return_value.raise_for_status.side_effect = RuntimeError("HTTP error")
        with patch.dict(os.environ, {
            "DISCORD_NOTIFICATIONS_ENABLED": "true",
            "PRODUCTION_DISCORD_WEBHOOK_URL": "https://example.invalid/webhook",
        }):
            with patch.dict(notify.__globals__, {"DiscordWebhook": webhook}):
                with self.assertRaisesRegex(RuntimeError, "HTTP error"):
                    notify(1)
        webhook.return_value.execute.assert_called_once()
        self.assertEqual(get_pending_discord_papers(str(self.database)), ["paper"])

    def test_failed_notification_is_retried_on_later_empty_run(self):
        database_inserter([self.metadata], str(self.database))
        notify = self.dag.get_task("notify_discord").python_callable
        webhook = Mock()
        webhook.return_value.execute.return_value.raise_for_status.side_effect = [
            RuntimeError("HTTP error"), None,
        ]
        with patch.dict(os.environ, {
            "DISCORD_NOTIFICATIONS_ENABLED": "true",
            "PRODUCTION_DISCORD_WEBHOOK_URL": "https://example.invalid/webhook",
        }):
            with patch.dict(notify.__globals__, {"DiscordWebhook": webhook}):
                with self.assertRaisesRegex(RuntimeError, "HTTP error"):
                    notify(1)
                self.assertEqual(get_pending_discord_papers(str(self.database)), ["paper"])

                # A fresh DAG run discovers no new files, but still delivers the backlog.
                initialize_database(str(self.database))
                files = self.dag.get_task("check_new_papers").python_callable()
                paths = self.dag.get_task("convert_papers_to_text").python_callable(files)
                records = self.dag.get_task("call_llm").python_callable(paths)
                count = self.dag.get_task("save_to_db").python_callable(records)
                rendered = self.dag.get_task("render_html").python_callable(count)
                self.assertEqual(rendered, 0)
                notify(rendered)
                self.assertEqual(get_pending_discord_papers(str(self.database)), [])

                # A subsequent empty run has nothing left to announce.
                notify(0)
        self.assertEqual(webhook.call_count, 2)
        self.assertEqual(webhook.return_value.execute.call_count, 2)
        self.assertIn("1 new paper has", webhook.call_args.kwargs["content"])

    def test_connection_failure_keeps_notification_pending(self):
        database_inserter([self.metadata], str(self.database))
        notify = self.dag.get_task("notify_discord").python_callable
        webhook = Mock()
        webhook.return_value.execute.side_effect = ConnectionError("Unavailable")
        with patch.dict(os.environ, {
            "DISCORD_NOTIFICATIONS_ENABLED": "true",
            "PRODUCTION_DISCORD_WEBHOOK_URL": "https://example.invalid/webhook",
        }):
            with patch.dict(notify.__globals__, {"DiscordWebhook": webhook}):
                with self.assertRaises(ConnectionError):
                    notify(0)
        self.assertEqual(get_pending_discord_papers(str(self.database)), ["paper"])

    def test_notification_acknowledges_only_the_sent_papers(self):
        database_inserter([self.metadata], str(self.database))
        notify = self.dag.get_task("notify_discord").python_callable
        webhook = Mock()

        def send_and_add_another_paper():
            database_inserter([{**self.metadata, "filename": "later"}], str(self.database))
            return Mock()

        webhook.return_value.execute.side_effect = send_and_add_another_paper
        with patch.dict(os.environ, {
            "DISCORD_NOTIFICATIONS_ENABLED": "true",
            "PRODUCTION_DISCORD_WEBHOOK_URL": "https://example.invalid/webhook",
        }):
            with patch.dict(notify.__globals__, {"DiscordWebhook": webhook}):
                notify(1)
        self.assertEqual(get_pending_discord_papers(str(self.database)), ["later"])

    def test_missing_webhook_keeps_notification_pending(self):
        database_inserter([self.metadata], str(self.database))
        notify = self.dag.get_task("notify_discord").python_callable
        with patch.dict(os.environ, {
            "DISCORD_NOTIFICATIONS_ENABLED": "true",
            "PRODUCTION_DISCORD_WEBHOOK_URL": "",
        }):
            with self.assertRaisesRegex(ValueError, "PRODUCTION_DISCORD_WEBHOOK_URL"):
                notify(0)
        self.assertEqual(get_pending_discord_papers(str(self.database)), ["paper"])

    def test_llm_input_is_not_silently_cut_to_1000_characters(self):
        client = self.fake_client()
        content = "Research details. " * 100
        get_structured_response(content, [], client, "Extract metadata.")
        sent = client.beta.chat.completions.parse.call_args.kwargs["messages"][1]["content"]
        self.assertEqual(sent, content)

    def test_configured_llm_input_limit(self):
        client = self.fake_client()
        content = "Research details. " * 100
        with patch.dict(os.environ, {"LLM_MAX_INPUT_CHARS": "1200"}):
            get_structured_response(content, [], client, "Extract metadata.")
        sent = client.beta.chat.completions.parse.call_args.kwargs["messages"][1]["content"]
        self.assertEqual(sent, content[:1200] + "\n[Paper text truncated]")

    def test_llm_without_parsed_metadata_fails_clearly(self):
        client = self.fake_client()
        client.beta.chat.completions.parse.return_value.choices[0].message.parsed = None
        with self.assertRaisesRegex(ValueError, "structured paper metadata"):
            get_structured_response("Research paper.", [], client, "Extract metadata.")

    def test_end_to_end_with_mocked_llm_and_repeat_run(self):
        self.make_pdf()
        scan = self.dag.get_task("check_new_papers").python_callable
        convert = self.dag.get_task("convert_papers_to_text").python_callable
        infer = self.dag.get_task("call_llm").python_callable
        save = self.dag.get_task("save_to_db").python_callable
        render = self.dag.get_task("render_html").python_callable
        with patch("paper_pipeline.parser.get_llm_client", return_value=self.fake_client()):
            records = infer(convert(scan()))
        self.assertEqual(render(save(records)), 1)
        self.assertTrue((self.root / "output/index.html").is_file())
        self.assertEqual(save(infer(convert(scan()))), 0)


if __name__ == "__main__":
    unittest.main()
