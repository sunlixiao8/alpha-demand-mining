const test = require('node:test');
const assert = require('node:assert/strict');
const { summarizeForWeChat, readBrief, safeJson } = require('../scripts/wechat_test_push');

test('phone summary excludes full candidate list and markers', () => {
  const text = summarizeForWeChat('# report\n<!-- evidence-report-v2 -->\n## 今日摘要\n今天无新增\n## 来源覆盖\nprivate tail', 'https://example.com');
  assert.ok(text.includes('今天无新增'));
  assert.ok(!text.includes('private tail'));
  assert.ok(!text.includes('<!--'));
});
test('missing report must not masquerade as delivery success', () => {
  assert.throws(() => readBrief('1900-01-01'), /missing/);
});
test('secrets are redacted', () => {
  assert.ok(!safeJson({ access_token: 'hidden', secret: 'hidden' }).includes('hidden'));
});
