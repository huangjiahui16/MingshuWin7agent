<img width="690" height="391" alt="image" src="https://github.com/user-attachments/assets/86bbc125-2a08-4040-aef3-2e441e57ee32" /># 明枢Win7（MingShu Win7）
<img width="1109" height="754" alt="image" src="https://github.com/user-attachments/assets/312e2606-1590-4d93-872b-b51c6e86d2e9" />

**简体中文**  |
[English](README.md)
<img width="897" height="711" alt="image" src="https://github.com/user-attachments/assets/7487fde0-d5b3-49dc-a7bf-b60a97ec8773" />

<img width="1116" height="755" alt="image" src="https://github.com/user-attachments/assets/76484037-aede-44c3-9f01-c88cdbd60644" />



一个能在 **Windows 7 SP1** 上跑起来的桌面 Agent：你用中文说一句话，它自己去操作电脑——整理文件、读文档、查网络、跑命令，每一步都可以拦、可以看、可以中断。

- **纯标准库**：界面用 tkinter 自绘，零第三方依赖（不需要 Electron / Node / .NET）
- **真·智能体**：会自己规划多步、调用工具、看结果、再决定下一步，最后汇报
- **安全优先**：三道内核级资源墙 + 审批闸 + 越界必询问 + 审计日志 + 熔断
- **能跑就行**：单机、无 GPU、4G 内存、机械硬盘、32 位系统都能用

> 模型在云端（任意 OpenAI 兼容接口），本机只负责工具执行与安全管控。
> 不绑定厂商：DeepSeek / 通义千问 / Kimi / OpenAI / 本地 Ollama / LM Studio 都行。

---

## 一、系统要求

| 项 | 要求 |
|---|---|
| 系统 | Windows 7 SP1 及以上（32 位 / 64 位均可） |
| Python | 源码运行需要 **3.8**（Win7 支持的最后一个版本）；用 exe 则不需要装 Python |
| 内存 | 4GB 起（程序自身被限制在 300MB 以内） |
| 显卡 | 不需要，无 GPU 依赖 |
| 网络 | 需要能访问你配置的模型接口 |

---

## 二、快速开始

### 方式 A：直接下 exe（推荐给普通用户）

到 **Releases** 页面下载：

- `明枢Win7.exe` —— 64 位系统
- `明枢Win7-x86.exe` —— 32 位系统

双击运行。首次启动会在同目录生成 `data\`（配置、会话、日志都在这），然后在「设置 → 模型接口」里填 API Key 即可。

### 方式 B：从源码运行（开发/自定义）

```bat
:: 1) 装 Python 3.8（安装时勾选 Add to PATH）
:: 2) 复制配置模板
copy docs\assistant.example.ini data\assistant.ini
copy docs\api.md.example api.md
:: 3) 打开 data\assistant.ini 填 api_key（或启动后在设置里填）
:: 4) 启动
start-gui.bat
```

命令行模式：`start-cli.bat`（无界面，适合服务器/脚本调用）。

---

## 三、配置

### 1. 设置面板（最省事）

界面上点「设置」，可改：接口地址、API Key、模型名、代理、思考档位、工具结果长度、最大步数、工作目录、权限档位、长期记忆、技能与记忆的强制开关。

两个开关（强制执行 Skill / 强制固定记忆）**改完立即生效，不需要重启**；只有正在跑的那一轮会沿用旧设置，结束后自动切到新值。

### 2. `api.md`（多模型预设）

程序根目录的 `api.md` 是一份**人可以直接改**的模型清单，设置面板里也是读它、并写回它：

```ini
# 当前使用：deepseek

[deepseek]
label = DeepSeek（便宜、中文好）
base_url = https://api.deepseek.com/v1
api_key = sk-你的Key
model = deepseek-flash

[qwen]
label = 通义千问
base_url = https://dashscope.aliyuncs.com/compatible-mode/v1
api_key = 
model = qwen-plus

# 想预留别的模型，整段用 # 注释掉即可，随时解开
#[local]
#base_url = http://127.0.0.1:1234/v1
#model = qwen2.5-7b-instruct
```

设置面板里选预设 → 点「载入预设」，字段就填好了；想确认能不能连通，点**「测试连通」**（发一个 `max_tokens=1` 的最小请求，把结果写回面板）。

### 3. `data\assistant.ini`（高级项）

常用几个：

```ini
[llm]
base_url = https://api.deepseek.com/v1
api_key = 
model = deepseek-flash
thinking = off          ; 思考档位 off/low/high/max

[agent]
workspace =             ; 限定可操作的目录，留空 = 整台电脑
perm_gear = ask         ; auto/ask/strict/locked
max_steps = 6           ; 单任务最多几步
mem_limit_mb = 300      ; 内存墙
max_procs = 4           ; 子进程上限
cpu_wall = thread       ; thread（只降工作线程）/ process（整进程 IDLE）

[memory]
enabled = true
```

---

## 四、怎么用

### 三种模式

| 模式 | 能干什么 |
|---|---|
| **Agent** | 全工具：列目录、读文件、搜索、跑命令、写文件、打开文件、抓网页 |
| **Plan** | 只读：只能看不能改，适合先分析后动手 |
| **Ask** | 纯聊天：不调用任何工具，最省 token |

### 四档权限

| 档位 | 行为 |
|---|---|
| 🟢 自动 | L0/L1（只读、写 logs）免打扰；L2/L3 仍会问你 |
| 🟡 询问 | 到 L2 免打扰；L3（动系统）必须明确授权 |
| 🟠 严格 | 只放行只读，其余直接拒绝 |
| 🔴 锁死 | 全部拒绝 |

**工作区之外的操作一律弹窗询问**，不受档位影响——这条也不能被长期记忆里的话覆盖。

### 快捷键

| 按键 | 作用 |
|---|---|
| `Enter` | 发送 |
| `Shift+Enter` | 换行 |
| `Esc` | 停止当前任务 |
| `Ctrl+K` | 命令面板 |
| `Ctrl+Alt+Q` | 在任意窗口中断当前任务（抢鼠标场景用） |
| `Ctrl+V` | 粘贴剪贴板里的**文件**或**截图**（自动变附件，带缩略图；鼠标悬停看大图） |

聊天记录里的路径、英文名：**双击即可整段选中并复制**；右键菜单还能复制整条 / 复制当前行 / 全选。

### 右下角提醒

窗口被最小化或切到别的程序时，任务有结果会在屏幕右下角弹一条：

- ✓ 绿 — 任务完成（附结论摘要）
- **? 黄 — 需要你确认**（工作区外操作等，不会自动消失，等你处理）
- ! 红 — 出错了
- i 蓝 — 定时任务跑完了

点一下就回到主窗口。你正盯着界面的时候不会弹。

### 长期记忆

- 说「记住：我每周五下午交周报」→ 存进长期记忆，之后每轮都会带上
- 也可以直接改根目录的 `记忆.md`（一行一条，`#` 开头是注释）
- 每个对话的记忆互相隔离，删掉会话会连它学到的记忆一起清掉
- 不想用就把设置里的「强制固定记忆」关掉（立即生效，不注入也不保存）

### 技能库（skills）

`skills\` 下每个文件夹是一个技能，模型按 `SKILL.md` 里的描述判断什么时候该用它。仓库自带 7 个：

| 技能 | 什么时候用 |
|---|---|
| `win7-files` | 整理文件、批量改名、清理、找大文件/重复文件 |
| `office-docs` | 读/写 Word、Excel、PPT，从文档里抽文字和表格 |
| `net-diag` | 上不了网、接口连不上、DNS/代理/TLS 排查 |
| `system-check` | 看系统信息、判断兼容性、排查卡顿 |
| `git-github` | 提交代码、整理仓库、准备上传 GitHub |
| `win7-pitfall` | 写脚本前查 Win7 的坑（编码、路径、DPI、TLS） |
| `pdf-extract` | 从 PDF 提取文字，判断是不是扫描件 |

**自己加技能**：新建 `skills\你的技能名\SKILL.md`，开头写上描述就行：

```markdown
---
name: my-skill
description: 一句话说清什么时候该用这个技能（模型靠这句话判断）
---

# 正文：具体步骤、命令、注意事项
```

**删技能**：直接删对应文件夹。改完不用重启，下一轮对话就会重新扫描。

### 中英文界面

左下角「对话」上方有语言按钮，点一下整个界面（含帮助页、按钮、提示、右下角通知）立刻切成英文，**模型也会改用英文回答**；选择会记在 `data\ui_state.json`，下次打开沿用。第一次运行默认中文。

---

## 五、安全设计（为什么它不会搞坏你的机器）

| 机制 | 说明 |
|---|---|
| **内存墙** | Job Object：本程序超过 300MB，内核直接杀进程；同时最多 4 个子进程 |
| **CPU 墙** | 工作线程降到空闲优先级（-15），你一碰键鼠它就排到最后 |
| **I/O 墙** | 工作线程切后台 I/O 模式，前台程序永远优先 |
| **审批闸** | 卡在工具注册层，模型绕不过去；工作区之外一律问人 |
| **审计日志** | 每次工具调用都记一笔（谁、什么级别、批准还是拒绝） |
| **熔断** | 危险操作 >5 次、写文件 >200 个、工具调用 >60 次 → 转只读，需要人工恢复 |
| **快照** | 写文件/删除前备份，可从备份恢复 |
| **可中断** | 界面上有「打断」，任何窗口都能按 `Ctrl+Alt+Q` |

---

## 六、目录结构

```
明枢Win7.exe / 明枢Win7-x86.exe   发布用二进制（自己打包才有）
start-gui.bat / start-cli.bat     源码启动脚本
api.md                            模型预设（自己填 Key，别提交到仓库）
记忆.md                            长期记忆（一行一条）
src\                              源码
  wb_app.py                         界面（tkinter 自绘）
  win7_assistant.py                 引擎（主循环 / 工具 / 权限 / 协议）
  win7_limits.py                    三道资源墙 + 分段计时
assets\                           图标
skills\                           技能库
docs\                             说明文档、模板、性能报告、上传清单
tests\                            回归测试（python tests\某测试.py）
data\                             运行时生成：配置、会话、日志、临时图片
```

`data\` 里全是运行数据（`assistant.ini`、`sessions\`、`logs\`、`facts.json`、`perf.jsonl`），删掉就等于恢复出厂设置，但**会话和记忆会一起没**。

---

## 七、常见问题

**连不上模型 / 报 TLS 握手失败**
本程序已显式要求 TLS 1.2。老 Win7 还失败的话：① 校准系统时间；② 打根证书更新（KB931125）；③ 打启用 TLS 1.2 的补丁（KB3140245）；④ 换线路或检查代理。

**证书校验失败**
同上，多半是系统时间不准或根证书太旧，程序会直接告诉你是哪一类。

**360/火绒拦住了 exe**
PyInstaller 打包的程序没有代码签名，首次运行常被拦。把程序加入白名单即可。

**任务栏图标不是我的图标**
Windows 图标缓存会回放旧图标。重启资源管理器，或运行 `ie4uinit.exe -show`。

**感觉比 Win11 上的客户端慢**
先用 `python docs\bench_perf.py` 看三段占比。实测本地读写在总耗时里只占 1% 左右，时间几乎全在等模型返回——想快就减少工具轮次，而不是优化磁盘。

**token 花得快**
调小 `max_steps`、关掉思考档位、关掉「强制执行 Skill」、把工具结果长度调到 1000 左右。

---

## 八、自己打包 exe

```bat
:: 需要 Python 3.8 + PyInstaller
python -m pip install pyinstaller==5.13.2
python -m PyInstaller --onefile --windowed --name MingShuWin7 ^
  --icon assets\mingshu.ico --add-data "assets;assets" ^
  --paths src --distpath dist --workpath build src\wb_app.py
```

产物在 `dist\`，拷走 exe 就能用。

---

## 九、许可

MIT License，可自由使用、修改、分发。图标由本项目作者用 AI 生成，随项目一同开源（不用于商业用途）。
第三方接口（DeepSeek / 通义 / OpenAI 等）请遵守各自服务条款。

<!-- 界面预览：把截图放进 docs/images/ 并命名为 main.png / settings.png / toast.png，
     然后删掉本段首尾的注释标记（这一行和结尾的 --> ），GitHub 上就会显示出来。

## 界面预览

![主界面](docs/images/main.png)

![设置面板](docs/images/settings.png)

![右下角提醒与粘贴预览](docs/images/toast.png)

-->
