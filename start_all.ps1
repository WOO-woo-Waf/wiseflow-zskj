
param(
  [string]$Base = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'

# =========== 1) 激活 conda wiseflow ===========
conda activate wiseflow | Out-Null
$env:PYTHONUNBUFFERED = "1"

# =========== 2) 路径 ===========
$BASE   = $Base
$LOG    = Join-Path $BASE 'logs'
$PBWD   = Join-Path $BASE 'core\pb'
$WEBWD  = Join-Path $BASE 'dashboard\web'
$BEWD   = Join-Path $BASE 'dashboard\backend'
$TASKWD = Join-Path $BASE 'core'

foreach ($d in @($BASE,$PBWD,$WEBWD,$BEWD,$TASKWD)) {
  if (-not (Test-Path $d)) { throw "目录不存在: $d" }
}
New-Item -ItemType Directory -Force -Path $LOG | Out-Null

# pocketbase 可执行（兼容无扩展名/不同命名）
$pocketbaseExe = Get-ChildItem -Path $PBWD -Filter 'pocketbase*' -File -ErrorAction SilentlyContinue |
                 Select-Object -First 1
if (-not $pocketbaseExe) { throw "找不到 pocketbase 可执行（期望在：$PBWD 下名为 pocketbase*）" }
$pocketbaseExe = $pocketbaseExe.FullName

# =========== 3) 工具函数 ===========
function Test-ProcessRunning {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$Pattern)
  $p = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
       Where-Object { $_.CommandLine -match $Pattern }
  return [bool]$p
}

function Start-TrackedProcess {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Name,
    [Parameter(Mandatory)][string]$FilePath,
    [Parameter(Mandatory)][string[]]$ArgumentList,
    [Parameter(Mandatory)][string]$WorkingDirectory,
    [Parameter(Mandatory)][string]$Stdout,
    [Parameter(Mandatory)][string]$Stderr
  )
  if (-not (Test-Path $WorkingDirectory)) { throw "WorkingDirectory 不存在: $WorkingDirectory" }
  if (-not (Test-Path $FilePath)) {
    $cmd = Get-Command $FilePath -ErrorAction SilentlyContinue
    if ($cmd) { $FilePath = $cmd.Source } else { throw "找不到可执行文件: $FilePath" }
  }
  $p = Start-Process -FilePath $FilePath `
                     -ArgumentList $ArgumentList `
                     -WorkingDirectory $WorkingDirectory `
                     -WindowStyle Hidden `
                     -RedirectStandardOutput $Stdout `
                     -RedirectStandardError  $Stderr `
                     -PassThru
  Set-Content -Path (Join-Path $LOG "$Name.pid") -Value $p.Id
  Write-Host "[$Name] started. PID=$($p.Id)"
}

# =========== 4) 启动顺序 ===========
Write-Host "[1/4] start pocketbase..."
if (Test-ProcessRunning 'pocketbase\s+serve') {
  Write-Host "[pocketbase] 已在运行，跳过。"
} else {
  Start-TrackedProcess -Name 'pocketbase' -FilePath $pocketbaseExe `
    -ArgumentList @('serve') `
    -WorkingDirectory $PBWD `
    -Stdout (Join-Path $LOG 'pb.log') `
    -Stderr (Join-Path $LOG 'pb.err.log')
}
Start-Sleep -Seconds 1

Write-Host "[2/4] start dashboard web (uvicorn serve:app)..."
if (Test-ProcessRunning 'uvicorn.*serve:app') {
  Write-Host "[web] 已在运行，跳过。"
} else {
  Start-TrackedProcess -Name 'web' -FilePath 'python' `
    -ArgumentList @('-m','uvicorn','serve:app','--host','127.0.0.1','--port','5555','--log-level','info','--access-log') `
    -WorkingDirectory $WEBWD `
    -Stdout (Join-Path $LOG 'web.log') `
    -Stderr (Join-Path $LOG 'web.err.log')
}

Write-Host "[3/4] start backend (uvicorn main:app)..."
if (Test-ProcessRunning 'uvicorn.*main:app') {
  Write-Host "[backend] 已在运行，跳过。"
} else {
  Start-TrackedProcess -Name 'backend' -FilePath 'python' `
    -ArgumentList @('-m','uvicorn','main:app','--host','127.0.0.1','--port','7777','--log-level','info','--access-log') `
    -WorkingDirectory $BEWD `
    -Stdout (Join-Path $LOG 'backend.log') `
    -Stderr (Join-Path $LOG 'backend.err.log')
}

# Write-Host "[4/4] start tasks.py..."
# if (Test-ProcessRunning 'python\s+tasks\.py') {
#   Write-Host "[tasks] 已在运行，跳过。"
# } else {
#   Start-TrackedProcess -Name 'tasks' -FilePath 'python' `
#     -ArgumentList @('tasks.py') `
#     -WorkingDirectory $TASKWD `
#     -Stdout (Join-Path $LOG 'tasks.log') `
#     -Stderr (Join-Path $LOG 'tasks.err.log')
# }

Write-Host "All started. Logs: $LOG"

$FrontendUrl = 'http://localhost:5555'

function Wait-UntilHttpOk {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Url,
    [int]$TimeoutSec = 40,
    [int]$IntervalSec = 1
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
      if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) { return $true }
    } catch { }
    Start-Sleep -Seconds $IntervalSec
  }
  return $false
}

# 5) 自动打开前端链接
Write-Host "Opening frontend: $FrontendUrl"
$ok = Wait-UntilHttpOk -Url $FrontendUrl -TimeoutSec $OpenTimeoutSec
if (-not $ok) {
  Write-Host "Frontend not responding within $OpenTimeoutSec s, opening anyway..."
}
Start-Process $FrontendUrl | Out-Null
