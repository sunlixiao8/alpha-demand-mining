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


def context_text(item: Signal) -> str:
    return re.sub(r"\s+", " ", f"{item.title}. {item.raw}").strip()


def display_subject(item: Signal) -> str:
    title = item.title.strip()
    if "/" in title and not title.lower().startswith("http"):
        return title.split("/")[-1].replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", title)


def keyword_flags(item: Signal) -> set[str]:
    text = context_text(item).lower()
    flags: set[str] = set()
    groups = {
        "agent": ["agent", "multi-agent", "autonomous"],
        "llm": ["llm", "gpt", "claude", "gemini", "deepseek", "model", "rag"],
        "image": ["image", "photo", "picture", "comfyui", "stable diffusion", "flux", "drawing"],
        "video": ["video", "shortvideo", "veo", "seedance", "sora"],
        "voice": ["voice", "tts", "speech", "audio", "podcast"],
        "docs": ["doc", "docs", "documentation", "readme", "wiki"],
        "workflow": ["workflow", "pipeline", "automation", "orchestration"],
        "security": ["guard", "security", "eval", "safety", "policy"],
        "design": ["design", "ui", "ux", "figma", "prototype"],
        "writing": ["writing", "copy", "content", "blog"],
        "local": ["local", "offline", "self-host", "self host", "desktop"],
    }
    for flag, words in groups.items():
        if any(word in text for word in words):
            flags.add(flag)
    return flags


def compact_raw(item: Signal, max_len: int = 180) -> str:
    text = re.sub(r"\s+", " ", item.raw).strip()
    if not text:
        return "暂无描述，先从标题和来源判断。"
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def evidence_sentence(item: Signal) -> str:
    text = context_text(item)
    if item.source.startswith("GitHub Search"):
        stars = re.search(r"Stars:\s*(\d+)", text)
        stars_text = f"短期内已有 {stars.group(1)} stars，" if stars else ""
        return f"{stars_text}且项目创建时间新，说明开发者圈已经开始围绕这个能力聚集注意力。原始描述：{compact_raw(item, 120)}"
    if "Hugging Face" in item.source:
        likes = re.search(r"Likes:\s*(\d+|None)", text)
        downloads = re.search(r"Downloads:\s*(\d+|None)", text)
        bits = []
        if downloads and downloads.group(1) != "None":
            bits.append(f"下载 {downloads.group(1)}")
        if likes and likes.group(1) != "None":
            bits.append(f"点赞 {likes.group(1)}")
        metric = "，".join(bits) if bits else "处在 Trending 列表"
        return f"Hugging Face 上 {metric}，适合判断是否存在模型能力到产品入口之间的空档。"
    if "Hacker News" in item.source:
        return "Hacker News 已出现讨论，说明早期开发者和技术买家开始关注；需要重点看评论里是否有人抱怨部署、成本或替代方案。"
    if "Reddit" in item.source:
        return "Reddit 社区帖子通常更接近真实使用场景；如果评论里反复出现同类不爽，就可以进入抱怨池。"
    if "Product Hunt" in item.source:
        return "Product Hunt 新品发布可用来观察用户是否愿意尝试同类产品，以及评论区是否暴露差异化切口。"
    return f"线索来自 {item.source}，需要继续核查搜索量、讨论密度和可交付性。"


def why_now_sentence(item: Signal) -> str:
    flags = keyword_flags(item)
    if "HF" in item.type:
        return "现在值得看，是因为模型/Space 进入 Trending 后，通常会先出现尝鲜搜索，再出现工具化供给。窗口很短。"
    if item.source.startswith("GitHub Search"):
        return "现在值得看，是因为它是近 10 天新出现的项目，适合抢在教程站、托管版和垂直模板变多之前判断入口。"
    if "News" in item.type:
        return "现在值得看，是因为新闻讨论先于成熟供给，适合做新词页、教程页或最小工具承接第一波搜索。"
    if "Complaint" in item.type:
        return "现在值得看，是因为用户已经在公开表达不爽，比问卷里的“我想要”更接近真实需求。"
    if "video" in flags or "image" in flags:
        return "现在值得看，是因为多模态生成能力变化快，用户更关心可直接交付的场景方案，而不是底层模型本身。"
    return "现在值得看，是因为它可能处在需求已经出现、供给还没充分产品化的早期阶段。"


def wedge_sentence(item: Signal) -> str:
    subject = display_subject(item)
    flags = keyword_flags(item)
    if "docs" in flags:
        return "切口不要做“大而全知识库”，先做 GitHub PR/Issue 文档更新这一刀，贴近开发者工作流。"
    if "video" in flags:
        return f"切口不要把 {subject} 做成通用视频生成器，先选一个高频模板，比如产品广告、TikTok 短剧分镜、课程切片。"
    if "image" in flags:
        return f"切口不要把 {subject} 做成通用出图站，先选一个能付费的垂直场景，比如电商主图、App Store 截图、角色设定图。"
    if "voice" in flags:
        return f"切口不要把 {subject} 做成普通 TTS，先做多语言短视频配音或课程旁白，一次解决文本、声音和下载。"
    if "agent" in flags:
        return f"切口不要做通用 Agent 平台，先把 {subject} 映射到一个窄流程，例如开发协作、内容运营、SEO 外链或客服质检。"
    if "design" in flags:
        return "切口不要做完整设计平台，先做“产品说明到首屏/组件稿”的窄场景，服务独立开发者。"
    if "HF" in item.type or "GitHub" in item.type:
        return f"切口可以是 {subject} 的托管 demo、中文/英文教程、新词站承接页或一键部署包。"
    return "切口要尽量小：只解决一个具体动作，先验证是否有人愿意留下邮箱、试用或付费。"


def distribution_sentence(item: Signal) -> str:
    subject = display_subject(item)
    flags = keyword_flags(item)
    if "video" in flags or "image" in flags:
        return f"分发靠 {subject} 的样例：把生成前后对比图/视频发到 X、小红书、Reddit、Product Hunt，再用模板页承接搜索。"
    if "docs" in flags:
        return "分发找开源项目维护者、SaaS changelog 场景和开发者工具社区，用免费开源仓库换私有仓库付费。"
    if "agent" in flags:
        return f"分发靠 {subject} 的案例：展示一个岗位任务从 30 分钟变 3 分钟，并把流程录屏发到 X、HN、独立开发者社区。"
    if "HF" in item.type:
        return "分发优先做新词 SEO：模型名 + demo/free/tutorial/API/alternative，同时去 Hugging Face 评论区、Reddit、X 发可用入口。"
    if item.source.startswith("GitHub Search") or "GitHub" in item.type:
        return f"分发从 {subject} 所在 GitHub 生态切入：README 对比页、Issue 评论、相关 repo discussion、开发者社区和教程文章。"
    return "分发先从来源社区反打回去，再补 SEO 页面承接长尾搜索。"


def validation_sentence(item: Signal) -> str:
    subject = display_subject(item)
    flags = keyword_flags(item)
    if "HF" in item.type:
        return "验证动作：今天建一个 landing page，标题包含模型/Space 名；放 3 个 demo 截图和 waitlist，看 24 小时点击/注册。"
    if "GitHub" in item.type:
        return f"验证动作：先读 {subject} 的 README 和 Issues，找 3 个部署/使用痛点；做一个教程页或 hosted demo，发到相关讨论区测点击。"
    if "video" in flags or "image" in flags:
        return f"验证动作：围绕 {subject} 做 5 个可展示样例，找 10 个目标用户问是否愿意为模板/批量生成付费。"
    if "docs" in flags:
        return "验证动作：找 5 个活跃开源 repo，手动生成一次 PR 文档更新，问维护者是否愿意接入 Action。"
    if "agent" in flags:
        return "验证动作：人工先跑 3 单，把输入、执行、交付过程记录下来，再判断哪些步骤能自动化。"
    return "验证动作：用一页纸说明问题、解法和价格，找 5 个目标用户确认是否愿意试用或预付。"


def decision_sentence(item: Signal) -> str:
    flags = keyword_flags(item)
    if item.score >= 21 and ("video" in flags or "image" in flags or "agent" in flags or "docs" in flags):
        return "值得今天进入深挖池。它有明确新技术信号，也能落到一个可收费的窄场景。"
    if item.score >= 21:
        return "值得深挖，但先别开工；需要补一轮搜索量、竞品和真实用户动作核查。"
    if item.score >= 18:
        return "适合观察和做轻量验证。先用页面/样例测兴趣，不建议直接重投入开发。"
    return "暂时只记录。除非后续出现搜索增长或重复抱怨，否则不进入开发队列。"


def confidence_sentence(item: Signal) -> str:
    raw_len = len(item.raw.strip())
    if item.source.startswith("GitHub Search") and raw_len > 80:
        return "中高：有项目描述和热度指标，但还缺用户评论与搜索量。"
    if "Hugging Face" in item.source:
        return "中：Trending 是早期信号，但要继续核查 demo 质量、license 和普通用户是否真的会搜。"
    if "Hacker News" in item.source or "Reddit" in item.source:
        return "中：有讨论信号，但需要阅读评论确认是不是具体痛点。"
    return "低到中：需要补充更多证据。"


def quality_gate(item: Signal) -> bool:
    if not item.url.startswith("http"):
        return False
    if "fetch failed" in item.title.lower():
        return False
    text = context_text(item).lower()
    if any(risky in text for risky in ["therapist", "medical diagnosis", "investment advice"]):
        item.score = min(item.score, 15)
    if "GitHub" in item.type or "HF" in item.type:
        return bool(keyword_flags(item)) and len(item.raw.strip()) >= 30
    if "News" in item.type or "Complaint" in item.type:
        return is_relevant_ai_text(text)
    return True


def need_sentence(item: Signal) -> str:
    subject = display_subject(item)
    flags = keyword_flags(item)
    if "docs" in flags:
        return f"围绕 {subject} 做“代码/PR 自动生成用户文档”的轻量工具，解决小团队文档总是落后的问题。"
    if "video" in flags:
        return f"把 {subject} 这类视频生成/短视频流水线包装成面向创作者的模板化工具，而不是让用户自己拼脚本。"
    if "image" in flags:
        return f"把 {subject} 这类图像生成能力收敛到具体场景，例如商品图、角色图、封面图或工作流模板。"
    if "voice" in flags:
        return f"把 {subject} 这类语音/TTS 能力做成可直接试用的配音、播客、客服话术或本地化工具。"
    if "agent" in flags and "workflow" in flags:
        return f"把 {subject} 的 Agent/工作流能力产品化，帮用户完成一个明确任务，而不是只展示框架。"
    if "agent" in flags:
        return f"围绕 {subject} 做垂直 Agent：选一个岗位或场景，把通用 Agent 变成可交付的流程。"
    if "writing" in flags:
        return f"把 {subject} 包装成特定人群的写作/改写/发布助手，重点解决风格和流程问题。"
    if "design" in flags:
        return f"围绕 {subject} 做设计交付辅助工具，帮助非设计团队快速得到可用界面或素材。"
    if "security" in flags:
        return f"把 {subject} 做成 AI 应用安全/评测/策略检查工具，服务正在上线 Agent 的团队。"
    if "HF Trending" in item.type or "GitHub Trending" in item.type:
        return f"把 {subject} 从开源项目/模型变成一个普通用户可直接使用的托管入口或模板。"
    if "News" in item.type:
        return f"围绕“{subject}”这个新讨论点，快速承接教程、试用、替代方案或新词站流量。"
    if "Complaint" in item.type:
        return f"从“{subject}”背后的社区不爽里，找到一个更快、更便宜或更简单的替代动作。"
    if "Product" in item.type:
        return f"拆解 {subject} 的核心任务，找一个更垂直、更轻量或更便宜的 20% 版本。"
    return f"判断 {subject} 背后是否存在明确任务和供需失衡。"


def user_sentence(item: Signal) -> str:
    flags = keyword_flags(item)
    if "video" in flags:
        return "短视频创作者、出海营销团队、内容工作室、需要批量生成视频素材的小团队。"
    if "image" in flags:
        return "电商卖家、设计外包团队、游戏/角色创作者、需要稳定出图流程的独立开发者。"
    if "voice" in flags:
        return "播客/短视频创作者、课程团队、客服团队、做多语言内容本地化的人。"
    if "docs" in flags:
        return "频繁改代码但文档维护跟不上的开源作者、SaaS 小团队和开发者工具团队。"
    if "agent" in flags:
        return "想把重复流程交给 AI 的创业团队、运营人员、开发者和个人效率工具用户。"
    if "design" in flags:
        return "缺少专业设计资源的小型开发团队、独立开发者和 SaaS MVP 团队。"
    if "HF" in item.type or "GitHub" in item.type:
        return "AI 应用开发者、独立开发者、内容创作者、需要把模型能力落地到具体任务的人。"
    if "Complaint" in item.type:
        return "正在公开求助、吐槽或寻找替代方案的早期用户。"
    if "Product" in item.type:
        return "正在试用同类工具、但可能觉得太贵、太重或场景不够贴合的小团队。"
    return "追新技术、追效率工具、需要立即解决具体任务的早期采用者。"


def gap_sentence(item: Signal) -> str:
    subject = display_subject(item)
    flags = keyword_flags(item)
    if "local" in flags:
        return f"{subject} 可能满足本地/离线需求，但部署和配置门槛高，普通用户缺少一键安装和默认工作流。"
    if "video" in flags:
        return "视频生成需求很热，但用户通常卡在提示词、镜头脚本、批处理、模型选择和成片交付。"
    if "image" in flags:
        return "图像生成能力多，但垂直行业模板、稳定风格、批量生成和后处理仍然供给不足。"
    if "docs" in flags:
        return "团队知道文档重要，但 PR 合并后文档经常滞后；现有方案要么太重，要么没有贴进 GitHub 流程。"
    if "agent" in flags:
        return f"{subject} 证明 Agent 生态还在快速长新工具，但多数仍停留在开发者框架，缺少面向具体业务动作的交付层。"
    if "HF" in item.type:
        return "模型能力可能已经出现，但普通用户缺少稳定入口、清晰场景、低门槛 UI 和可付费包装。"
    if "GitHub" in item.type:
        return f"{subject} 这类开源项目通常有技术势能，但部署、示例、文档和产品化入口还不够顺。"
    if "News" in item.type:
        return "信息热度先于产品供给，窗口期内用户会主动搜索入口、教程和替代方案。"
    return "现有供给可能存在慢、贵、复杂、场景不聚焦或缺少自动化的问题。"


def mvp_sentence(item: Signal) -> str:
    subject = display_subject(item)
    flags = keyword_flags(item)
    if "docs" in flags:
        return "做 GitHub App/Action：用户在 PR 评论里触发，自动生成 changelog、README 片段和用户文档草稿。"
    if "video" in flags:
        return f"围绕 {subject} 做一个“输入主题→脚本→镜头提示词→生成队列”的单页工具，先支持 3 个固定视频模板。"
    if "image" in flags:
        return f"围绕 {subject} 做一个场景化生成页：固定 5-10 个模板、示例图和参数预设，先收集邮箱或 credits 付费。"
    if "voice" in flags:
        return f"围绕 {subject} 做一个上传文本即可生成多语音版本的 demo，附带字幕/音频下载和按分钟计费。"
    if "agent" in flags:
        return f"选 {subject} 最明显的一个任务，做表单输入 + 后台脚本/半自动 Agent + 结果交付。"
    if "design" in flags:
        return "做“上传产品说明→生成 landing page 首屏/组件稿”的最小工具，先服务独立开发者。"
    if "HF" in item.type or "GitHub" in item.type:
        return "48 小时内做一个承接页 + Demo/教程 + 等候名单；能调用则做最小可用 Web 工具。"
    if "News" in item.type:
        return "做新词承接页、教程页、资源导航、替代入口或轻量转换/生成工具。"
    if "Complaint" in item.type:
        return "先做单一痛点的表单、脚本、插件或半自动服务，验证是否有人愿意试用/付费。"
    return "做一个只解决核心任务的轻量页面或工作流，先收集真实反馈。"


def monetization_sentence(item: Signal) -> str:
    flags = keyword_flags(item)
    if "video" in flags or "image" in flags or "voice" in flags:
        return "credits 按生成次数收费，外加 Pro 订阅解锁批量、高清、商用模板和队列优先级。"
    if "docs" in flags:
        return "按仓库/席位订阅，或按 PR 次数计费；开源免费、私有仓库收费。"
    if "agent" in flags or "workflow" in flags:
        return "按任务包、月度订阅或托管执行次数收费；早期可用人工兜底提高交付率。"
    if "HF" in item.type or "GitHub" in item.type:
        return "订阅、credits、托管版、API 加价、模板包或部署服务。"
    if "News" in item.type:
        return "一次性付费、订阅、credits、导流联盟、咨询/安装服务。"
    if "Complaint" in item.type:
        return "一次性解决费、订阅、自动化服务包或按结果收费。"
    return "订阅、一次性收费、模板售卖或增值服务。"


def risk_sentence(item: Signal) -> str:
    flags = keyword_flags(item)
    if "video" in flags or "image" in flags or "voice" in flags:
        return "生成成本、版权/商用授权和同质化竞争是主要风险，需要用垂直场景避开纯工具内卷。"
    if "docs" in flags:
        return "需要接入代码仓库权限，信任成本较高；先用 GitHub Action 或只读权限降低阻力。"
    if "agent" in flags:
        return "Agent 演示容易惊艳但交付不稳定；MVP 要限制任务边界并保留人工兜底。"
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
        lines.append(f"- 结论：{decision_sentence(item)}")
        lines.append(f"- 原始信号：{compact_raw(item)}")
        lines.append(f"- 证据：{evidence_sentence(item)}")
        lines.append(f"- 为什么现在：{why_now_sentence(item)}")
        lines.append(f"- 用户是谁：{user_sentence(item)}")
        lines.append(f"- 真实需求：{need_sentence(item)}")
        lines.append(f"- 供需失衡：{gap_sentence(item)}")
        lines.append(f"- 切入角度：{wedge_sentence(item)}")
        lines.append(f"- 可做 MVP：{mvp_sentence(item)}")
        lines.append(f"- 分发路径：{distribution_sentence(item)}")
        lines.append(f"- 变现方式：{monetization_sentence(item)}")
        lines.append(f"- 风险：{risk_sentence(item)}")
        lines.append(f"- 下一步验证：{validation_sentence(item)}")
        lines.append(f"- 置信度：{confidence_sentence(item)}")
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
    existing_rows: list[dict[str, str]] = []
    fieldnames = [
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
    ]
    if CSV_PATH.exists():
        with CSV_PATH.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            existing_rows = [row for row in reader if row.get("date") != today]
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing_rows)
        for item in signals[:20]:
            writer.writerow({
                "date": today,
                "title": item.title,
                "type": item.type,
                "source": item.source,
                "url": item.url,
                "user": user_sentence(item),
                "need": need_sentence(item),
                "supply_gap": gap_sentence(item),
                "mvp": mvp_sentence(item),
                "monetization": monetization_sentence(item),
                "risk": risk_sentence(item),
                "score": item.score,
                "status": recommendation(item.score),
            })


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
    signals = [item for item in signals if quality_gate(item)]
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
