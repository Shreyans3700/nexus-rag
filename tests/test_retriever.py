import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")

from src.documents.retriever import _scope_filter, cited_sources


class RetrieverTests(unittest.TestCase):
    def test_citations_only_return_sources_used_in_answer(self):
        sources = [
            {"citation": 1, "filename": "one.pdf", "page": 1, "chunk": 0},
            {"citation": 2, "filename": "two.pdf", "page": 3, "chunk": 1},
        ]

        result = cited_sources("The answer is supported by [2], not [99].", sources)

        self.assertEqual(result, [sources[1]])

    def test_citations_match_comma_separated_bracket(self):
        sources = [
            {"citation": 1, "filename": "one.pdf", "page": 1, "chunk": 0},
            {"citation": 2, "filename": "two.pdf", "page": 3, "chunk": 1},
        ]

        result = cited_sources("Supported by [1, 2].", sources)

        self.assertEqual(result, sources)

    def test_citations_match_escaped_markdown_brackets(self):
        sources = [{"citation": 1, "filename": "one.pdf", "page": 1, "chunk": 0}]

        result = cited_sources("Supported by \\[1\\].", sources)

        self.assertEqual(result, sources)

    def test_citations_match_footnote_style(self):
        sources = [{"citation": 1, "filename": "one.pdf", "page": 1, "chunk": 0}]

        result = cited_sources("Supported by [^1].", sources)

        self.assertEqual(result, sources)

    def test_falls_back_to_all_sources_when_nothing_cited(self):
        sources = [
            {"citation": 1, "filename": "one.pdf", "page": 1, "chunk": 0},
            {"citation": 2, "filename": "two.pdf", "page": 3, "chunk": 1},
        ]

        result = cited_sources("The authors are Jane Doe and John Smith.", sources)

        self.assertEqual(result, sources)

    def test_no_sources_stays_empty_when_none_retrieved(self):
        result = cited_sources("No context was used for this answer.", [])

        self.assertEqual(result, [])

    def test_scope_filter_escapes_user_controlled_values(self):
        result = _scope_filter('user"id', 'session\\id')

        self.assertEqual(
            result,
            'user_id == "user\\"id" and session_id == "session\\\\id"',
        )
