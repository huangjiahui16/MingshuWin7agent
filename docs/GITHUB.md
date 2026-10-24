# 上传 GitHub 前必须做的事（明枢Win7）

一句话结论：**只删 API Key 不够。** 你这个目录里还有四类东西不能进公开仓库。

| 类别 | 位置 | 为什么不能传 |
|---|---|---|
| API Key | `data/assistant.ini`、`api.md` | 传上去等于替别人付账单，爬虫几分钟就能扫到 |
| 聊天记录 | `data/sessions/`、`data/sessions.json` | 里面可能有你的文件路径、工作内容、隐私 |
| 长期记忆 | `data/facts.json`、`记忆.md` | 记的是你的习惯、目录、项目约定 |
| 便携运行时 | `runtime/`（约 117MB） | GitHub 单文件上限 100MB，直接拒绝推送 |

`.gitignore` 已经把上面这些全挡住了（包括 `api.md` 和 `记忆.md`）。你只要不 `git add -f` 强行加，就不会不小心传上去。

## 一、第一次上传（照抄即可）

```bat
cd /d F:\jiyu\zuixing\ai
git init
git add .
git status
```

**停下来看 `git status` 的输出**：列表里如果出现 `data/`、`api.md`、`记忆.md`、`runtime/`、`*.exe`，说明 `.gitignore` 没生效，先别 commit。

确认干净后再继续：

```bat
git commit -m "明枢Win7: Win7 上的桌面 Agent（源码）"
git branch -M main
git remote add origin https://github.com/你的用户名/仓库名.git
git push -u origin main
```

## 二、exe 放哪里

exe 已经 10MB 左右，但它会随每次改动变大，不要放进仓库历史。两种做法：

1. **Releases**（推荐）：网页上 New release → 上传 `明枢Win7.exe`、`明枢Win7-x86.exe`；
2. 或者建 `dist` 分支只放二进制，主分支不含 exe。

## 三、别人 clone 下来怎么跑

因为 `runtime/` 和 `data/` 都不在仓库里，README 里要写清楚：

```bat
:: 1) 装 Python 3.8（Win7 最后一个能用的版本）
:: 2) 复制配置模板
copy docs\assistant.example.ini data\assistant.ini
copy docs\api.md.example api.md
:: 3) 填 Key，然后启动
start-gui.bat
```

## 四、几个容易翻车的点

- **文件名有中文**（`记忆.md`、`明枢Win7.exe`）：Windows 上没问题，但部分 CI/老 git 会乱码。介意就把仓库里改成 ASCII 名（`MEMORY.md`），本地保留中文。
- **提交前扫一遍密钥**：运行 `python docs\check_no_secrets.py`，它会扫出形似 Key 的字符串并列出文件。
- **图标版权**：`assets/mingshu.ico` 用的是你提供的图，公开仓库要么标注来源/授权，要么换成自己画的。
- **不要提交 `crash.log` / `fault.log`**：里面含完整调用栈和本机路径。
- **公开仓库等于公开源码**：`src/` 里的提示词、工具清单都会被人看到，如果不希望暴露，就把仓库设为私有。

## 五、想发一个"能直接下载就用"的版本

在仓库根目录执行（只复制必要的文件到干净目录，再在那个目录里 git init）：

```bat
python docs\make_release_copy.py
```

它会生成 `release_copy\`：只含 `src/ docs/ skills/ assets/ start-*.bat .gitignore`，
并自动检查里面还能不能搜到 Key。

---

## 仓库简介（Repository Description，350 字符上限）

复制下面任一版，粘到仓库首页右侧 About 的齿轮里。中文 257 字符、英文 347 字符，都在限制内。

**中文：**

```
运行在 Windows 7 SP1 上的桌面 Agent：一句中文说出目标，它自己规划多步、调用工具、看结果再决定下一步——整理文件、读 Office/PDF 文档、查网络、跑命令。纯 Python 标准库（tkinter 自绘界面），不要 Electron / Node / .NET，4G 内存、机械硬盘、32 位老机都能跑。三道内核级资源墙（Job 内存上限、空闲 CPU 优先级、后台 I/O）+ 审批闸 + 越界必询问 + 审计日志 + 熔断，随时可中断、可降级。不绑厂商，任意 OpenAI 兼容接口。
```

**English：**

```
Desktop agent for Windows 7 SP1: say a goal in plain words, it plans the steps, calls tools, reads the results and decides next. File cleanup, Office/PDF reading, network and shell tasks. Stdlib only (tkinter), no Electron/Node/.NET; 4GB RAM and 32-bit OK. Kernel-level resource walls, approval gate, audit log, breaker. Any OpenAI-compatible API.
```

## Topics（标签，比简介更容易被搜到）

在 About 齿轮里把这几个逐个加进 Topics：

```
windows7  windows-7  desktop-agent  ai-agent  llm  tkinter  python3-8  openai-compatible  deepseek  automation  legacy-hardware  no-dependencies
```

## 首版 Release 填写建议

- Tag：`v25`
- Release title：`v25 — 首个可用版本（Win7 SP1 / x86 + x64）`
- 附件：`明枢Win7-v25.exe`（64 位）、`明枢Win7-x86-v25.exe`（32 位）
- 说明里写清：首次运行会被 360/火绒拦（程序没签名，加白名单即可）；老机器若报 TLS 握手失败，需打 KB3140245 + KB931125。
