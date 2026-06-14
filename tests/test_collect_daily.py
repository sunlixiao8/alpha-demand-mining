import csv
import tempfile
import unittest
from pathlib import Path

import scripts.collect_daily as c
import scripts.audit_report as audit_report


class CollectDailyTest(unittest.TestCase):
    def make_signal(self, title, raw, type_="GitHub Trending / New Tech", source="GitHub Search: test"):
        item = c.Signal(title=title, url="https://example.com/x", source=source, type=type_, raw=raw, score=20)
        return c.classify_and_score(item)

    def test_clean_url_keeps_last_url_when_concatenated(self):
        bad = "https://github.com/a/bhttps://github.com/c/d"
        self.assertEqual(c.clean_url(bad), "https://github.com/c/d")

    def test_domain_specific_mvp_is_not_generic_for_video_and_docs(self):
        video = self.make_signal(
            "myccarl/ai-shortVideo-pipeline",
            "End-to-end AI short-video production pipeline with multi-model failover.",
        )
        docs = self.make_signal(
            "amElnagdy/guard-skills",
            "Guard skills for coding agents, quality gates that catch AI-generated failure modes in code, tests, and docs.",
        )

        self.assertIn("视频", c.need_sentence(video))
        self.assertIn("GitHub", c.mvp_sentence(docs))
        self.assertNotEqual(c.mvp_sentence(video), c.mvp_sentence(docs))
        self.assertNotEqual(c.distribution_sentence(video), c.distribution_sentence(docs))

    def test_quality_gate_rejects_failed_or_contextless_items(self):
        failed = c.Signal("GitHub Trending fetch failed", "https://example.com", "GitHub", "GitHub Trending", "error", 8)
        weak = c.Signal("random/repo", "https://example.com", "GitHub", "GitHub Trending / New Tech", "", 12)
        useful = self.make_signal("demo/ai-agent", "AI agent workflow automation with deployment templates. Stars: 100.")

        self.assertFalse(c.quality_gate(failed))
        self.assertFalse(c.quality_gate(weak))
        self.assertTrue(c.quality_gate(useful))

    def test_append_csv_replaces_same_day_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_csv = c.CSV_PATH
            try:
                c.CSV_PATH = Path(tmp) / "opportunities.csv"
                first = self.make_signal("demo/ai-agent", "AI agent workflow automation with deployment templates.")
                second = self.make_signal("demo/image-tool", "AI image generation workflow for ecommerce product photos.")
                c.append_csv([first], "2026-06-15")
                c.append_csv([second], "2026-06-15")
                with c.CSV_PATH.open(encoding="utf-8") as f:
                    rows = list(csv.DictReader(f))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["title"], "demo/image-tool")
            finally:
                c.CSV_PATH = old_csv

    def test_audit_rejects_template_repetition(self):
        template_item = """
### 1. demo

- 来源：x
- 链接：https://example.com
- 类型：x
- 结论：结论：适合观察和做轻量验证。
- 原始信号：这是足够长的原始信号，方便复核。
- 证据：证据足够。
- 为什么现在：现在有窗口。
- 用户是谁：用户。
- 真实需求：重复需求
- 供需失衡：供给不足。
- 切入角度：重复切口
- 可做 MVP：重复 MVP
- 分发路径：重复分发
- 变现方式：订阅。
- 风险：风险。
- 下一步验证：重复验证
- 置信度：中。
- 评分：需求强度 4 / 供给缺口 4 / Alpha 时效 5 / MVP 可行性 4 / 变现潜力 4，总分 21
- 建议：深挖
"""
        report = "# report\n" + template_item * 10
        errors = audit_report.audit(report)
        self.assertTrue(any("重复模板" in error for error in errors))

    def test_selection_preserves_source_diversity(self):
        signals = []
        for idx in range(15):
            signals.append(self.make_signal(f"demo/ai-agent-{idx}", "AI agent workflow automation with deployment templates. Stars: 100."))
        for idx in range(3):
            signals.append(self.make_signal(
                f"org/model-{idx}",
                "Trending model. Tags: text-generation, transformers. Downloads: 1000. Likes: 20.",
                type_="HF Trending / New Tech",
                source="Hugging Face Trending",
            ))
        for idx in range(2):
            signals.append(self.make_signal(
                f"Show HN: AI workflow {idx}",
                "Fresh tech discussion about AI workflow automation.",
                type_="News Window",
                source="Hacker News: AI",
            ))

        selected = c.select_signals(signals)
        families = [c.source_family(item) for item in selected]
        self.assertIn("Hugging Face", families)
        self.assertIn("News", families)
        self.assertLessEqual(families.count("GitHub"), 9)

    def test_huggingface_model_parser_filters_navigation_links(self):
        html = """
        <a href="/models">Models</a>
        <a href="/join/discord">Discord</a>
        <a href="/google/diffusiongemma-26B-A4B-it">model</a>
        <a href="/moonshotai/Kimi-K2.7-Code">model</a>
        <a href="/inference/models">not a model</a>
        <a href="/spaces/user/demo">space</a>
        <a href="/docs/transformers">docs</a>
        """
        self.assertEqual(
            c.extract_huggingface_model_ids(html),
            ["google/diffusiongemma-26B-A4B-it", "moonshotai/Kimi-K2.7-Code"],
        )

    def test_audit_rejects_single_source_report(self):
        item = """
### 1. demo

- 来源：GitHub Search: test
- 链接：https://example.com
- 类型：GitHub Trending / New Tech
- 结论：适合观察和做轻量验证。
- 原始信号：这是足够长的原始信号，方便复核。
- 证据：证据足够。
- 为什么现在：现在有窗口。
- 用户是谁：用户。
- 真实需求：需求 1
- 供需失衡：供给不足。
- 切入角度：切口 1
- 可做 MVP：MVP 1
- 分发路径：分发 1
- 变现方式：订阅。
- 风险：风险。
- 下一步验证：验证 1
- 置信度：中。
- 评分：需求强度 4 / 供给缺口 4 / Alpha 时效 5 / MVP 可行性 4 / 变现潜力 4，总分 21
- 建议：观察
"""
        report = "# report\n" + "\n".join(item.replace("需求 1", f"需求 {idx}").replace("切口 1", f"切口 {idx}").replace("MVP 1", f"MVP {idx}").replace("分发 1", f"分发 {idx}").replace("验证 1", f"验证 {idx}") for idx in range(10))
        errors = audit_report.audit(report)
        self.assertTrue(any("来源过于单一" in error for error in errors))

    def test_collector_quality_gate_rejects_empty_selection(self):
        errors = c.validate_selected_signals([])
        self.assertTrue(any("有效线索不足" in error for error in errors))
        self.assertTrue(any("缺少 Hugging Face" in error for error in errors))

    def test_collector_quality_gate_accepts_diverse_selection(self):
        signals = []
        for idx in range(5):
            item = self.make_signal(
                f"org/model-{idx}",
                "Trending model. Tags: text-generation, transformers. Downloads: 1000. Likes: 20.",
                type_="HF Trending / New Tech",
                source="Hugging Face Trending",
            )
            signals.append(item)
        for idx in range(5):
            signals.append(self.make_signal(f"demo/ai-agent-{idx}", "AI agent workflow automation with deployment templates. Stars: 100."))
        self.assertEqual(c.validate_selected_signals(signals), [])


if __name__ == "__main__":
    unittest.main()
