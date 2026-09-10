from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import unittest


ROOT = Path(__file__).resolve().parents[2]
CONVERSATION = (ROOT / "backend" / "app" / "conversation_agent.py").read_text(encoding="utf-8")
INGESTION = (ROOT / "backend" / "app" / "ingestion.py").read_text(encoding="utf-8")
RETRIEVAL = (ROOT / "backend" / "app" / "retrieval.py").read_text(encoding="utf-8")


def _load_subset(
    source: str,
    *,
    functions: set[str],
    assignments: set[str] | None = None,
    globals_: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tree = ast.parse(source)
    selected: list[ast.stmt] = []
    assignment_names = assignments or set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in functions:
            selected.append(node)
            continue
        if isinstance(node, ast.Assign):
            names = {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            if names.intersection(assignment_names):
                selected.append(node)

    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace: dict[str, Any] = {
        "Any": Any,
        "re": re,
        **(globals_ or {}),
    }
    exec(compile(module, "<p16-regression-subset>", "exec"), namespace)
    return namespace


class P16ReviewRegressionTests(unittest.TestCase):
    def test_followup_spec_change_preserves_product_identifier(self):
        ns = _load_subset(
            CONVERSATION,
            functions={"_entity_family", "_contextual_retrieval_query"},
            assignments={"ENTITY_PATTERN"},
            globals_={
                "settings": SimpleNamespace(retrieval_query_context_max_chars=320),
            },
        )
        enrich = ns["_contextual_retrieval_query"]

        enriched, contextualized = enrich(
            "那 IP67 呢？",
            [{"role": "user", "content": "X100 支持 IP65 吗？"}],
        )
        self.assertTrue(contextualized)
        self.assertIn("上下文主题：X100 支持 IP67 吗？", enriched)
        self.assertNotIn("IP65", enriched)
        self.assertNotIn("IP67 支持 IP67", enriched)

    def test_followup_product_change_preserves_unrelated_spec_identifier(self):
        ns = _load_subset(
            CONVERSATION,
            functions={"_entity_family", "_contextual_retrieval_query"},
            assignments={"ENTITY_PATTERN"},
            globals_={
                "settings": SimpleNamespace(retrieval_query_context_max_chars=320),
            },
        )
        enrich = ns["_contextual_retrieval_query"]

        enriched, contextualized = enrich(
            "那 X200 呢？",
            [{"role": "user", "content": "X100 支持 IP65 吗？"}],
        )
        self.assertTrue(contextualized)
        self.assertIn("上下文主题：X200 支持 IP65 吗？", enriched)
        self.assertNotIn("X100", enriched)

    def test_markdown_child_chunk_keeps_parent_heading_without_heading_only_chunk(self):
        ns = _load_subset(
            INGESTION,
            functions={"chunk_text", "chunk_markdown"},
            assignments={"MARKDOWN_HEADING"},
            globals_={
                "settings": SimpleNamespace(chunk_size=800, chunk_overlap=120),
            },
        )
        chunk_markdown = ns["chunk_markdown"]

        parts = chunk_markdown(
            "## 4. 国内住宿标准\n"
            "### 4.1 一线城市\n"
            "北京、上海住宿标准为每晚 500 元。\n"
        )
        self.assertEqual(1, len(parts))
        self.assertEqual("4. 国内住宿标准 > 4.1 一线城市", parts[0]["section_title"])
        self.assertIn("## 4. 国内住宿标准", parts[0]["content"])
        self.assertIn("### 4.1 一线城市", parts[0]["content"])
        self.assertIn("500 元", parts[0]["content"])

    def test_non_positive_bm25_score_keeps_real_lexical_match(self):
        ns = _load_subset(
            RETRIEVAL,
            functions={"tokenize", "rank_bm25_match_ids"},
        )
        tokenize = ns["tokenize"]
        rank_matches = ns["rank_bm25_match_ids"]

        rows = [{"id": "x200-temp"}]
        corpus = [tokenize("X200 工作温度 -20 到 60 摄氏度")]
        self.assertEqual(
            ["x200-temp"],
            rank_matches(rows, corpus, [-0.25], "X200 工作温度"),
        )
        self.assertEqual([], rank_matches(rows, corpus, [-0.25], "差旅报销"))
        self.assertIn("bm25_match_ids = rank_bm25_match_ids", RETRIEVAL)
        self.assertIn("for point_id in bm25_match_ids", RETRIEVAL)


if __name__ == "__main__":
    unittest.main()
