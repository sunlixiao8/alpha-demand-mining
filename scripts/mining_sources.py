"""Public evidence adapters. No opportunity claims are generated here."""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser


def request(url, payload=None, headers=None, timeout=18):
    merged = {'User-Agent': 'AlphaDemandMining/2.0', 'Accept': 'application/json'}
    merged.update(headers or {})
    if payload is not None:
        merged['Content-Type'] = 'application/json'
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=merged)
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read(2_000_000).decode('utf-8', errors='replace')
        except Exception:
            if attempt:
                raise
            time.sleep(0.5)


def get_json(url):
    headers = {}
    if urllib.parse.urlsplit(url).hostname == 'api.github.com' and os.getenv('GITHUB_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GITHUB_TOKEN']
    return json.loads(request(url, headers=headers))


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('style', 'script', 'svg'):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ('style', 'script', 'svg') and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value):
    parser = TextExtractor()
    parser.feed(value or '')
    return re.sub(r'\s+', ' ', ' '.join(parser.parts)).strip()


def hf(kind='models'):
    from .mining import evidence
    data = get_json(f'https://huggingface.co/api/{kind}?sort=trendingScore&limit=20&full=true')
    if not isinstance(data, list):
        raise ValueError('Unexpected Hugging Face response')
    def one(row):
        name = row['id']
        prefix = '' if kind == 'models' else 'spaces/'
        url = f'https://huggingface.co/{prefix}{name}'
        card_url = f'{url}/raw/main/README.md'
        item = evidence(name, url, 'Hugging Face ' + kind, '新技术', '', row.get('createdAt', ''))
        item['metrics'] = {k: row[k] for k in ('likes', 'downloads') if k in row}
        try:
            card = request(card_url)
            card = re.sub(r'^---\s*\n.*?\n---\s*\n', '', card, flags=re.S)
            item['raw'] = plain(card)[:5000]
            item['evidence_url'] = card_url
        except Exception:
            item['context_state'] = '模型卡获取失败，待补证据'
        return item
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(one, data))


def github():
    from .mining import evidence
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).date().isoformat()
    query = urllib.parse.urlencode({'q': f'created:>={since} stars:>=5 topic:ai', 'sort': 'stars', 'per_page': 30})
    data = get_json('https://api.github.com/search/repositories?' + query)
    def one(row):
        name = row['full_name']
        item = evidence(name, row['html_url'], 'GitHub', '新技术', row.get('description') or '', row.get('created_at', ''))
        item['metrics'] = {'stars': row.get('stargazers_count', 0)}
        readme_url = f"https://raw.githubusercontent.com/{name}/{row['default_branch']}/README.md"
        try:
            item['raw'] = plain(request(readme_url))[:5000]
            item['evidence_url'] = readme_url
        except Exception:
            item['context_state'] = '仅项目描述；README 未获取'
        return item
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(one, data['items']))


def hackernews():
    from .mining import evidence
    since = int(time.time()) - 3 * 86400
    query = urllib.parse.urlencode({'tags': 'story', 'numericFilters': f'created_at_i>{since},num_comments>2', 'hitsPerPage': 30})
    data = get_json('https://hn.algolia.com/api/v1/search_by_date?' + query)
    def one(hit):
        discussion = f"https://news.ycombinator.com/item?id={hit['objectID']}"
        item = evidence(hit['title'], discussion, 'Hacker News', '待分类', plain(hit.get('story_text')), hit.get('created_at', ''))
        item['related_url'] = hit.get('url') or ''
        try:
            detail = get_json(f"https://hn.algolia.com/api/v1/items/{hit['objectID']}")
            comments = [f"评论 {x['id']}: {plain(x.get('text'))}" for x in detail.get('children', [])[:5] if x.get('text')]
            item['raw'] = (plain(detail.get('text')) + '\n' + '\n'.join(comments)).strip()[:5000]
        except Exception:
            item['context_state'] = '正文或评论获取失败'
        return item
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(one, data['hits']))


def reddit():
    from .mining import evidence
    data = get_json('https://www.reddit.com/r/SaaS+SideProject+LocalLLaMA/new.json?limit=30')
    return [evidence(x['data']['title'], 'https://www.reddit.com' + x['data']['permalink'],
                     'Reddit', '个人抱怨', plain(x['data'].get('selftext')),
                     dt.datetime.fromtimestamp(x['data']['created_utc'], dt.timezone.utc).isoformat())
            for x in data['data']['children']]


def producthunt():
    from .mining import evidence
    root = ET.fromstring(request('https://www.producthunt.com/feed'))
    rows = root.findall('.//item') or root.findall('{http://www.w3.org/2005/Atom}entry')
    def value(row, name):
        return row.findtext(name) or row.findtext('{http://www.w3.org/2005/Atom}' + name) or ''
    result = []
    for row in rows[:30]:
        link = value(row, 'link')
        if not link:
            element = row.find('{http://www.w3.org/2005/Atom}link')
            link = element.get('href', '') if element is not None else ''
        if link:
            result.append(evidence(value(row, 'title'), link, 'Product Hunt', '待分类',
                                   plain(value(row, 'description') or value(row, 'summary') or value(row, 'content')),
                                   value(row, 'pubDate') or value(row, 'published')))
    return result


def adapters():
    return {'Hugging Face models': lambda: hf('models'), 'Hugging Face spaces': lambda: hf('spaces'),
            'GitHub': github, 'Hacker News': hackernews, 'Reddit': reddit, 'Product Hunt': producthunt}
