# PancakeSwap 申购活动监测

自动监测 @PancakeSwap 的 X（Twitter）账号，发现新的 IFO / Pre-Access / Launchpad / 新币申购活动时发送邮件通知。

## 功能

- 每4小时自动监测 @PancakeSwap 最新推文
- 关键词匹配：IFO、Pre-Access、Launchpad、token sale、申购、新币、发售等
- 发现新申购活动时立即发送邮件通知
- 自动去重，避免重复通知

## 配置

在 GitHub Secrets 中配置：

- `EMAIL_PASSWORD`：QQ邮箱授权码（不是登录密码）

## 本地运行

```bash
pip install playwright requests
playwright install chromium
python monitor_pancakeswap.py
```

## 关键词列表

IFO、Initial Farm Offering、Pre-Access、Launchpad、token sale、subscription、whitelist、public sale、申购、新币、发售、众筹、白名单、预售等。

## 注意事项

- 使用 Playwright 渲染 X 页面抓取推文
- 状态保存在 GitHub Cache 中
- 仅供研究参考
