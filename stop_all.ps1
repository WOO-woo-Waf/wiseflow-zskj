param(
  [string]$Base = $PSScriptRoot
)

$ErrorActionPreference = 'SilentlyContinue'


$BASE = $Base
$LOG  = Join-Path $BASE 'logs'

function Stop-ByPidFile {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Name,
    [Parameter(Mandatory)][string]$Pattern
  )
  $pidFile = Join-Path $LOG "$Name.pid"
  if (Test-Path $pidFile) {
    $procId = Get-Content $pidFile | Select-Object -First 1
    if ($procId) {
      Write-Host "Stopping $Name (PID=$procId)..."
      Stop-Process -Id $procId -Force
    }
    Remove-Item $pidFile -Force
  } else {
    Write-Host "PID file for $Name not found, try pattern kill..."
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match $Pattern } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  }
}

# 停止顺序：先 task，再 backend、web，最后 pocketbase
Stop-ByPidFile -Name 'tasks'      -Pattern 'python\s+tasks\.py'
Stop-ByPidFile -Name 'backend'    -Pattern 'uvicorn.*main:app'
Stop-ByPidFile -Name 'web'        -Pattern 'uvicorn.*serve:app'
Stop-ByPidFile -Name 'pocketbase' -Pattern 'pocketbase\s+serve'

Write-Host 'All stopped.'
