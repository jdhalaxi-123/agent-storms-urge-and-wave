<#
=====================================================================
 启动服务（由 2-启动.bat 调用）
 - 找到项目自带的 .venv，没有就提示先部署
 - 打印中文启动信息，然后启动 main.py（前台运行，关窗口即停止）
=====================================================================
#>
[CmdletBinding()]
param([string]$Root = "")

$ErrorActionPreference = "Stop"

# 项目根目录（由 2-启动.bat 传入；直接运行时按脚本位置推断）
# 注意：cmd 传参时 "E:\Agent\" 里的 \" 会被当成转义引号，收到的值可能带尾部引号
$RootGiven = ""
if ($Root) { $RootGiven = $Root.Trim().Trim('"').Trim("'").TrimEnd("\", "/") }
$Root = $null
foreach ($c in @($RootGiven, (Split-Path -Parent $PSScriptRoot), $PSScriptRoot, (Get-Location).Path)) {
    if ($c -and (Test-Path (Join-Path $c "main.py") -ErrorAction SilentlyContinue)) {
        $Root = (Resolve-Path $c).Path
        break
    }
}
if (-not $Root) {
    Write-Host ""
    Write-Host "   [错误] 找不到 main.py，无法确定项目目录。" -ForegroundColor Red
    Write-Host "          当前脚本位置：$PSScriptRoot" -ForegroundColor Yellow
    Write-Host ""
    if (-not [Console]::IsInputRedirected) { Read-Host "按回车退出" }
    exit 1
}
Set-Location $Root

function Say($m, $c = "White") { Write-Host $m -ForegroundColor $c }

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Say ""
    Say "   [错误] 还没有安装运行环境（找不到 .venv）" "Red"
    Say "          请先双击运行：  1-一键部署-Windows.bat" "Yellow"
    Say ""
    exit 1
}

$Port = if ($env:STORM_PORT) { $env:STORM_PORT } else { "7860" }

Say ""
Say "================================================================" "Cyan"
Say "   风暴潮与海浪智能预报助手" "Cyan"
Say "================================================================" "Cyan"
Say "   正在启动，约 10~30 秒后自动打开浏览器……"
Say "   网页地址：http://localhost:$Port"
Say ""
Say "   关闭本窗口 = 停止服务"
Say "================================================================" "Cyan"
Say ""

# 端口被占用时给个提示（不阻止启动，Gradio 自己会报错）
try {
    $busy = (Test-NetConnection -ComputerName 127.0.0.1 -Port ([int]$Port) -WarningAction SilentlyContinue).TcpTestSucceeded
    if ($busy) {
        Say "   [注意] 端口 $Port 已被占用：可能是本程序已经在运行。" "Yellow"
        Say "          如果打不开页面，先关掉旧的黑色窗口再启动。" "Yellow"
        Say ""
    }
} catch {}

$env:PYTHONIOENCODING = "utf-8"
& $Py (Join-Path $Root "main.py")
