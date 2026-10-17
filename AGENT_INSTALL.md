# 让 AI Agent 全自动安装

这个文件是写给 **AI Agent（Claude Code / Cursor / Codex / DSH 等）** 看的安装手册。

用户只需要做两件事：

1. 把项目下载到本地（或让 Agent 自己 clone）
2. 告诉 Agent：**装到哪个目录**

其余全部由 Agent 完成：Python、解压工具、GPT-SoVITS 引擎、音色模型。

> 适用系统：Windows 10 / 11 64 位。本项目不支持 Linux / macOS（引擎是 Windows 整合包）。

---

## 给用户：把这段话复制给你的 Agent

**情况 A：已经下载好项目了**

```
我下载了「曼波配音工坊」（曼波语音生成软件）。
请严格按照项目根目录的 AGENT_INSTALL.md 帮我把所有依赖装好，最后按验收标准向我汇报。

安装目录：D:/MamboVoiceEngine/GPT-SoVITS    ← 改成你想要的目录（必须纯英文、不要中文）
```

**情况 B：只有仓库链接（更省事，Agent 会自己拉代码）**

```
帮我安装这个项目：https://github.com/Suedonmalus/manbo-voice-studio
请按仓库里的 AGENT_INSTALL.md 执行：自己把代码拉到本地，装好所有依赖，最后按验收标准向我汇报。

安装目录：D:/MamboVoiceEngine/GPT-SoVITS    ← 改成你想要的目录（必须纯英文、不要中文）
```

两种情况都只需要改最后那行安装目录；目录不存在没关系，Agent 会创建。

---

## Agent 执行手册

按顺序执行，每步都要检查结果，不要跳步。

### 第 0 步：拿到代码（用户只给了链接时）

先确认当前目录有没有项目文件：

```powershell
Get-ChildItem app.py, tools/agent_install.py
```

都在 → 跳过本步。缺 → 用下面任一方式拉取：

```powershell
# 方式 1：git clone（推荐，以后能 git pull 更新）
git clone https://github.com/Suedonmalus/manbo-voice-studio.git
cd manbo-voice-studio

# 方式 2：没有 git 就下源码包再解压
curl.exe -L -o studio.zip https://github.com/Suedonmalus/manbo-voice-studio/archive/refs/tags/v1.1.zip
Expand-Archive studio.zip -DestinationPath .
cd manbo-voice-studio-1.1
```

> 项目根目录就是能看到 `app.py`、`tools/`、`README.md` 的那一层。
> 下源码包解压后会多一层 `manbo-voice-studio-1.1/`，别在上一层找 `tools/agent_install.py`。
> 既没有 git 也没有 curl 时，让用户从 GitHub 页面 Code → Download ZIP 手动下载。
> 上面固定写的是 `v1.1`，如果仓库有更新的 tag，换成最新的那个。

### 第 1 步：确认环境

```powershell
# 必须是 Windows
[System.Environment]::OSVersion.Platform
# 确认项目根目录存在 app.py 和 tools/agent_install.py
Get-ChildItem app.py, tools/agent_install.py
```

### 第 2 步：确保 Python 3.10+

```powershell
python --version
```

- 输出 `Python 3.10` 及以上 → 跳过第 3 步
- 提示找不到 `python`，或版本低于 3.10 → 执行第 3 步

### 第 3 步：安装 Python（仅在第 2 步不通过时）

**不需要管理员权限**，装用户级即可。

优先用 winget：

```powershell
winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
```

winget 不可用时，用官方安装器静默安装：

```powershell
$url = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
curl.exe -L -o "$env:TEMP\python-setup.exe" $url
Start-Process -Wait "$env:TEMP\python-setup.exe" -ArgumentList '/quiet InstallAllUsers=0 PrependPath=1 Include_tcltk=1 Include_pip=1'
```

> 如果上面的固定版本号 404，去 https://www.python.org/downloads/windows/ 选当前最新的 3.12.x（Windows installer 64-bit）替换链接。
>
> 参数含义：`InstallAllUsers=0` 用户级安装（免 UAC）、`PrependPath=1` 写进 PATH、`Include_tcltk=1` 带上 tkinter。

装完 **必须换一个新终端**（或重新加载环境变量）再验证，因为当前 shell 的 PATH 不会自动更新：

```powershell
python --version
```

若新终端里仍然没有 `python`，直接用绝对路径调用（下面用 `$PY` 代指）：

```powershell
$PY = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $PY --version
```

### 第 4 步：运行全自动安装器

```powershell
python tools/agent_install.py --dest "D:/MamboVoiceEngine/GPT-SoVITS"
```

（第 3 步用了绝对路径的话，把 `python` 换成 `$PY`）

它会依次完成：

| 顺序 | 动作 | 大小 / 耗时 |
| --- | --- | --- |
| 1 | 校验安装目录（纯英文、非系统目录、≥32GB 空闲、空目录） | 毫秒 |
| 2 | 准备解压工具：系统有 7-Zip 就用；没有就自动下 `7zr.exe`（590KB）到 `tools/` | 秒级 |
| 3 | 识别显卡，下载对应引擎整合包并解压安装 | 约 8.2GB，5–15 分钟 |
| 4 | 下载曼波音色模型包，只取出 3 个文件放进 `models/` | 约 213MB |
| 5 | 校验引擎目录、模型文件、`config.json` | 秒级 |

**脚本会把过程日志打到 stderr，把最终结果 JSON 打到 stdout。** 请解析 JSON 而不是靠猜。

### 第 5 步：解析结果

成功时退出码 `0`，stdout 形如：

```json
{
  "ok": true,
  "dest": "D:\\MamboVoiceEngine\\GPT-SoVITS",
  "seven_zip": { "path": "C:/Program Files/7-Zip/7z.exe", "source": "system" },
  "engine": { "ok": true, "path": "D:\\MamboVoiceEngine\\GPT-SoVITS", "reused": false },
  "models": { "ok": true, "downloaded": true, "files": ["manbo-e10.ckpt", "manbo_e8_s168.pth", "refer.wav"] },
  "verify": {
    "ok": true,
    "engine_ok": true,
    "models_ok": true,
    "config_ok": true,
    "files": { "manbo_e8_s168.pth": { "ok": true, "size_mb": 75.0 } }
  },
  "steps": [ "..." ],
  "elapsed_sec": 812.3
}
```

失败时 `ok: false`，并带 `error` 和 `stage`（出错阶段）。

### 第 6 步：可选冒烟测试

静态校验通过后，如果想确认真的能出声：

```powershell
python app.py
```

会打开图形界面。手动输入一段文字点「生成配音」，首次合成需要等 20–60 秒（引擎加载模型）。
**不要用 `pythonw`**，那样崩溃时看不到错误。

也可以只确认引擎能起来（不打开界面）：

```powershell
$dest = "D:/MamboVoiceEngine/GPT-SoVITS"
& "$dest/runtime/python.exe" "$dest/api.py" -a 127.0.0.1 -p 9880
```

看到 Uvicorn 监听 `127.0.0.1:9880` 即为正常，随后 Ctrl+C 关掉。

---

## 依赖与权限清单

| 项目 | 谁负责 | 说明 |
| --- | --- | --- |
| Python 3.10–3.15 | Agent（第 3 步） | 用户级安装，**不需要管理员** |
| 7-Zip | Agent 自动 | 优先用系统已装的；没有就下免安装 `7zr.exe` |
| `requests` / `numpy` | Agent 自动 | 安装器自己会 pip 装（清华镜像） |
| `PySide6` | 不用管 | 首次运行 `启动.bat` / `python app.py` 时自动装 |
| GPT-SoVITS 引擎 | Agent 自动 | 约 8.2GB 下载 + 18GB 解压 |
| 曼波音色模型 | Agent 自动 | 从 MamboTTS 的 MIT 发布包取 3 个文件 |

**磁盘**：安装盘至少 **32GB 空闲**（8.2GB 包在装完后会自动删除）。
**网络**：全程约 **8.5GB** 下载量。
**权限**：不需要管理员权限；不要装到 `C:\Windows`、`C:\Program Files`、`C:\ProgramData`。

---

## 安装目录的硬性要求

必须同时满足，否则脚本会拒绝：

- **纯英文路径**：不能有中文、空格可以但有风险，建议 `D:/MamboVoiceEngine/GPT-SoVITS` 这种
- **不是盘符根目录**：`D:/` ❌，`D:/GPT-SoVITS` ✅
- **不是系统目录**
- **目录为空或不存在**：非空目录一律拒绝，避免覆盖用户数据（已装好的引擎目录除外，会直接复用）
- **所在盘 ≥32GB 空闲**

---

## 失败处理

| 退出码 / 现象 | 原因 | 处理 |
| --- | --- | --- |
| 退出码 `2` | Python < 3.10 | 按第 3 步装 Python 后重试 |
| `stage: "seven_zip"` | 7zr.exe 下载失败且系统没 7-Zip | 让用户装 https://www.7-zip.org/download.html 后重试 |
| `stage: "engine"` 且提示"所有下载源都连不上" | 网络/代理问题 | 重试一次；仍失败则手动下载 7z 放进 `engine_temp/` 再重试 |
| `stage: "models"` | 模型包下载失败 | 重试（支持复用已下载的包）；或让用户从 https://github.com/Tsukimisaka/MamboTTS/releases 手动下载后放 `models/` |
| `stage: "check_dest"` | 目录含中文 / 非空 / 空间不足 | 换一个空目录重试 |
| 下载中断 | 网络抖动 | 直接重跑同一条命令，**支持断点续传** |

**重要**：这个安装器是幂等的。任何一步失败后，原样重跑就能从断点继续，不会重复下载已完成的部分。

---

## 验收标准

安装成功的判定（全部满足）：

1. `tools/agent_install.py` 退出码为 `0`
2. 输出 JSON 中 `ok`、`verify.engine_ok`、`verify.models_ok`、`verify.config_ok` 全为 `true`
3. `config.json` 里的 `engine_dir` 等于用户指定的目录
4. `models/` 下有 `manbo_e8_s168.pth`（约 75MB）、`manbo-e10.ckpt`（约 136MB）、`refer.wav`（约 0.36MB）

向用户汇报时请包含：

- 实际安装目录
- 下载总量与总耗时
- 7-Zip 是复用系统的还是自动下载的
- 音色模型是否自动装好
- 启动方式：**双击 `启动.bat`**

---

## 卸载（给 Agent）

```powershell
python tools/uninstall.py --dry-run --json   # 先看会删什么
python tools/uninstall.py --yes              # 执行卸载
```

- 默认连音色模型一起删；要保留加 `--keep-models`，保留 7zr 加 `--keep-7zr`
- `--yes` 不弹窗，直接输出 JSON
- **卸载前确认 127.0.0.1:9880 没有引擎在跑**，否则文件被占用会删不掉
- 不会删 `output/`、项目源码、pip 装的 Python 库
- 只会删「确认是引擎」的目录（里面必须有 `api.py` + `runtime/`）；如果 `config.json`
  被改到奇怪的位置，脚本会跳过并给出原因，不会乱删

输出形如：

```json
{
  "ok": true,
  "removed": ["D:\\MamboVoiceEngine\\GPT-SoVITS", "D:\\MamboVoiceEngine\\voices"],
  "failed": [],
  "freed": 15277545131
}
```

## 已知限制

- 引擎下载源目前是 ModelScope / hf-mirror / HuggingFace，国内网络一般可用；源文件更新会导致大小校验失败，届时需要更新 `tools/download_engine.py` 里的 `SIZE`
- 音色模型包固定在 MamboTTS `v1.2.1`，该版本 MIT 许可；升级需同步改 `MODEL_ZIP_URL` 和 `MODEL_MIN_SIZE`
- 没有 NVIDIA 显卡也能装，但只能用 CPU 推理，合成速度慢 20–50 倍
- ARM64 Windows 上的 Python 装不了 `PySide6` 的部分依赖，本项目仅验证 x64
