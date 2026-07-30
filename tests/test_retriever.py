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

    def test_scope_filter_escapes_user_controlled_values(self):
        result = _scope_filter('user"id', 'session\\id')

        self.assertEqual(
            result,
            'user_id == "user\\"id" and session_id == "session\\\\id"',
        )

    def test_user_scope_omits_session_constraint(self):
        self.assertEqual(_scope_filter("user-1"), 'user_id == "user-1"')
