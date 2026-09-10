# 交给 AI 的部署与使用说明书

> **读者：另一台电脑上的 AI 助手（DeepSeek 等）。**
> 人类用户会把这份文件、以及整个 `stormsurge-agent` 程序目录交给你。
> 请你按本文档在这台电脑上完成部署、验证，并在后续帮用户使用和维护。
>
> 文档里的命令都是 **Windows**（PowerShell / cmd）写法；Linux 差异见第 9 节。
> 全部命令都已在本项目开发机上实测通过。

---

## 0. 一句话背景

这是一个**风暴潮与海浪智能预报助手**：用户用中文提问（如"厦门未来5天的风暴潮"），
它调用 DeepSeek 大模型解析意图 → 读取本地 NetCDF 预报数据 → 判级 → 输出文字简报、
预报图（PNG）和 Word 文档，界面是浏览器里的聊天窗口（Gradio，端口 7860）。

**技术栈**：Python 3.10 + gradio + xarray/netCDF4 + matplotlib + python-docx + openai SDK。

**它需要联网的地方**：
- 部署阶段：下载 pip 依赖
- 使用阶段：调用 `api.deepseek.com`（对话大脑）、可选 `asr.tencentcloudapi.com`（语音识别）

---

## 1. 你要先判断的三件事

在动手之前，请先确认（可以直接跑程序目录里的 `3-环境自检.bat`，
它会生成《环境自检报告.md》，末尾有 JSON 格式的机器可读事实）：

| 要判断的 | 通过标准 | 不通过怎么办 |
| --- | --- | --- |
| 系统位数 | 必须 **64 位** Windows | 32 位无法安装 netCDF4/ctranslate2，只能换机器 |
| pip 源可达 | `pypi.tuna.tsinghua.edu.cn` / `mirrors.aliyun.com` / `pypi.org` 任一可连 | 让运维开白名单；或改用离线包（见第 8 节） |
| 磁盘空间 | 程序所在盘 **≥ 3 GB** | 清理或换盘 |
| 端口 7860 | 空闲 | 启动前设 `STORM_PORT=7861` 换端口 |
| VC++ 运行库 | `C:\Windows\System32\vcruntime140.dll` 存在 | 装 <https://aka.ms/vs/17/release/vc_redist.x64.exe>（netCDF4 的硬依赖） |

---

## 2. 部署（推荐：一条命令）

程序目录里双击 `1-一键部署-Windows.bat` 即可。它会自动完成：
检查系统 → 找/装 Python 3.10 → 建 `.venv` → 装依赖 → 引导填 API Key →
检查数据目录 → 建桌面快捷方式 → 启动并打开浏览器。

**如果你（AI）要在命令行里代跑**，用它等价的命令：

```powershell
cd <程序目录>
powershell -NoProfile -ExecutionPolicy Bypass -File ".\deploy\setup_windows.ps1"
```

可用的参数：

| 参数 | 作用 |
| --- | --- |
| `-DeepseekKey sk-xxxx` | 直接指定 DeepSeek 密钥，跳过交互提问 |
| `-Mirror https://pypi.tuna.tsinghua.edu.cn/simple` | 指定 pip 源（默认自动在清华/阿里/官方之间择优重试） |
| `-SkipInstall` | 跳过装依赖，只做其余步骤 |
| `-NoStart` | 装完不自动启动 |
| `-Root <目录>` | 显式指定程序目录（一般不用给） |

部署成不成功的判据（第 4 节有完整验证方法）：

```
[OK] 依赖安装完成
[OK] 桌面快捷方式已创建
部署完成！
```

---

## 3. 已知坑（**重要，请先看这一节**）

### 3.1 `-Root "E:\App\"` 尾部反斜杠吞引号（2026-09 修复）

**症状**（旧版脚本）：

```
Test-Path : 路径中具有非法字符。
+ if (-not $Root -or -not (Test-Path (Join-Path $Root "main.py"))) {
+ CategoryInfo : InvalidArgument: (E:\Agent"\main.py:String)
```

**原因**：批处理里 `%~dp0` 结尾永远带 `\`，拼出的命令行是 `-Root "E:\Agent\"`。
Windows 命令行解析器把 `\"` 当成**转义引号**，PowerShell 实际收到 `E:\Agent"`（多个引号）。

**修复状态**：新交付包已修（`.bat` 里剥掉尾部反斜杠 + `.ps1` 里 `Trim('"')` 并逐级兜底）。

**如果你手上的包是旧版，两种处理**：

方案 A（推荐，一行命令绕过，不传 `-Root` 即可，脚本会自己按脚本位置推断）：

```powershell
cd E:\Agent
powershell -NoProfile -ExecutionPolicy Bypass -File "E:\Agent\deploy\setup_windows.ps1"
```

方案 B（就地打补丁）：用记事本打开 `deploy\setup_windows.ps1`，
把第 35~42 行那段「项目根目录」判断替换为：

```powershell
$RootGiven = ""
if ($Root) { $RootGiven = $Root.Trim().Trim('"').Trim("'").TrimEnd("\", "/") }
$Root = $null
foreach ($c in @($RootGiven, (Split-Path -Parent $PSScriptRoot), $PSScriptRoot, (Get-Location).Path)) {
    if ($c -and (Test-Path (Join-Path $c "main.py") -ErrorAction SilentlyContinue)) {
        $Root = (Resolve-Path $c).Path; break
    }
}
if (-not $Root) { Write-Host "[错误] 找不到 main.py"; exit 1 }
Set-Location $Root
```

### 3.2 编码（**改动脚本时务必注意**）

| 文件类型 | 必须的编码 | 原因 |
| --- | --- | --- |
| `.ps1` | **UTF-8 带 BOM** | Windows PowerShell 5.1 读「无 BOM 的 UTF-8」会按 GBK 解码，中文注释里的字节被当成引号/花括号 → 脚本解析失败（报 `The string is missing the terminator`） |
| `.bat` / `.cmd` | **纯 ASCII** | cmd.exe 按 OEM 代码页（中文 Windows = GBK）读批处理，中文会被截断甚至拆断命令行 → 报 `'xxx' is not recognized` |
| `.py` / `.md` | UTF-8 无 BOM | Python 与浏览器/编辑器默认行为 |

**因此**：中文提示一律写在 `.ps1` 里，`.bat` 只做纯 ASCII 的转发。
如果必须改 `.bat` 并想加中文，请先 `chcp 65001` 且确保编辑器保存为 UTF-8（无 BOM），并实测一遍。

给 `.ps1` 补 BOM 的命令：

```powershell
$p = "deploy\setup_windows.ps1"
$t = [System.IO.File]::ReadAllText($p, [System.Text.UTF8Encoding]::new($false))
[System.IO.File]::WriteAllText($p, $t, [System.Text.UTF8Encoding]::new($true))
```

### 3.3 其他

- **依赖没装全**：旧版 `requirements.txt` 只列了 5 个包，缺 `xarray / netCDF4 / scipy /
  matplotlib / python-docx / ctranslate2 / av` —— 少了这些程序起不来。新版已补全，
  若你拿到的是旧包，用新包覆盖 `requirements.txt` 后重跑部署。
- **语音识别第一次很慢**：本地 faster-whisper 模型要从 HuggingFace 下载。
  国内先设 `HF_ENDPOINT=https://hf-mirror.com` 再启动；或在 `.env` 填腾讯云密钥走云端识别。
- **没有数据也能启动**：会自动降级为骨架演示（不会崩），但出不了真实预报图。

---

## 4. 部署后的验证（请务必跑这三步）

```powershell
cd <程序目录>

# ① 依赖齐不齐
.\.venv\Scripts\python.exe -c "import gradio,xarray,netCDF4,matplotlib,docx,openai,faster_whisper; print('deps OK')"

# ② 程序能不能起来（后台起，5 秒后探测端口，然后关掉）
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "main.py" -WorkingDirectory (Get-Location) -WindowStyle Hidden
Start-Sleep -Seconds 25
(Invoke-WebRequest http://127.0.0.1:7860 -UseBasicParsing).StatusCode    # 期望 200

# ③ 大模型通不通（需要 .env 里有 DEEPSEEK_API_KEY）
.\.venv\Scripts\python.exe -c "from orchestrator import llm; print(llm.chat('一句话说明风暴潮是什么', [])[0][:80])"
```

三步都过 → 部署成功。以后启动：双击 `2-启动.bat`（或命令行
`.\.venv\Scripts\python.exe main.py`），浏览器开 <http://localhost:7860>。

---

## 5. 配置（`.env`，在程序根目录）

```ini
DEEPSEEK_API_KEY=sk-xxxx          # 必填，https://platform.deepseek.com
TENCENT_SECRET_ID=xxxx            # 可选，语音识别（不填走本地识别）
TENCENT_SECRET_KEY=xxxx
TENCENT_ASR_REGION=ap-guangzhou
FTP_HOST=120.42.36.229            # 可选，课题数据库（问"数据在哪/同步数据"时用）
FTP_PORT=22210
FTP_USER=xxxx
FTP_PASS=xxxx
STORM_DATA_DIR=E:\数据\storm_data  # 可选，数据不在程序目录时用这个指路
```

启动时可用的环境变量：`STORM_PORT`（默认 7860）、`STORM_HOST`（默认 127.0.0.1，
设为 `0.0.0.0` 则同局域网可访问）、`STORM_NO_BROWSER=1`（不自动开浏览器）。

> **安全**：`.env` 含密钥，不要提交 git、不要外发。交付包里不含 `.env`，由使用者自己填。

---

## 6. 放数据

程序自动扫描**程序目录下的 `data/`**，无需配置。目录约定：

```
data/
├── 2526/                          # 按台风编号分文件夹
│   ├── output_0.nc                # 数值模拟风暴潮场
│   ├── output_4.nc                # AI/融合风暴潮场
│   └── ERA5/2025110800.nc         # 风场（ERA5 逐日文件）
├── Ensemble/Ensemble_Surge_20250421/2403_irregular_new.nc   # 集合(AI)预报
├── ftp/2403/2403_surge.nc         # 从课题数据库同步下来的
├── typhoon_2526-wave/M1_wav_20251110.nc                     # 海浪（M1 细网格）
├── typhoon_2526-wave/R1_wav_20251110.nc                     # 海浪（R1 大范围）
└── storm_surge_field_station/typhoon_2526/ocn_forecast_20251110-20251116.nc  # 站点单点
```

两种放法：把 `data` 整个拷到程序目录下；或设 `STORM_DATA_DIR` 指向数据所在位置。

**没有数据想先验证链路**：`.\.venv\Scripts\python.exe scripts\make_sample_data.py`
会生成约 30 MB 样例 NC 数据到 `data/sample/`。

---

## 7. 怎么用（产品能力，供你回答用户）

**能回答什么**

| 用户问法 | 系统行为 |
| --- | --- |
| "厦门的风暴潮" | 走本站单点数据 + 四色警戒潮位判级，出过程曲线图 |
| "福州/澎湖/高雄/温州/汕头附近的风暴潮" | 在模式场按该地点坐标**采样**，按风暴增水分级判级，图上标注目标点 |
| "东经120.5度 北纬25.5度 这个位置" | 直接按经纬度采样 |
| "画一下风场 / 看海浪 / 看全场增水分布" | 只画用户要的那一类图（问什么给什么） |
| "上海的风暴潮" | **超范围**：只回文字说明，不出数据不出图 |
| "台湾的风暴潮" | 范围太大：**追问**具体位置，不出数据 |
| "XX数据在数据库哪个目录" | 查课题数据库(FTP)目录，返回真实路径 |
| 生成简报 | 对话里给 Markdown，同时生成可下载的红头 Word |

**覆盖范围**：`114.5°E ~ 127.5°E，17.0°N ~ 29.5°N`（台湾海峡及福建、浙南沿海）。
**本站站点**：厦门、崇武、晋江、东山东港。

**接口（想自己调用时）**

```python
import sys; sys.path.insert(0, "<程序目录>")
from orchestrator import engine
r = engine.run_with_slots({"disaster": "storm_surge", "region": "福州",
                           "time_window": "未指定", "risk_type": "general",
                           "typhoon": "", "date": "", "plot": ""})
print(r["reply"]); print(r["images"]); print(r["docx_path"])
```

---

## 8. 二次维护（改代码时看这里）

| 想做什么 | 改哪里 |
| --- | --- |
| 加/改地名（含经纬度） | `orchestrator/geo_domain.py` 的 `KNOWN_PLACES`，一行 `"地名": (经度, 纬度)` |
| 改覆盖范围 | 同文件顶部 `LON_MIN/LON_MAX/LAT_MIN/LAT_MAX` |
| 改"大范围要追问"的区域 | 同文件 `BROAD_REGIONS` |
| 改判级阈值 | `modules/assess.py` 的 `LEVELS`（增水）与 `STATION_WARN_LEVELS`（各站四色警戒潮位） |
| 加业务模块 | 在 `modules/` 新建 `xxx.py`，实现 `run(ctx) -> ctx`（契约见 `orchestrator/contract.py`），在 `orchestrator/engine.py` 里挂进链路 |
| 改 LLM 提示词/工具定义 | `orchestrator/llm.py` 的 `SYSTEM_PROMPT` / `FORECAST_TOOL` |
| 改界面 | `main.py` |

**重新打交付包**：`.\.venv\Scripts\python.exe scripts\build_deploy_package.py`
→ `dist\stormsurge-agent-部署包-YYYYMMDD.zip`（自动排除 `.venv`/`data`/`outputs`/密钥/对话记录，
并自动把 `.ps1` 规范成带 BOM 的 UTF-8）。

**离线部署**（目标机不能上外网）：在有网机器上
`pip download -r requirements.txt -d wheelhouse --platform win_amd64 --python-version 310 --only-binary=:all:`，
把 `wheelhouse/` 一起拷过去，安装时用
`pip install -r requirements.txt --no-index --find-links wheelhouse`。

---

## 9. Linux / macOS 差异

```bash
bash deploy/setup_linux.sh      # 一键部署（可加 --mirror 指定源）
bash deploy/start_linux.sh      # 启动
```

netCDF4 编译失败时先装系统库：Ubuntu `sudo apt install -y libnetcdf-dev libhdf5-dev`；
macOS `brew install netcdf`。端口/主机/数据目录环境变量同上（`export STORM_PORT=8080`）。

---

## 10. 排错速查

| 现象 | 原因 → 处理 |
| --- | --- |
| `Test-Path : 路径中具有非法字符` | 见 3.1，尾部反斜杠吞引号 |
| `The string is missing the terminator` | `.ps1` 丢了 BOM，见 3.2 |
| `'xxx' is not recognized as an internal or external command` | `.bat` 里有中文，见 3.2 |
| `ModuleNotFoundError: xarray/netCDF4/docx/...` | 依赖没装全，重跑部署或 `pip install -r requirements.txt` |
| `netCDF4` 装不上 | 缺 VC++ 运行库，见第 1 节 |
| 连不上 pypi | 换源：`-Mirror https://mirrors.aliyun.com/pypi/simple` |
| 页面打不开 | 7860 被占：`3-环境自检.bat` 会告诉你；或设 `STORM_PORT=7861` |
| 对话报"未找到 DEEPSEEK_API_KEY" | `.env` 没填/没保存，填完重启 |
| 回复"数据不足/骨架演示" | 没有 `data/` 数据，见第 6 节 |
| 回答里出现 1970 年 | 数据时间轴编码不识别，需要看 `modules/geo_stats.py` 的 `_time0_dt` |
| 图里数值异常大（几百 cm） | 采样点落在近岸浅水/河口格点，属模型数据特性；系统已在注释里标注采样点位置与距离 |

---

## 11. 请遵守的边界

1. **不要编造数据或路径**：预报结论只能来自本地 NC 数据；数据库路径只能来自 FTP 工具的真实返回。
2. **超范围就明说**：不在 `114.5~127.5°E / 17.0~29.5°N` 的地点，只回文字说明，不要"估一个"。
3. **大范围先追问**：用户只说"台湾""福建"这类大范围时，先问具体位置，不要直接给结论。
4. **密钥不外传**：不要读取、打印或转发 `.env` 里的密钥内容。
5. **判级口径**：本站走「总水位 × 该站四色警戒潮位」；任意采样点无本站警戒潮位，走「风暴增水分级」。
   最终以厦门中心业务化运行结果为准。
