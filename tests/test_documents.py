import os
import unittest

from fastapi import HTTPException

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")

from src.documents.chunker import chunk_units
from src.documents.parser import ParsedUnit, parse_file
from src.routes.documents import _check_extension


class DocumentProcessingTests(unittest.TestCase):
    def test_csv_is_parsed_into_searchable_rows(self):
        units = parse_file("contacts.csv", b"name,city\nAda,London\n")

        self.assertEqual(len(units), 1)
        self.assertIn("Ada, London", units[0].text)
        self.assertIsNone(units[0].page)

    def test_text_parser_falls_back_for_non_utf8_content(self):
        units = parse_file("notes.txt", b"caf\xe9")

        self.assertEqual(units[0].text, "caf\u00e9")

    def test_chunking_preserves_page_metadata_and_boundaries(self):
        units = [
            ParsedUnit(text="first page content", page=1),
            ParsedUnit(text="second page content", page=2),
        ]

        chunks = chunk_units(units)

        self.assertEqual([chunk.page for chunk in chunks], [1, 2])
        self.assertEqual([chunk.chunk_index for chunk in chunks], [0, 1])

    def test_disallowed_extension_is_rejected_before_ingestion(self):
        with self.assertRaises(HTTPException) as error:
            _check_extension("payload.exe")

        self.assertEqual(error.exception.status_code, 422)

    def test_parser_rejects_unknown_extension(self):
        with self.assertRaises(ValueError):
            parse_file("payload.exe", b"not executable")
