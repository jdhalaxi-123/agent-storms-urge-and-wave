<#
=====================================================================
 stormsuregent 一键部署脚本（Windows）
 由「1-一键部署-Windows.bat」调用，也可以直接右键“用 PowerShell 运行”。

 做的事情：
   1. 找 Python（没有就自动下载安装到用户目录，不需要管理员权限）
   2. 建虚拟环境 .venv
   3. 装依赖（自动在 清华镜像 / 阿里镜像 / 官方源 之间择优）
   4. 引导填写 .env（DeepSeek API Key）
   5. 检查数据目录
   6. 创建桌面快捷方式
   7. 启动服务并打开浏览器

 参数（一般不用给）：
   -SkipInstall   跳过装依赖，只启动
   -Mirror <url>  指定 pip 源
   -DeepseekKey <key>  直接指定密钥，跳过交互
   -NoStart       装完不启动
   -Root <dir>    项目目录（由 .bat 传入）
=====================================================================
#>
[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [string]$Mirror = "",
    [string]$DeepseekKey = "",
    [switch]$NoStart,
    [string]$Root = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# 项目根目录（由 1-一键部署-Windows.bat 传入；直接运行时按脚本位置推断）
if ($Root) { $Root = $Root.TrimEnd("\", "/") }
if (-not $Root -or -not (Test-Path (Join-Path $Root "main.py"))) {
    $Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
    if (-not (Test-Path (Join-Path $Root "main.py"))) { $Root = (Get-Location).Path }
}
$Root = (Resolve-Path $Root).Path
Set-Location $Root

$Venv = Join-Path $Root ".venv"
$Py   = Join-Path $Venv "Scripts\python.exe"
$LogFile = Join-Path $Root "部署日志.txt"

function Say($msg, $color = "White") { Write-Host $msg -ForegroundColor $color }
function Step($n, $msg) { Write-Host ""; Write-Host "== [$n] $msg ==" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "   [OK]   $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "   [注意] $msg" -ForegroundColor Yellow }
function Bad($msg)  { Write-Host "   [失败] $msg" -ForegroundColor Red }

function Log($msg) {
    try { Add-Content -Path $LogFile -Value ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg) -Encoding UTF8 } catch {}
}

Say ""
Say "================================================================" "Cyan"
Say "   风暴潮与海浪智能预报助手  ·  一键部署" "Cyan"
Say "================================================================" "Cyan"
Say "   项目目录：$Root"
Say "   开始时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Log "部署开始，目录 $Root"

# ------------------------------------------------------------------ #
Step 1 "检查系统"
# ------------------------------------------------------------------ #
if (-not [Environment]::Is64BitOperatingSystem) {
    Bad "本项目需要 64 位 Windows（netCDF4 / ctranslate2 只有 64 位包）"
    if (-not [Console]::IsInputRedirected) { Read-Host "按回车退出" }; exit 1
}
Ok "Windows 64 位"

$sysRoot = $env:SystemRoot
$vcOk = (Test-Path "$sysRoot\System32\vcruntime140.dll") -and (Test-Path "$sysRoot\System32\msvcp140.dll")
if ($vcOk) { Ok "VC++ 运行库已安装" }
else {
    Warn "缺少 VC++ 2015-2022 运行库，netCDF4 可能装不上"
    Say  "        正在尝试自动安装 VC++ 运行库..."
    $vcUrl = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
    $vcExe = Join-Path $env:TEMP "vc_redist.x64.exe"
    try {
        Invoke-WebRequest -Uri $vcUrl -OutFile $vcExe -UseBasicParsing -TimeoutSec 180
        Start-Process -FilePath $vcExe -ArgumentList "/install","/quiet","/norestart" -Wait
        Ok "VC++ 运行库安装完成"
    } catch {
        Warn "自动安装失败：$($_.Exception.Message)"
        Warn "如果后面 netCDF4 装不上，请手动安装：https://aka.ms/vs/17/release/vc_redist.x64.exe"
    }
}

# ------------------------------------------------------------------ #
Step 2 "准备 Python 3.10+"
# ------------------------------------------------------------------ #
function Find-Python {
    # 返回可用的 python.exe 完整路径；找不到返回 $null
    $cands = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in @("-3.12","-3.11","-3.10","-3")) {
            try {
                $p = & py $v -c "import sys;print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $p) {
                    $ver = & py $v -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
                    if ([version]$ver -ge [version]"3.9") { $cands += ,@($p.Trim(), $ver) }
                }
            } catch {}
        }
    }
    foreach ($name in @("python","python3")) {
        $c = Get-Command $name -ErrorAction SilentlyContinue
        if ($c) {
            try {
                $p = & $c.Source -c "import sys;print(sys.executable)" 2>$null
                $ver = & $c.Source -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
                if ($LASTEXITCODE -eq 0 -and $p -and [version]$ver -ge [version]"3.9") {
                    $cands += ,@($p.Trim(), $ver)
                }
            } catch {}
        }
    }
    foreach ($guess in @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python39\python.exe",
        "C:\Python312\python.exe","C:\Python311\python.exe","C:\Python310\python.exe")) {
        if (Test-Path $guess) {
            try {
                $ver = & $guess -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
                if ([version]$ver -ge [version]"3.9") { $cands += ,@($guess, $ver) }
            } catch {}
        }
    }
    # 优先 3.10，其次 3.11/3.12
    $rank = { param($v) if ($v -eq "3.10") {0} elseif ($v -eq "3.11") {1} elseif ($v -eq "3.12") {2} else {3} }
    $sorted = $cands | Sort-Object -Property @{Expression = { & $rank $_[1] }}
    if ($sorted.Count -gt 0) { return $sorted[0][0] }
    return $null
}

$sysPython = Find-Python
if ($sysPython) {
    $v = & $sysPython -c "import sys;print('%d.%d.%d'%sys.version_info[:3])"
    Ok "找到 Python $v : $sysPython"
} else {
    Warn "本机没有 Python 3.9+，开始自动下载安装 Python 3.10（装到当前用户目录，不需要管理员）"
    $purl = "https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe"
    $pexe = Join-Path $env:TEMP "python-3.10.11-amd64.exe"
    $downloaded = $false
    foreach ($u in @($purl, "https://mirrors.huaweicloud.com/python/3.10.11/python-3.10.11-amd64.exe")) {
        try {
            Say "        下载 $u"
            Invoke-WebRequest -Uri $u -OutFile $pexe -UseBasicParsing -TimeoutSec 900
            $downloaded = $true; break
        } catch { Warn "下载失败：$($_.Exception.Message)" }
    }
    if (-not $downloaded) {
        Bad "Python 安装包下载失败。请手动安装 Python 3.10（勾选 Add to PATH）：https://www.python.org/downloads/"
        if (-not [Console]::IsInputRedirected) { Read-Host "按回车退出" }; exit 1
    }
    Say "        安装中（约 1-3 分钟，请勿关闭窗口）..."
    $args = @("/quiet","InstallAllUsers=0","PrependPath=1","Include_pip=1",
              "Include_launcher=1","Include_test=0","SimpleInstall=1",
              "TargetDir=$env:LOCALAPPDATA\Programs\Python\Python310")
    Start-Process -FilePath $pexe -ArgumentList $args -Wait
    $sysPython = Find-Python
    if (-not $sysPython) {
        Bad "Python 安装后仍未找到，请手动安装后重跑本脚本。"
        if (-not [Console]::IsInputRedirected) { Read-Host "按回车退出" }; exit 1
    }
    Ok "Python 安装完成：$sysPython"
}
Log "使用 Python: $sysPython"

# ------------------------------------------------------------------ #
Step 3 "创建虚拟环境 .venv"
# ------------------------------------------------------------------ #
if (Test-Path $Py) {
    Ok "已存在：$Venv"
} else {
    Say "        正在创建（约 30 秒）..."
    & $sysPython -m venv $Venv
    if (-not (Test-Path $Py)) {
        Bad "虚拟环境创建失败。"
        if (-not [Console]::IsInputRedirected) { Read-Host "按回车退出" }; exit 1
    }
    Ok "创建完成：$Venv"
}

# ------------------------------------------------------------------ #
Step 4 "安装依赖（约 1.5 GB，首次 5~20 分钟）"
# ------------------------------------------------------------------ #
if ($SkipInstall) {
    Warn "已指定 -SkipInstall，跳过依赖安装"
} else {
    & $Py -m pip install --upgrade pip setuptools wheel --quiet --disable-pip-version-check 2>&1 |
        Tee-Object -FilePath $LogFile -Append | Out-Null

    $mirrors = @()
    if ($Mirror) { $mirrors += $Mirror }
    $mirrors += @(
        "https://pypi.tuna.tsinghua.edu.cn/simple",
        "https://mirrors.aliyun.com/pypi/simple",
        "https://pypi.org/simple"
    )

    $installed = $false
    foreach ($m in $mirrors) {
        Say "        使用源：$m"
        $host_ = ([Uri]$m).Host
        & $Py -m pip install -r requirements.txt `
            --index-url $m `
            --trusted-host $host_ `
            --timeout 60 --retries 2 --disable-pip-version-check 2>&1 |
            Tee-Object -FilePath $LogFile -Append | ForEach-Object {
                if ($_ -match "^\s*(Collecting|Installing|Downloading)\s+(\S+)") {
                    Write-Host "          $($Matches[1]) $($Matches[2])" -ForegroundColor DarkGray
                }
            }
        if ($LASTEXITCODE -eq 0) { $installed = $true; break }
        Warn "该源安装失败，换下一个源重试"
    }

    if (-not $installed) {
        Bad "依赖安装失败，请把 部署日志.txt 发给技术支持。"
        if (-not [Console]::IsInputRedirected) { Read-Host "按回车退出" }; exit 1
    }
    Ok "依赖安装完成"
    Log "依赖安装完成"
}

# ------------------------------------------------------------------ #
Step 5 "配置 .env（密钥）"
# ------------------------------------------------------------------ #
$EnvFile = Join-Path $Root ".env"
if (Test-Path $EnvFile) {
    Ok ".env 已存在，跳过（如需修改请直接编辑该文件）"
} else {
    $example = Join-Path $Root ".env.example"
    if (Test-Path $example) { Copy-Item $example $EnvFile -Force }
    else { New-Item -ItemType File -Path $EnvFile -Force | Out-Null }

    if (-not $DeepseekKey) {
        Say ""
        Say "   请输入 DeepSeek API Key（必填，形如 sk-xxxxxxxx）" "Yellow"
        Say "   获取地址：https://platform.deepseek.com   （直接回车可跳过，之后手工填 .env）" "DarkGray"
        if ([Console]::IsInputRedirected) { $DeepseekKey = "" } else { $DeepseekKey = Read-Host "   DeepSeek API Key" }
    }
    if ($DeepseekKey) {
        $content = Get-Content $EnvFile -Raw -Encoding UTF8
        if ($content -match "(?m)^\s*DEEPSEEK_API_KEY=") {
            $content = $content -replace "(?m)^\s*DEEPSEEK_API_KEY=.*$", "DEEPSEEK_API_KEY=$DeepseekKey"
        } else {
            $content = "DEEPSEEK_API_KEY=$DeepseekKey`r`n" + $content
        }
        Set-Content -Path $EnvFile -Value $content -Encoding UTF8 -NoNewline
        Ok "已写入 DEEPSEEK_API_KEY"
        Log "已写入 DEEPSEEK_API_KEY"
    } else {
        Warn "未填密钥，请稍后编辑 $EnvFile 填入 DEEPSEEK_API_KEY"
    }
}

# ------------------------------------------------------------------ #
Step 6 "检查数据目录"
# ------------------------------------------------------------------ #
$DataDir = if ($env:STORM_DATA_DIR) { $env:STORM_DATA_DIR } else { Join-Path $Root "data" }
if (Test-Path $DataDir) {
    $n = (Get-ChildItem $DataDir -Recurse -Filter *.nc -ErrorAction SilentlyContinue | Measure-Object).Count
    Ok "数据目录 $DataDir，发现 $n 个 .nc 文件"
} else {
    Warn "数据目录不存在：$DataDir"
    Say  "        不影响启动（系统会用骨架演示跑通链路），但没有真实预报数据。"
    Say  "        把 NC 数据拷到该目录即可，或设置环境变量 STORM_DATA_DIR 指向数据位置。"
}
try { New-Item -ItemType Directory -Path (Join-Path $Root "outputs") -Force | Out-Null } catch {}

# ------------------------------------------------------------------ #
Step 7 "创建桌面快捷方式"
# ------------------------------------------------------------------ #
try {
    $startBat = Join-Path $Root "2-启动.bat"
    if (-not (Test-Path $startBat)) { $startBat = Join-Path $Root "deploy\2-启动.bat" }
    if (Test-Path $startBat) {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $lnk = Join-Path $desktop "风暴潮智能预报助手.lnk"
        $ws = New-Object -ComObject WScript.Shell
        $sc = $ws.CreateShortcut($lnk)
        $sc.TargetPath = $startBat
        $sc.WorkingDirectory = $Root
        $sc.IconLocation = "shell32.dll,13"
        $sc.Description = "风暴潮与海浪智能预报助手"
        $sc.Save()
        Ok "桌面快捷方式已创建：风暴潮智能预报助手"
    } else {
        Warn "没找到 2-启动.bat，跳过快捷方式创建"
    }
} catch { Warn "快捷方式创建失败（不影响使用）：$($_.Exception.Message)" }

# ------------------------------------------------------------------ #
Step 8 "启动"
# ------------------------------------------------------------------ #
Say ""
Say "================================================================" "Green"
Say "   部署完成！" "Green"
Say "================================================================" "Green"
Say "   以后启动：双击   2-启动.bat"
Say "   网页地址：http://localhost:7860"
Say "   项目目录：$Root"
Log "部署完成"

if ($NoStart) { if (-not [Console]::IsInputRedirected) { Read-Host "按回车退出" }; exit 0 }

Say ""
Say "   正在启动服务，第一次启动约 10~30 秒，请稍候..." "Yellow"
$env:PYTHONIOENCODING = "utf-8"
& $Py (Join-Path $Root "main.py")
