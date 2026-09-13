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

    def test_single_source_more_than_twenty_not_capped(self):
        items = [self.sample(f'https://example.com/{i}') for i in range(25)]
        report = mining.render_report(items, {}, '2026-09-13')
        self.assertEqual(report.count('\n### '), 25)
        self.assertNotIn('总分', report)

    def test_empty_report_is_auditable(self):
        from scripts.audit_report import audit
        self.assertEqual(audit(mining.render_report([], {'x': {'state': '正常无结果', 'count': 0}}, '2026-09-13')), [])

    def test_valid_model_response_and_fabricated_quote(self):
        item = self.sample()
        value = mining.fallback(item)
        value['recommendation'] = '深挖'
        value['facts'] = [{'evidence_id': item['id'], 'quote': 'Export invoices as CSV'}]
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
            self.assertIn('href="https://example.com/tool"', markdown_to_html(report))
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
        analysis = mining.fallback(item)
        analysis['facts'] = [{'evidence_id': item['id'], 'quote': 'Export invoices as CSV'}]
        analysis['recommendation'] = '观察'
        response = json.dumps({'choices': [{'message': {'content': json.dumps({'analyses': [analysis]})}}]})
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'test-only', 'DEEPSEEK_MODEL': 'deepseek-flash'}):
            with patch.object(mining.sources, 'request', return_value=response) as request:
                result = mining.analyze_batch([item])
                self.assertEqual(request.call_args.args[1]['model'], 'deepseek-flash')
        self.assertEqual(result[item['id']]['recommendation'], '观察')

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
