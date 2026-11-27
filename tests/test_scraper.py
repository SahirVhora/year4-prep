import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import scrape_papers


class PaperValidationTests(unittest.TestCase):
    def test_html_download_page_is_not_accepted_as_a_pdf(self):
        response = Mock(status=200)
        response.read.return_value = b"<!doctype html>" + b"x" * 6000
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)
        with patch.object(scrape_papers, "urlopen", return_value=response):
            result = scrape_papers.verify_pdf("https://school.example/paper.pdf")
        self.assertEqual(result["status"], "broken")
        self.assertIn("not a PDF", result["error"])

    def test_forbidden_download_is_not_republished_as_browser_only(self):
        papers = [
            {"url": "https://school.example/ok.pdf", "name": "OK", "term": "Spring"},
            {"url": "https://school.example/denied.pdf", "name": "Denied", "term": "Spring"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "papers.json"
            with (
                patch.object(scrape_papers, "OUTPUT_FILE", str(output)),
                patch.object(scrape_papers, "discover_from_known_sources", return_value=papers),
                patch.object(scrape_papers, "discover_from_searches", return_value=[]),
                patch.object(scrape_papers.time, "sleep"),
                patch.object(scrape_papers, "verify_pdf", side_effect=[
                    {"status": "ok", "size": 6000},
                    {"status": "broken", "error": "HTTP 403 Forbidden"},
                ]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                scrape_papers.main()
            result = json.loads(output.read_text())
        self.assertEqual([paper["name"] for paper in result["papers"]], ["OK"])
        self.assertEqual([paper["name"] for paper in result["broken"]], ["Denied"])
        self.assertEqual(result["metadata"]["unverifiedPapers"], 0)


if __name__ == "__main__":
    unittest.main()
