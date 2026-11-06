# StarTrace（GitHub 热门项目每日邮件推送）

每天自动抓取 [GitHub Trending](https://github.com/trending?since=daily) 的每日热门项目，推送到你的邮箱。

**版本**：v1.0.0 ｜ **作者**：Guozhengkun（guozhengkun@tju.edu.cn）

StarTrace 1.0.0 是首个正式版本。它会整理 GitHub Trending 项目并通过邮件发送日报，也支持选择本地翻译或云大模型翻译。使用云服务商的 API 时，请留意其计费规则。

## 软件版（推荐）

桌面上的 `StarTrace.exe` 即完整软件，**无需安装 Python**，双击即用：

- Win11 风格界面：圆角卡片、胶囊按钮、浅色主题
- 在界面内直接填写邮箱 / 授权码 / 收件人 / 语言 / 数量 / 推送时间
- 一键「保存配置」「预览今日榜单」「立即发送邮件」「开启 / 取消定时推送」
- 可在设置中提前下载并准备翻译模型，首页和运行记录会显示下载进度
- 点击首页 StarTrace 可查看作者头像、版本和数据来源；弹窗标题栏使用 StarTrace 图标
- 运行日志实时显示，可一键打开所在文件夹、查看日志文件
- 支持静默模式（供定时任务调用）：`StarTrace.exe --send`
- StarTrace 标题可点击查看作者和版本；关闭主窗口后程序收至 Windows 系统托盘
- 邮件简介使用 Index-Translate 2B 本地翻译模型；首次翻译时从 ModelScope 国内源下载约 1.31 GB，下载完成后离线运行。下载过程中显示进度，建议预留 4 GB 可用内存
- 中文简介默认开启；可在设置中关闭，并选择本地模型或云大模型翻译
- 在线 API 密钥写入当前 Windows 用户的凭据管理器；地址和模型名称保存在普通配置中

## 从源码运行与打包

使用 Python 3.10 或更新版本，在项目目录打开终端后运行：

```bat
python main.py
```

打包 Windows 单文件程序：

```bat
pyinstaller --noconfirm --clean StarTrace.spec
```

生成的程序位于 `dist\StarTrace.exe`，PyInstaller 的中间构建目录为 `build\StarTrace`。

> 定时任务指向 exe 自身，**不要移动或删除桌面上的 exe**，否则定时推送会失效（重新「开启定时推送」即可指向新位置）。

## 命令行版

适合喜欢命令行或服务器环境的用户：

```bat
python send_trending.py                      # 抓取并发送
python send_trending.py --dry-run            # 只预览榜单
python send_trending.py --install-task       # 注册每日定时任务
python send_trending.py --uninstall-task     # 取消定时任务
```

## 快速开始（4 步）

### 第 1 步：在软件界面填写邮箱信息

首次运行请在软件界面填写邮箱信息并点击「保存配置」。SMTP 授权码会保存在当前 Windows 用户的凭据管理器中，不会以明文写入 `config.json`。旧版配置会尝试在首次读取时迁移；如果 Windows 当前登录会话不允许访问凭据管理器，请在界面重新填写授权码并保存。

命令行版需要先在软件界面保存一次 SMTP 授权码，再运行下面的命令。

配置文件只保存非敏感设置，例如：

```json
{
  "smtp": {
    "host": "smtp.qq.com",
    "port": 465,
    "user": "你的QQ邮箱@qq.com"
  },
  "to": ["收件邮箱@example.com"],
  "language": "all",
  "top_n": 25,
  "send_time": "09:00"
}
```

首次翻译需要联网下载 Index-Translate 2B 模型（约 1.31 GB）和本地推理组件；下载完成后，简介翻译可离线使用。模型采用 Apache 2.0 许可，详见 [模型卡](https://huggingface.co/IndexTeam/Index-Translate-2B-GGUF)；推理组件 llama.cpp 采用 MIT 许可。

| 字段 | 说明 |
|---|---|
| `smtp.host / port` | 发件邮箱 SMTP 服务器，见下方常用邮箱对照表 |
| `smtp.user` | 发件邮箱地址 |
| SMTP 授权码 | 在软件中填写；保存在 Windows 凭据管理器，不写入配置文件 |
| `to` | 收件邮箱，可填多个：`["a@xx.com", "b@xx.com"]` |
| `language` | 筛选语言，如 `python`、`javascript`、`go`、`rust`；填 `all` 表示全部 |
| `top_n` | 每次推送的项目数量，默认 25 |
| `send_time` | 每天推送时间（24 小时制），默认 09:00 |

### 常用邮箱 SMTP 对照表

| 邮箱 | host | port | 授权码获取方式 |
|---|---|---|---|
| QQ 邮箱 | smtp.qq.com | 465 | 设置 → 账户 → 开启「SMTP 服务」→ 生成授权码 |
| 网易 163 | smtp.163.com | 465 | 设置 → POP3/SMTP → 开启 → 设置客户端授权密码 |
| 网易 126 | smtp.126.com | 465 | 同上 |
| Gmail | smtp.gmail.com | 465 | 需开启两步验证 → 生成「应用专用密码」（国内网络需代理） |
| Outlook/微软 | smtp-mail.outlook.com | 587 | 账户设置中开启 SMTP（587 端口走 STARTTLS，脚本已自动适配） |

> 收件箱和发件箱可以是同一个邮箱，比如都用你自己的 QQ 邮箱，零成本自收自发。

### 第 2 步：先预览榜单（不发邮件）

```bat
python send_trending.py --dry-run
```

### 第 3 步：测试发送一封邮件

```bat
python send_trending.py
```

看到 `[OK] 邮件已发送到：...` 即成功，去邮箱查收。

### 第 4 步：注册每日定时任务

```bat
python send_trending.py --install-task
```

默认每天 `09:00` 自动运行（也可 `--time 08:30` 指定其他时间）。之后每天到点自动抓取并推送，全程后台静默，无窗口弹出。

## 其他命令

| 命令 | 作用 |
|---|---|
| `python send_trending.py --install-task --time 18:30` | 指定每天 18:30 推送 |
| `python send_trending.py --uninstall-task` | 取消定时推送 |
| `python send_trending.py --dry-run` | 只看今天的榜单，不发邮件 |
| `python send_trending.py` | 立即抓取并发送 |

日志记录在 `send_trending.log`，排障时查看。

## 常见问题

1. **`SMTPAuthenticationError`（535 错误）**：授权码错误，或邮箱未开启 SMTP 服务。重新生成授权码后填入。
2. **`ConnectionRefusedError` / SSL 错误**：多为网络或代理问题。确认 host/port 与上表一致；Gmail 在国内直连常失败，建议用 QQ/163 邮箱。
3. **抓取失败**：脚本会自动切换到 GitHub Search API 备用方案，仍可正常推送。
4. **定时任务没运行**：任务注册为「用户登录时运行」，需要电脑开机且已登录 Windows。若想关机也能跑，需在任务计划程序中为任务设置「不管用户是否登录都要运行」并填写 Windows 密码（或使用服务器/云函数方案）。
5. **推送时间不精确**：任务计划程序是整点触发，误差一般在 1 分钟以内；若电脑当时处于睡眠状态，会在唤醒后补跑一次。

## 提示

- 想换不同语言或数量，直接改 `config.json` 即可，不用改代码。
- 想用 5 分钟版跑通：先填好 config → `--dry-run` 看榜单 → 正式跑一次收到邮件 → `--install-task` 收工。
