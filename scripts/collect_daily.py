#!/usr/bin/env python3
"""Daily demand-signal collector.

Runs on GitHub Actions, writes:
- daily/YYYY-MM-DD.md
- data/opportunities.csv

No API keys are required for v1.
"""

from __future__ import annotations

import csv
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DAILY_DIR = ROOT / "daily"
DATA_DIR = ROOT / "data"
CSV_PATH = DATA_DIR / "opportunities.csv"

USER_AGENT = (
    "Mozilla/5.0 (compatible; AlphaDemandMining/1.0; "
    "+https://github.com/sunlixiao/alpha-demand-mining)"
)


@dataclass
class Signal:
    title: str
    url: str
    source: str
    type: str
    raw: str = ""
    score: int = 0


def fetch_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def absolute(base: str, href: str) -> str:
    return urllib.parse.urljoin(base, href)


def clean_url(url: str) -> str:
    url = (url or "").strip()
    if url.count("https://") > 1:
        second = url.find("https://", 8)
        return url[second:]
    if url.count("http://") > 1:
        second = url.find("http://", 7)
        return url[second:]
    return url


def dedupe(signals: list[Signal]) -> list[Signal]:
    seen: set[str] = set()
    result: list[Signal] = []
    for item in signals:
        key = re.sub(r"\W+", "", (item.title + item.url).lower())
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def collect_huggingface() -> list[Signal]:
    url = "https://huggingface.co/api/models?sort=trending&limit=30"
    try:
        data = json.loads(fetch_text(url))
    except Exception as exc:
        return [Signal("Hugging Face Trending fetch failed", url, "Hugging Face", "HF Trending", str(exc), 8)]

    signals: list[Signal] = []
    for model in data:
        model_id = model.get("modelId") or model.get("id")
        if not model_id or "/" not in model_id:
            continue
        tags = ", ".join(model.get("tags") or [])
        downloads = model.get("downloads")
        likes = model.get("likes")
        raw = f"Trending model. Tags: {tags}. Downloads: {downloads}. Likes: {likes}."
        signals.append(
            Signal(
                title=model_id,
                url=f"https://huggingface.co/{model_id}",
                source="Hugging Face Trending",
                type="HF Trending",
                raw=raw,
            )
        )
    return signals


def collect_huggingface_spaces() -> list[Signal]:
    url = "https://huggingface.co/api/spaces?sort=trending&limit=20"
    try:
        data = json.loads(fetch_text(url))
    except Exception:
        return []

    signals: list[Signal] = []
    for space in data:
        space_id = space.get("id") or space.get("modelId")
        if not space_id or "/" not in space_id:
            continue
        tags = ", ".join(space.get("tags") or [])
        signals.append(
            Signal(
                title=space_id,
                url=f"https://huggingface.co/spaces/{space_id}",
                source="Hugging Face Spaces Trending",
                type="HF Trending",
                raw=f"Trending Space/demo. Tags: {tags}. Strong candidate for wrapper, hosted demo, tutorial, or new-word landing page.",
            )
        )
    return signals


def collect_github_trending() -> list[Signal]:
    url = "https://github.com/trending?since=daily"
    try:
        text = fetch_text(url)
    except Exception as exc:
        return [Signal("GitHub Trending fetch failed", url, "GitHub", "GitHub Trending", str(exc), 8)]

    blocks = re.findall(r'<h2 class="h3 lh-condensed">(.+?)</h2>', text, flags=re.S)
    signals: list[Signal] = []
    for block in blocks[:12]:
        match = re.search(r'href="([^"]+)"', block)
        if not match:
            continue
        href = match.group(1)
        title = strip_tags(block).replace(" / ", "/").replace(" ", "")
        if not is_relevant_ai_text(title):
            continue
        signals.append(
            Signal(
                title=title,
                url=absolute("https://github.com", href),
                source="GitHub Trending",
                type="GitHub Trending",
                raw="Daily trending repository. Look for productizable workflows, wrappers, hosted demos, or deployment pain.",
            )
        )
    return signals


def collect_github_ai_search() -> list[Signal]:
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).strftime("%Y-%m-%d")
    queries = [
        f"llm created:>={since}",
        f"ai-agent created:>={since}",
        f"image-generation created:>={since}",
        f"video-generation created:>={since}",
        f"tts created:>={since}",
        f"mcp created:>={since}",
    ]
    signals: list[Signal] = []
    for query in queries:
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
            {"q": query, "sort": "stars", "order": "desc", "per_page": "8"}
        )
        try:
            data = json.loads(fetch_text(url))
        except Exception:
            continue
        for repo in data.get("items", [])[:5]:
            name = repo.get("full_name")
            html_url = repo.get("html_url")
            desc = repo.get("description") or ""
            stars = repo.get("stargazers_count")
            if not name or not html_url:
                continue
            signals.append(
                Signal(
                    title=name,
                    url=html_url,
                    source=f"GitHub Search: {query}",
                    type="GitHub Trending",
                    raw=f"{desc} Stars: {stars}. Newly created AI-related repo; check deployment, demo, and productization gaps.",
                )
            )
    return signals


def collect_hackernews() -> list[Signal]:
    signals: list[Signal] = []
    queries = ["AI", "LLM", "agent", "model", "image generation", "video generation", "Hugging Face"]
    for query in queries:
        url = (
            "https://hn.algolia.com/api/v1/search_by_date?"
            + urllib.parse.urlencode({"query": query, "tags": "story"})
        )
        try:
            data = json.loads(fetch_text(url))
        except Exception:
            continue
        for hit in data.get("hits", [])[:4]:
            title = hit.get("title") or hit.get("story_title")
            link = clean_url(hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}")
            if not title or not link or not is_relevant_ai_text(title):
                continue
            signals.append(
                Signal(
                    title=title,
                    url=link,
                    source=f"Hacker News: {query}",
                    type="News Window",
                    raw="Fresh tech discussion. Check comments for complaints, missing tooling, and early adopter workflows.",
                )
            )
    return signals


def collect_reddit() -> list[Signal]:
    subreddits = ["LocalLLaMA", "SideProject", "SaaS", "ArtificialInteligence"]
    signals: list[Signal] = []
    for sub in subreddits:
        url = f"https://www.reddit.com/r/{sub}/hot.json?limit=8"
        try:
            data = json.loads(fetch_text(url))
        except Exception:
            continue
        for child in data.get("data", {}).get("children", [])[:5]:
            post = child.get("data", {})
            title = post.get("title")
            permalink = post.get("permalink")
            if not title or not permalink or not is_relevant_ai_text(title):
                continue
            signals.append(
                Signal(
                    title=title,
                    url=absolute("https://www.reddit.com", permalink),
                    source=f"Reddit r/{sub}",
                    type="Complaint / Community Pain",
                    raw="Community post. Prefer posts asking for alternatives, complaining about setup, cost, quality, or workflow gaps.",
                )
            )
    return signals


def collect_producthunt() -> list[Signal]:
    url = "https://www.producthunt.com/feed"
    try:
        text = fetch_text(url)
    except Exception:
        return []
    items = re.findall(r"<item>(.+?)</item>", text, flags=re.S)
    signals: list[Signal] = []
    for item in items[:10]:
        title = strip_tags(re.search(r"<title>(.+?)</title>", item, flags=re.S).group(1)) if re.search(r"<title>(.+?)</title>", item, flags=re.S) else ""
        link = strip_tags(re.search(r"<link>(.+?)</link>", item, flags=re.S).group(1)) if re.search(r"<link>(.+?)</link>", item, flags=re.S) else ""
        if not title or not link:
            continue
        signals.append(
            Signal(
                title=title,
                url=link,
                source="Product Hunt",
                type="Product Launch",
                raw="New product launch. Compare positioning, pricing, user comments, and gaps for shadow-replication ideas.",
            )
        )
    return signals


def is_relevant_ai_text(text: str) -> bool:
    lowered = text.lower()
    keywords = [
        "ai",
        "llm",
        "agent",
        "model",
        "gpt",
        "claude",
        "gemini",
        "deepseek",
        "hugging",
        "mcp",
        "rag",
        "image",
        "video",
        "voice",
        "tts",
        "speech",
        "prompt",
        "workflow",
        "automation",
        "generate",
        "generator",
    ]
    return any(keyword in lowered for keyword in keywords)


def classify_and_score(item: Signal) -> Signal:
    title = item.title.lower()
    raw = item.raw.lower()
    text = f"{title} {raw}"

    score = 10
    if item.type in {"HF Trending", "GitHub Trending"}:
        score += 4
    if any(x in text for x in ["agent", "llm", "model", "image", "video", "tts", "voice", "workflow", "generate", "generator"]):
        score += 3
    if any(x in text for x in ["open source", "github", "hugging face", "demo", "api"]):
        score += 2
    if any(x in text for x in ["alternative", "free", "tool", "template", "maker", "online", "tutorial"]):
        score += 3
    if any(x in text for x in ["complain", "hard", "difficult", "expensive", "slow", "broken", "can't", "cannot"]):
        score += 2
    if item.type == "Product Launch":
        score += 1
    item.score = min(score, 25)

    if item.type == "HF Trending":
        item.type = "HF Trending / New Tech"
    elif item.type == "GitHub Trending":
        item.type = "GitHub Trending / New Tech"
    return item


def need_sentence(item: Signal) -> str:
    if "HF Trending" in item.type or "GitHub Trending" in item.type:
        return "把新模型/开源能力包装成普通用户可直接使用的工具、模板或托管工作流。"
    if "News" in item.type:
        return "围绕刚出现的技术/平台变化，快速承接教程、试用、迁移、替代或生成类需求。"
    if "Complaint" in item.type:
        return "从社区讨论中提取反复出现的不爽，寻找更快、更便宜、更简单的替代方案。"
    if "Product" in item.type:
        return "观察新产品发布背后的用户任务，寻找更垂直、更轻量或更便宜的 20% 版本。"
    return "判断该线索背后是否存在明确任务和供需失衡。"


def user_sentence(item: Signal) -> str:
    if "HF" in item.type or "GitHub" in item.type:
        return "AI 应用开发者、独立开发者、内容创作者、需要把模型能力落地到具体任务的人。"
    if "Complaint" in item.type:
        return "正在公开求助、吐槽或寻找替代方案的早期用户。"
    if "Product" in item.type:
        return "正在试用同类工具、但可能觉得太贵、太重或场景不够贴合的小团队。"
    return "追新技术、追效率工具、需要立即解决具体任务的早期采用者。"


def gap_sentence(item: Signal) -> str:
    if "HF" in item.type:
        return "模型能力可能已经出现，但普通用户缺少稳定入口、清晰场景、低门槛 UI 和可付费包装。"
    if "GitHub" in item.type:
        return "开源项目通常部署、配置、文档和产品化不足，适合做托管版、模板版或垂直版。"
    if "News" in item.type:
        return "信息热度先于产品供给，窗口期内用户会主动搜索入口、教程和替代方案。"
    return "现有供给可能存在慢、贵、复杂、场景不聚焦或缺少自动化的问题。"


def mvp_sentence(item: Signal) -> str:
    if "HF" in item.type or "GitHub" in item.type:
        return "48 小时内做一个承接页 + Demo/教程 + 等候名单；能调用则做最小可用 Web 工具。"
    if "News" in item.type:
        return "做新词承接页、教程页、资源导航、替代入口或轻量转换/生成工具。"
    if "Complaint" in item.type:
        return "先做单一痛点的表单、脚本、插件或半自动服务，验证是否有人愿意试用/付费。"
    return "做一个只解决核心任务的轻量页面或工作流，先收集真实反馈。"


def monetization_sentence(item: Signal) -> str:
    if "HF" in item.type or "GitHub" in item.type:
        return "订阅、credits、托管版、API 加价、模板包或部署服务。"
    if "News" in item.type:
        return "一次性付费、订阅、credits、导流联盟、咨询/安装服务。"
    if "Complaint" in item.type:
        return "一次性解决费、订阅、自动化服务包或按结果收费。"
    return "订阅、一次性收费、模板售卖或增值服务。"


def risk_sentence(item: Signal) -> str:
    if "News" in item.type:
        return "热度衰减快；若涉及品牌词或商标，避免长期做 EMD，必要时转向自有品牌。"
    if "HF" in item.type or "GitHub" in item.type:
        return "技术可能只是短期热度；需要确认 license、模型可用性、成本和真实工作流。"
    return "需求可能不够高频；需要验证是否是一类人反复出现的问题。"


def recommendation(score: int) -> str:
    if score >= 21:
        return "深挖"
    if score >= 16:
        return "观察"
    return "丢弃/低优先级"


def build_report(signals: list[Signal], today: str) -> str:
    top = signals[:20]
    if len(top) < 10:
        top = signals

    lines: list[str] = []
    lines.append(f"# {today} 需求线索日报")
    lines.append("")
    lines.append("## 今日摘要")
    lines.append("")
    lines.append(f"- 采集线索：{len(top)} 条")
    lines.append("- 重点权重：新词站、Hugging Face Trending、GitHub 新技术机会")
    lines.append("- 筛选原则：宁可少于 20 条，也不硬凑低质量内容")
    lines.append("")
    lines.append("## Top 10-20 线索")
    lines.append("")

    for idx, item in enumerate(top, 1):
        demand = 4 if item.score >= 18 else 3
        gap = 4 if item.score >= 17 else 3
        alpha = 5 if ("HF" in item.type or "GitHub" in item.type) else 4
        mvp = 4
        money = 4 if item.score >= 18 else 3
        total = min(item.score, demand + gap + alpha + mvp + money)
        item.score = total

        lines.append(f"### {idx}. {item.title}")
        lines.append("")
        lines.append(f"- 来源：{item.source}")
        lines.append(f"- 链接：{item.url}")
        lines.append(f"- 类型：{item.type}")
        lines.append(f"- 一句话需求：{need_sentence(item)}")
        lines.append(f"- 用户是谁：{user_sentence(item)}")
        lines.append(f"- 供需失衡：{gap_sentence(item)}")
        lines.append(f"- 可做 MVP：{mvp_sentence(item)}")
        lines.append(f"- 变现方式：{monetization_sentence(item)}")
        lines.append(f"- 风险：{risk_sentence(item)}")
        lines.append(
            f"- 评分：需求强度 {demand} / 供给缺口 {gap} / Alpha 时效 {alpha} / "
            f"MVP 可行性 {mvp} / 变现潜力 {money}，总分 {total}"
        )
        lines.append(f"- 建议：{recommendation(total)}")
        lines.append("")

    lines.append("## 今日最值得深挖的 1-3 个方向")
    lines.append("")
    for idx, item in enumerate(top[:3], 1):
        lines.append(f"{idx}. {item.title}：{mvp_sentence(item)}")
    lines.append("")
    lines.append("## 明日观察关键词")
    lines.append("")
    for item in top[:5]:
        keyword = re.sub(r"[^A-Za-z0-9 /.-]", "", item.title).strip()[:80]
        lines.append(f"- {keyword}")
    lines.append("")
    return "\n".join(lines)


def append_csv(signals: list[Signal], today: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    exists = CSV_PATH.exists()
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow([
                "date",
                "title",
                "type",
                "source",
                "url",
                "user",
                "need",
                "supply_gap",
                "mvp",
                "monetization",
                "risk",
                "score",
                "status",
            ])
        for item in signals[:20]:
            writer.writerow([
                today,
                item.title,
                item.type,
                item.source,
                item.url,
                user_sentence(item),
                need_sentence(item),
                gap_sentence(item),
                mvp_sentence(item),
                monetization_sentence(item),
                risk_sentence(item),
                item.score,
                recommendation(item.score),
            ])


def main() -> int:
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    collectors = [
        collect_huggingface,
        collect_huggingface_spaces,
        collect_github_trending,
        collect_github_ai_search,
        collect_hackernews,
        collect_reddit,
        collect_producthunt,
    ]

    signals: list[Signal] = []
    for collector in collectors:
        try:
            signals.extend(collector())
        except Exception as exc:
            signals.append(Signal(f"{collector.__name__} failed", "", "Collector", "Error", str(exc), 5))
        time.sleep(1)

    signals = [classify_and_score(item) for item in dedupe(signals)]
    signals.sort(key=lambda item: item.score, reverse=True)

    selected = signals[:20] if len(signals) >= 20 else signals[: max(10, len(signals))]
    DAILY_DIR.mkdir(exist_ok=True)
    report_path = DAILY_DIR / f"{today}.md"
    report_path.write_text(build_report(selected, today), encoding="utf-8")
    append_csv(selected, today)
    print(f"Wrote {report_path} with {len(selected)} signals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
