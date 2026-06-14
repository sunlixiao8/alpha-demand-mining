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


if __name__ == "__main__":
    unittest.main()
