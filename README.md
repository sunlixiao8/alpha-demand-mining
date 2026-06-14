# Alpha 需求挖掘

这个仓库用于每天采集、筛选和沉淀个人产品开发机会。

核心方法来自 4 节课程：

- 幸福的方式：从真实抱怨里找需求
- 功利的方式：从供需失衡里找机会
- Alpha 意识：持续捕捉窗口期
- 新词站：用网站承接新词带来的高意图搜索需求

## 每日节奏

- 时间：北京时间每天早上 08:00
- 目标：动态采集 10-20 条线索
- 阅读负担：每条约 3 分钟，总阅读约 20-30 分钟
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

## 安全约定

- 不把 API key 写入代码或 Markdown
- 如需使用 DeepSeek，后续通过环境变量 `DEEPSEEK_API_KEY` 读取
- 带商标/版权风险的新词机会必须标记风险，不默认建议做 EMD
- 04-07 课程 Markdown 是本地学习资料，不纳入 GitHub 推送范围

## GitHub Actions

工作流文件：`.github/workflows/daily-demand-mining.yml`

- `schedule`：每天 `00:00 UTC`，即北京时间 `08:00`
- `workflow_dispatch`：支持在 GitHub 页面手动触发
- 采集脚本：`scripts/collect_daily.py`
- 静态站构建：`scripts/build_daily_site.py`
- 自动提交范围：`daily/`、`data/`、`site/`
- 微信推送：`scripts/wechat_test_push.js`

如需微信推送，在 GitHub 仓库 `Settings > Secrets and variables > Actions` 配置：

- `WECHAT_APP_ID`
- `WECHAT_APP_SECRET`
- `WECHAT_OPENID`
- `WECHAT_TEMPLATE_ID`

工作流会把当天 GitHub Pages 日报链接作为 `WECHAT_DETAIL_URL` 自动传入。
