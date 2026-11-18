# ==============================================================================
# Windows Task Scheduler Autostart Installer (OnStartup)
# Domain : https://thietbibachkhoa.id.vn/
# Port   : 8765
# Usage  : powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_autostart.ps1
# ==============================================================================
param(
    [int]$Port = 8765,
    [string]$Domain = "thietbibachkhoa.id.vn",
    [string]$TaskName = "UAV_ThietBiBachKhoa_WebHost_8765"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDir
$BatPath = Join-Path $ScriptDir "start_thietbibachkhoa_windows.bat"

Write-Host "[thietbibachkhoa.id.vn] Registering Windows OnStartup Scheduled Task '$TaskName'..." -ForegroundColor Cyan
Write-Host "  Project Root : $ProjectRoot"
Write-Host "  Boot Script  : $BatPath"
Write-Host "  Local Port   : $Port"
Write-Host "  Public URL   : https://$Domain/"

$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$BatPath`"" -WorkingDirectory $ProjectRoot
$TriggerBoot = New-ScheduledTaskTrigger -AtStartup
$TriggerLogon = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger @($TriggerBoot, $TriggerLogon) -Settings $Settings -Description "Auto-start UAV GeoTIFF WebGPU Survey VN2000 on port $Port and Cloudflare Tunnel for https://$Domain/ when machine powers on." -Force

Write-Host "[thietbibachkhoa.id.vn] Successfully registered '$TaskName'. When this machine turns ON, https://$Domain/ will automatically come online; when turned OFF, it will go offline." -ForegroundColor Green
