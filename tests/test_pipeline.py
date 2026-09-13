import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import mining


class MiningTest(unittest.TestCase):
    def sample(self, url='https://example.com/tool', text='Export invoices as CSV without manual copy and paste.'):
        return mining.evidence('Invoice export', url, 'manual', '个人抱怨', text)

    def test_same_url_tracking_and_fragment_are_one_identity(self):
        self.assertEqual(self.sample()['id'], self.sample('https://example.com/tool?utm_source=x#top')['id'])

    def test_no_description_is_not_recommended(self):
        item = self.sample(text='')
        self.assertEqual(mining.fallback(item)['recommendation'], '暂存')
        self.assertNotIn('深挖', str(mining.fallback(item)))

    def test_model_cannot_invent_evidence(self):
        item = self.sample()
        with self.assertRaises(ValueError):
            mining.validate_analysis({'evidence_ids': ['invented']}, [item])

    def test_history_rerun_and_metrics_do_not_create_new_opportunity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.json'
            item = self.sample()
            first = mining.update_history([item], path, '2026-09-12')
            self.assertEqual(first[0]['change'], '新增')
            item['metrics'] = {'likes': 8}
            second = mining.update_history([item], path, '2026-09-13')
            self.assertEqual(second[0]['change'], '无变化')
            item['raw'] += ' Now supports batch export.'
            third = mining.update_history([item], path, '2026-09-13')
            self.assertEqual(third[0]['change'], '更新')

    def test_partial_failure_and_zero_results_are_distinct(self):
        def broken():
            raise TimeoutError('timeout')
        result = mining.collect_sources({'empty': lambda: [], 'broken': broken})
        self.assertEqual(result['sources']['empty']['state'], '正常无结果')
        self.assertEqual(result['sources']['broken']['state'], '失败')

    def test_private_records_are_never_published(self):
        item = self.sample()
        item['private'] = True
        report = mining.render_report([item], {}, '2026-09-13')
        self.assertNotIn('Invoice export', report)

    def test_report_shows_at_most_twenty_analyzed_opportunities(self):
        items = []
        for i in range(25):
            item = self.sample(f'https://example.com/{i}')
            item['selected_for_analysis'] = True
            item['analysis_mode'] = 'model'
            item['analysis'] = self.analyzed(item)
            items.append(item)
        report = mining.render_report(items, {}, '2026-09-13')
        self.assertEqual(report.count('\n### '), 20)
        self.assertIn('原始线索：25 条', report)
        self.assertIn('日报展示：20 条', report)

    def test_empty_report_is_auditable(self):
        from scripts.audit_report import audit
        self.assertEqual(audit(mining.render_report([], {'x': {'state': '正常无结果', 'count': 0}}, '2026-09-13')), [])

    def test_valid_model_response_and_fabricated_quote(self):
        item = self.sample()
        value = self.analyzed(item)
        self.assertEqual(mining.validate_analysis(value, [item]), value)
        value['facts'][0]['quote'] = '100 paying customers'
        with self.assertRaises(ValueError):
            mining.validate_analysis(value, [item])

    def test_end_to_end_without_model(self):
        from scripts.audit_report import audit
        from scripts.build_daily_site import markdown_to_html
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(mining.sources, 'adapters', return_value={'test': lambda: [self.sample()]}):
                self.assertEqual(mining.run(root, use_model=False), 0)
            report = next((root / 'daily').glob('*.md')).read_text()
            self.assertEqual(audit(report), [])
            html = markdown_to_html(report)
            self.assertIn('进入 DeepSeek 分析：1 条', html)
            self.assertIn('日报展示：0 条', html)
            self.assertNotIn('href="https://example.com/tool"', html)
            self.assertTrue((root / 'data/history.json').exists())

    def test_all_failed_has_diagnostics_and_failure_exit(self):
        def broken():
            raise TimeoutError()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mining.sources, 'adapters', return_value={'test': broken}):
                self.assertEqual(mining.run(Path(tmp), use_model=False), 1)
            self.assertTrue(list((Path(tmp) / 'data/runs').glob('*.json')))

    def test_private_feedback_survives_public_run(self):
        from scripts.opportunity import record, review
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record(root / '.local', 'Private customer detail', status='验证中', result='feedback')
            with patch.object(mining.sources, 'adapters', return_value={'test': lambda: []}):
                mining.run(root, use_model=False)
            self.assertEqual(review(root / '.local')[0]['result'], 'feedback')
            self.assertNotIn('Private customer', next((root / 'daily').glob('*.md')).read_text())

    def test_extracted_text_excludes_styles_scripts_and_badges(self):
        from scripts.mining_sources import plain
        text = plain('<style>.noise { color: red; }</style><p>Export CSV</p><script>secret()</script>')
        self.assertEqual(text, 'Export CSV')

    def test_template_space_card_is_not_context(self):
        self.assertFalse(mining.has_context('Check out the configuration reference at https://huggingface.co/docs/hub/spaces-config-reference'))

    def test_model_protocol_is_grounded_and_uses_requested_name(self):
        import json
        item = self.sample()
        analysis = self.analyzed(item, recommendation='观察')
        response = json.dumps({'choices': [{'message': {'content': json.dumps({'analyses': [analysis]})}}]})
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'test-only', 'DEEPSEEK_MODEL': 'deepseek-flash'}):
            with patch.object(mining.sources, 'request', return_value=response) as request:
                result = mining.analyze_batch([item])
                self.assertEqual(request.call_args.args[1]['model'], 'deepseek-flash')
        self.assertEqual(result[item['id']]['recommendation'], '观察')

    def test_failed_batch_is_split_so_valid_items_survive(self):
        items = [self.sample(f'https://example.com/{i}') for i in range(4)]

        def analyze(batch):
            if len(batch) > 1:
                raise ValueError('one malformed analysis poisoned the batch')
            if batch[0] is items[-1]:
                raise ValueError('Unverifiable quotation')
            return {batch[0]['id']: self.analyzed(batch[0], recommendation='观察')}

        with patch.object(mining, 'analyze_batch', side_effect=analyze):
            mapping, errors = mining.analyze_resilient(items)
        self.assertEqual(set(mapping), {item['id'] for item in items[:-1]})
        self.assertEqual(errors, {items[-1]['id']: 'Unverifiable quotation'})

    def analyzed(self, item, recommendation='深挖'):
        value = mining.fallback(item)
        value.update({
            'title_zh': '发票导出工具',
            'recommendation': recommendation,
            'facts': [{
                'evidence_id': item['id'],
                'quote': 'Export invoices as CSV',
                'translation_zh': '将发票导出为 CSV',
            }],
        })
        return value

    def test_prefilter_caps_model_input_and_removes_thin_launches(self):
        useful = [
            self.sample(f'https://example.com/useful-{i}',
                        f'Users need to export invoices, replace manual copy and automate recurring billing workflow {i}.')
            for i in range(50)
        ]
        thin = mining.evidence('New launch', 'https://example.com/thin', 'Product Hunt', '待分类', 'Discussion | Link')
        selected, rejected = mining.prefilter(useful + [thin], limit=40)
        self.assertEqual(len(selected), 40)
        self.assertNotIn(thin, selected)
        self.assertIn(thin, rejected)

    def test_prefilter_uses_category_specific_evidence(self):
        technology = mining.evidence('Local model', 'https://example.com/model', 'Hugging Face models', '新技术',
                                     'A small on-device model reduces memory and inference cost for offline document processing.')
        complaint = mining.evidence('Export broken', 'https://example.com/complaint', 'Hacker News', '个人抱怨',
                                    'I pay for this service but CSV export keeps failing, so I copy every invoice manually.')
        service = mining.evidence('Translation service', 'https://example.com/service', '手动公开证据', '服务产品化',
                                  'Delivered 120 subtitle translation orders with the same input and output format.')
        selected, _ = mining.prefilter([technology, complaint, service], limit=40)
        self.assertEqual({x['id'] for x in selected}, {technology['id'], complaint['id'], service['id']})

    def test_explicit_demand_outranks_long_technology_marketing(self):
        technology = mining.evidence(
            'Large model launch', 'https://example.com/large-model', 'Hugging Face models', '新技术',
            ('Open source local multimodal model inference API with faster image video audio agent support. ' * 80),
        )
        complaint = mining.evidence(
            'CSV export keeps failing', 'https://example.com/export-failure', 'Hacker News', '个人抱怨',
            'I pay for this service, but CSV export keeps failing. I manually copy every invoice each week.',
        )
        self.assertGreater(mining.candidate_score(complaint), mining.candidate_score(technology))

    def test_unclassified_public_sources_are_typed_before_ranking(self):
        ask = mining.evidence('Ask HN: How do you export this?', 'https://example.com/ask',
                              'Hacker News', '待分类', 'I keep doing this manually every week.')
        show = mining.evidence('Show HN: Exporter', 'https://example.com/show',
                               'Hacker News', '待分类', 'A tool for recurring CSV exports.')
        news = mining.evidence('Vendor changes API pricing', 'https://example.com/news',
                               'Hacker News', '待分类', '评论 1: This is now too expensive.')
        launch = mining.evidence('Exporter', 'https://example.com/launch',
                                 'Product Hunt', '待分类', 'Automate recurring CSV export.')
        mining.prefilter([ask, show, news, launch])
        self.assertEqual([ask['method'], show['method'], news['method'], launch['method']],
                         ['个人抱怨', '暗影复刻', '新闻窗口', '暗影复刻'])

    def test_multi_comment_discussion_can_outrank_generic_technology(self):
        technology = mining.evidence(
            'Generic model', 'https://example.com/generic-model', 'Hugging Face models', '新技术',
            ('Open source local multimodal model inference API with faster agent support. ' * 40),
        )
        discussion = mining.evidence(
            'Vendor changes pricing', 'https://example.com/discussion', 'Hacker News', '待分类',
            '评论 1: It is too expensive.\n评论 2: We now export manually.\n评论 3: I need an alternative.',
        )
        mining.prefilter([technology, discussion])
        self.assertGreater(mining.candidate_score(discussion), mining.candidate_score(technology))

    def test_translation_is_required_and_english_precedes_chinese(self):
        item = self.sample()
        item['selected_for_analysis'] = True
        item['analysis_mode'] = 'model'
        item['analysis'] = self.analyzed(item)
        report = mining.render_report([item], {}, '2026-09-13')
        english = report.index('英文原文：Export invoices as CSV')
        chinese = report.index('中文翻译：将发票导出为 CSV')
        self.assertLess(english, chinese)
        del item['analysis']['facts'][0]['translation_zh']
        with self.assertRaises(ValueError):
            mining.validate_analysis(item['analysis'], [item])

    def test_translation_field_must_really_be_chinese(self):
        item = self.sample(text='一个开源工具')
        value = self.analyzed(item)
        value['facts'][0] = {
            'evidence_id': item['id'],
            'quote': '一个开源工具',
            'translation_zh': 'An open-source tool',
        }
        with self.assertRaisesRegex(ValueError, 'Chinese translation required'):
            mining.validate_analysis(value, [item])

    def test_model_state_counts_cached_and_new_valid_analyses(self):
        items = [self.sample(f'https://example.com/{i}') for i in range(2)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mapping = {items[0]['id']: self.analyzed(items[0], recommendation='观察')}
            with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'test-only'}):
                with patch.object(mining.sources, 'adapters', return_value={'test': lambda: items}):
                    with patch.object(mining, 'analyze_resilient', return_value=(mapping, {items[1]['id']: 'bad'})):
                        mining.run(root)
            saved = mining.load_json(next((root / 'data/runs').glob('*.json')), {})
            self.assertEqual(saved['sources']['模型分析']['state'], '部分失败')
            self.assertEqual(saved['sources']['模型分析']['count'], 1)

    def test_unanalyzed_candidates_are_not_dumped_into_report(self):
        items = [self.sample(f'https://example.com/{i}') for i in range(130)]
        report = mining.render_report(items, {}, '2026-09-13')
        self.assertEqual(report.count('\n### '), 0)
        self.assertIn('原始线索：130 条', report)
        self.assertIn('日报展示：0 条', report)

    def test_translated_report_passes_audit(self):
        from scripts.audit_report import audit
        item = self.sample()
        item['selected_for_analysis'] = True
        item['analysis_mode'] = 'model'
        item['analysis'] = self.analyzed(item)
        self.assertEqual(audit(mining.render_report([item], {}, '2026-09-13')), [])

    def test_end_to_end_handles_prefiltered_out_items(self):
        items = [self.sample(f'https://example.com/useful-{i}',
                             f'Users need recurring invoice export and batch workflow automation {i}.')
                 for i in range(45)]
        items.append(mining.evidence('Thin launch', 'https://example.com/thin', 'Product Hunt', '待分类', 'Discussion | Link'))
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mining.sources, 'adapters', return_value={'test': lambda: items}):
                self.assertEqual(mining.run(Path(tmp), use_model=False), 0)

    def test_new_analysis_is_a_change_even_when_source_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.json'
            item = self.sample()
            item['analysis_mode'] = 'pending'
            mining.update_history([item], path, '2026-09-12')
            item['analysis_mode'] = 'model'
            self.assertEqual(mining.update_history([item], path, '2026-09-13')[0]['change'], '分析完成')


if __name__ == '__main__':
    unittest.main()
