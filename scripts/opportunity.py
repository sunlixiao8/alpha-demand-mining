"""Private personal notes and feedback. Never used by the public publisher."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import uuid
from pathlib import Path

from scripts.mining import ROOT, METHODS, evidence, load_json, save_json, now


def record(directory, text, opportunity_id='', status='关注', cost='', result=''):
    path = directory / 'notes.json'
    records = load_json(path, [])
    entry = {'id': uuid.uuid4().hex[:16], 'at': now(), 'text': text,
             'opportunity_id': opportunity_id, 'status': status, 'cost': cost, 'result': result}
    records.append(entry)
    save_json(path, records)
    return entry


def review(directory, days=7):
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    return [x for x in load_json(directory / 'notes.json', []) if dt.datetime.fromisoformat(x['at']) >= cutoff]


def main():
    parser = argparse.ArgumentParser(description='私人抱怨、验证反馈与周复盘')
    sub = parser.add_subparsers(dest='command', required=True)
    add = sub.add_parser('add')
    add.add_argument('text')
    add.add_argument('--id', default='')
    add.add_argument('--status', choices=['关注', '验证中', '继续', '暂缓', '放弃'], default='关注')
    add.add_argument('--cost', default='')
    add.add_argument('--result', default='')
    sub.add_parser('review')
    public = sub.add_parser('import-public', help='Explicitly import public source evidence, never personal notes')
    public.add_argument('--title', required=True)
    public.add_argument('--url', required=True)
    public.add_argument('--method', choices=METHODS, required=True)
    public.add_argument('--file', type=Path, required=True, help='UTF-8 public excerpt')
    args = parser.parse_args()
    directory = ROOT / '.local'
    if args.command == 'add':
        value = record(directory, args.text, args.id, args.status, args.cost, args.result)
        print('已保存到本机私人记录：' + value['id'])
    elif args.command == 'review':
        print(json.dumps(review(directory), ensure_ascii=False, indent=2))
    else:
        item = evidence(args.title, args.url, '手动公开证据', args.method, args.file.read_text(encoding='utf-8'))
        path = ROOT / 'data' / 'manual-evidence.json'
        rows = [x for x in load_json(path, []) if x['id'] != item['id']]
        save_json(path, rows + [item])
        print('已导入公开证据：' + item['id'])


if __name__ == '__main__':
    main()
