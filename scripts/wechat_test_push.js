#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token";
const TEMPLATE_SEND_URL = "https://api.weixin.qq.com/cgi-bin/message/template/send";

function readEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return {};
  const values = {};
  for (const line of fs.readFileSync(filePath, "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const match = trimmed.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!match) continue;
    values[match[1]] = match[2].replace(/^["']|["']$/g, "");
  }
  return values;
}

function configValue(name, sources) {
  for (const source of sources) {
    if (source[name]) return source[name];
  }
  return undefined;
}

function assertPresent(config, names) {
  const missing = names.filter((name) => !config[name]);
  if (missing.length) {
    throw new Error(`Missing required config: ${missing.join(", ")}`);
  }
}

async function getAccessToken(appId, appSecret) {
  const url = new URL(TOKEN_URL);
  url.searchParams.set("grant_type", "client_credential");
  url.searchParams.set("appid", appId);
  url.searchParams.set("secret", appSecret);

  const response = await fetch(url);
  const json = await response.json();
  if (!json.access_token) {
    throw new Error(`Failed to get WeChat access_token: ${safeJson(json)}`);
  }
  return json.access_token;
}

async function sendTemplateMessage({ accessToken, openid, templateId, content, detailUrl }) {
  const url = new URL(TEMPLATE_SEND_URL);
  url.searchParams.set("access_token", accessToken);

  const payload = {
    touser: openid,
    template_id: templateId,
    data: {
      xxx: { value: content },
    },
  };
  if (detailUrl) {
    payload.url = detailUrl;
  }

  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const json = await response.json();
  if (json.errcode !== 0) {
    throw new Error(`Failed to send WeChat template message: ${safeJson(json)}`);
  }
}

function todayInShanghai() {
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function readBrief(date) {
  const dailyPath = path.join(ROOT, "daily", `${date}.md`);
  if (fs.existsSync(dailyPath)) {
    return fs.readFileSync(dailyPath, "utf8").trim();
  }
  return [
    `# Alpha 需求线索日报｜${date}`,
    "",
    "今天的日报文件还不存在。可以先用这条测试消息确认微信推送链路。",
  ].join("\n");
}

function compactForWeChat(markdown, maxChars = 1500) {
  const text = markdown
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\*\*/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .trim();
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars - 48)}\n\n……内容较长，点击消息查看完整日报。`;
}

function summarizeForWeChat(markdown, detailUrl, maxChars = 1200) {
  const text = compactForWeChat(markdown, maxChars);
  if (!detailUrl) return text;
  return `${text}\n\n完整版本见详情链接。`;
}

function safeJson(value) {
  return JSON.stringify(value, (key, val) => {
    if (/token|secret|appid|openid/i.test(key)) return "[REDACTED]";
    return val;
  });
}

async function main() {
  const args = new Set(process.argv.slice(2));
  const dryRun = args.has("--dry-run");
  const testMessage = args.has("--test-message");

  const dotenv = readEnvFile(path.join(ROOT, ".env"));
  const sources = [process.env, dotenv];
  const config = {
    WECHAT_APP_ID: configValue("WECHAT_APP_ID", sources),
    WECHAT_APP_SECRET: configValue("WECHAT_APP_SECRET", sources),
    WECHAT_OPENID: configValue("WECHAT_OPENID", sources),
    WECHAT_TEMPLATE_ID: configValue("WECHAT_TEMPLATE_ID", sources),
    WECHAT_DETAIL_URL: configValue("WECHAT_DETAIL_URL", sources),
  };

  assertPresent(config, ["WECHAT_APP_ID", "WECHAT_APP_SECRET", "WECHAT_OPENID", "WECHAT_TEMPLATE_ID"]);

  const date = todayInShanghai();
  const content = testMessage
    ? `微信推送链路测试成功｜${date}\n\n如果你看到这条消息，说明 Alpha 需求线索日报的微信推送配置已经打通。`
    : summarizeForWeChat(readBrief(date), config.WECHAT_DETAIL_URL);

  if (dryRun) {
    console.log("Dry run passed. Required WeChat config is present. No secrets printed.");
    console.log(`Message length: ${content.length}`);
    return;
  }

  const accessToken = await getAccessToken(config.WECHAT_APP_ID, config.WECHAT_APP_SECRET);
  await sendTemplateMessage({
    accessToken,
    openid: config.WECHAT_OPENID,
    templateId: config.WECHAT_TEMPLATE_ID,
    content,
    detailUrl: config.WECHAT_DETAIL_URL,
  });
  console.log("WeChat template message sent.");
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
