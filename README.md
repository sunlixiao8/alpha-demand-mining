# Alpha 需求挖掘

这个仓库用于每天采集、筛选和沉淀个人产品开发机会。

新版依据见 [需求文档](docs/需求文档.md) 和 [采集器规则](docs/采集器规则.md)。生产入口已切换为证据采集流程；旧采集辅助函数仅为历史兼容保留，不参与新版日报。

核心方法来自 4 节课程：

- 幸福的方式：从真实抱怨里找需求
- 功利的方式：从供需失衡里找机会
- Alpha 意识：持续捕捉窗口期
- 新词站：用网站承接新词带来的高意图搜索需求

## 每日节奏

- 时间：北京时间每天早上 08:00
- 数量：不设配额和最低条数；摘要展示重点，完整列表保留候选
- 判断：原始摘录、商业假设、未知事项分开，不再按关键词计算总分
- 输出位置：`daily/YYYY-MM-DD.md`
- 汇总表：`data/opportunities.csv`
- 当前策略：每日成果推送 GitHub；课程原文只留本地，不推送
- 运行方式：GitHub Actions 云端定时运行，电脑关机也能执行
- 页面输出：GitHub Pages 会构建 `site/` 静态页面，方便浏览日报

## 当前侧重点

第一优先级：

- 新词站机会
- Hugging Face Trending 新模型/新项目

第二优先级：

- AI 产品新闻窗口
- Google 搜索词机会
- GitHub Trending / Product Hunt / Hacker News
- Fiverr / Upwork 服务产品化
- 公开抱怨和差评

## 报告标准

日报按照“商业决策简报”来写，而不是简单列链接。原始池不会整批铺到页面；每条展示机会必须包含：

- 结论
- 可追溯的英文原文与紧随其后的中文翻译
- 为什么现在
- 用户是谁
- 真实需求
- 供需失衡
- 切入角度
- MVP
- 分发路径
- 变现方式
- 风险
- 下一步验证
- 置信度

## 安全约定

- 不把 API key 写入代码或 Markdown
- DeepSeek 使用环境变量 `DEEPSEEK_API_KEY`，模型为 `deepseek-flash`
- 带商标/版权风险的新词机会必须标记风险，不默认建议做 EMD
- 04-07 课程 Markdown 是本地学习资料，不纳入 GitHub 推送范围

## GitHub Actions

工作流文件：`.github/workflows/daily-demand-mining.yml`

- `schedule`：每天 `00:00 UTC`，即北京时间 `08:00`
- `workflow_dispatch`：支持在 GitHub 页面手动触发
- 采集脚本：`scripts/collect_daily.py`
- 测试用例：`tests/test_collect_daily.py`
- 日报审查：`scripts/audit_report.py`
- 静态站构建：`scripts/build_daily_site.py`
- 自动提交范围：`daily/`、`data/`、`site/`
- 微信推送：`scripts/wechat_test_push.js`

工作流先运行 Python 和微信格式测试，再采集、审查、发布。数量、来源与深挖条数不会阻断新版日报。全局失败保存诊断并尝试异常通知；微信失败不会阻止日报提交，但会明确标为未完成。

如需微信推送，在 GitHub 仓库 `Settings > Secrets and variables > Actions` 配置：

- `WECHAT_APP_ID`
- `WECHAT_APP_SECRET`
- `WECHAT_OPENID`
- `WECHAT_TEMPLATE_ID`

工作流会把当天 GitHub Pages 日报链接作为 `WECHAT_DETAIL_URL` 自动传入。

## 模型与覆盖状态

本地默认读取环境中的 DeepSeek key；不自动加载 `.env`。云端已获授权分析自动采集的公开网页摘录，模型开关已启用，需配置 Secret `DEEPSEEK_API_KEY`。私人笔记与手动导入不发送。

每次采集先保留完整原始池，再按各方法的证据规则统一排序，最多选 40 条交给 DeepSeek；不设分类比例。日报只展示模型完成且建议为“深挖”或“观察”的前 20 条，其余原始线索和分析结果仍保留在运行数据中。

无 key、关闭模型或分析失败时，保留证据并标为待分析，不输出虚假商业结论。搜索量、服务订单、竞品付费与 Roadmap 尚未自动接入，可手动导入公开证据，覆盖缺口显示在日报中。

```bash
python3 scripts/collect_daily.py --no-model
python3 scripts/audit_report.py
python3 scripts/build_daily_site.py
python3 -m unittest discover -s tests
node --test tests/wechat.test.js
```

可用 `--replay data/runs/YYYY-MM-DD.json` 重用已采集证据验证处理流程。公开历史在 `data/history.json`，每天的证据与来源状态在 `data/runs/`。

## 个人记录与公开证据

私人记录仅保存在被 Git 忽略的 `.local/notes.json`，不会进入公开日报或发往模型。机会编号显示在日报详情。

```bash
python3 -m scripts.opportunity add "我遇到的具体问题"
python3 -m scripts.opportunity add "验证记录" --id 机会编号 --status 验证中 --cost "时间或费用" --result "实际反馈"
python3 -m scripts.opportunity review
```

公开网页摘录可显式导入：

```bash
python3 -m scripts.opportunity import-public --title "机会名称" --url https://example.com --method 搜索词 --file /path/to/public-excerpt.txt
```

该命令将资料放入可发布的 `data/manual-evidence.json`；不要用于私人材料。此阶段私人反馈是本机命令行功能，尚无跨设备同步；跨来源语义合并仍需人工复核，当前自动去重按规范化链接。
