#!/usr/bin/env python3
"""Audit generated daily demand report quality."""

from __future__ import annotations

import argparse
import datetime as dt
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FIELDS = [
    "结论",
    "原始信号",
    "证据",
    "为什么现在",
    "用户是谁",
    "真实需求",
    "供需失衡",
    "切入角度",
    "可做 MVP",
    "分发路径",
    "变现方式",
    "风险",
    "下一步验证",
    "置信度",
    "评分",
    "建议",
]
GENERIC_BAD_PHRASES = [
    "把新模型/开源能力包装成普通用户可直接使用的工具、模板或托管工作流",
    "开源项目通常部署、配置、文档和产品化不足，适合做托管版、模板版或垂直版",
    "48 小时内做一个承接页 + Demo/教程 + 等候名单；能调用则做最小可用 Web 工具",
]


def today_shanghai() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")


def split_items(markdown: str) -> list[str]:
    parts = re.split(r"\n###\s+\d+\.\s+", markdown)
    return parts[1:]


def field_value(item: str, field: str) -> str:
    match = re.search(rf"^- {re.escape(field)}：(.+)$", item, flags=re.M)
    return match.group(1).strip() if match else ""


def source_family(source: str) -> str:
    lowered = source.lower()
    if "hugging face" in lowered:
        return "Hugging Face"
    if "github" in lowered:
        return "GitHub"
    if "hacker news" in lowered:
        return "News"
    if "reddit" in lowered:
        return "Community"
    if "product hunt" in lowered:
        return "Product Hunt"
    return "Other"


def audit(markdown: str) -> list[str]:
    errors: list[str] = []
    items = split_items(markdown)
    if not (10 <= len(items) <= 20):
        errors.append(f"线索数量应在 10-20 条之间，当前 {len(items)} 条。")

    all_links = re.findall(r"https?://\S+", markdown)
    bad_links = [url for url in all_links if url.count("http://") + url.count("https://") > 1]
    if bad_links:
        errors.append(f"发现疑似坏链接：{bad_links[:3]}")

    for idx, item in enumerate(items, 1):
        missing = [field for field in REQUIRED_FIELDS if not field_value(item, field)]
        if missing:
            errors.append(f"第 {idx} 条缺少字段：{', '.join(missing)}")
        raw = field_value(item, "原始信号")
        if len(raw) < 25:
            errors.append(f"第 {idx} 条原始信号太短，无法复核。")
        conclusion = field_value(item, "结论")
        if not any(word in conclusion for word in ["值得", "观察", "记录", "深挖"]):
            errors.append(f"第 {idx} 条结论没有明确判断。")

    families = [source_family(field_value(item, "来源")) for item in items]
    family_counts = Counter(families)
    if len(family_counts) < 2:
        errors.append(f"来源过于单一：{dict(family_counts)}")
    if len(items) >= 15 and family_counts.get("GitHub", 0) > 12:
        errors.append(f"GitHub 来源过多：{family_counts.get('GitHub', 0)} / {len(items)}，不符合新词站/Hugging Face 优先策略。")
    if family_counts.get("Hugging Face", 0) == 0:
        errors.append("缺少 Hugging Face 线索，不符合当前侧重点。")

    for phrase in GENERIC_BAD_PHRASES:
        count = markdown.count(phrase)
        if count >= 3:
            errors.append(f"模板化短语重复 {count} 次：{phrase}")

    tracked_fields = ["真实需求", "切入角度", "可做 MVP", "分发路径", "下一步验证"]
    for field in tracked_fields:
        values = [field_value(item, field) for item in items]
        repeated = [value for value, count in Counter(values).items() if value and count >= 3]
        if repeated:
            errors.append(f"字段“{field}”存在重复模板：{repeated[0][:80]}")

    deep_count = markdown.count("- 建议：深挖")
    observe_count = markdown.count("- 建议：观察")
    if deep_count == 0 and observe_count == 0:
        errors.append("没有任何深挖或观察建议，报告无法支持决策。")
    if deep_count > 5:
        errors.append(f"深挖建议过多：{deep_count} 条。日报应帮助聚焦，而不是把太多线索都标成高优先级。")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", nargs="?", default=str(ROOT / "daily" / f"{today_shanghai()}.md"))
    args = parser.parse_args()

    path = Path(args.report)
    if not path.exists():
        print(f"Report not found: {path}")
        return 1

    errors = audit(path.read_text(encoding="utf-8"))
    if errors:
        print("Report audit failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Report audit passed: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
