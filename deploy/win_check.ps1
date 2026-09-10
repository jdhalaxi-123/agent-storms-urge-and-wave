<#
=====================================================================
 环境自检（由 3-环境自检.bat 调用）
 - 优先用项目自带 .venv 的 python；没有就用系统 python / py
 - 生成《环境自检报告.md》，可直接复制给 AI 助手看
=====================================================================
#>
[CmdletBinding()]
param([string]$Root = "")

$ErrorActionPreference = "Continue"

# 项目根目录（由 3-环境自检.bat 传入；直接运行时按脚本位置推断）
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

Say ""
Say "================================================================" "Cyan"
Say "   环境自检（部署前先跑这个）" "Cyan"
Say "================================================================" "Cyan"
Say "   会生成《环境自检报告.md》。"
Say "   如果自己看不懂，把报告全文复制给 AI（比如 DeepSeek 助手），"
Say "   它就能告诉你这台机器缺什么、下一步怎么做。"
Say "================================================================" "Cyan"
Say ""

$env:PYTHONIOENCODING = "utf-8"
$script = Join-Path $Root "deploy\check_env.py"

$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    & $venvPy $script
    exit $LASTEXITCODE
}

$sysPy = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $sysPy = "py" }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $sysPy = "python" }

if ($sysPy) {
    if ($sysPy -eq "py") { & py -3 $script } else { & python $script }
    exit $LASTEXITCODE
}

Say "   [提示] 这台电脑没有找到 Python，无法自动自检。" "Yellow"
Say "          请手动收集以下信息交给 AI：" "Yellow"
Say "            - 系统版本（命令行运行 winver 可以看到）"
Say "            - 是不是 64 位系统"
Say "            - 能不能打开 https://pypi.tuna.tsinghua.edu.cn"
Say "            - C 盘剩余空间"
Say ""
exit 1
