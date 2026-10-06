[CmdletBinding()]
param(
    [string]$TaskName = "KendoKeikoInstagramReel",
    [string]$WslDistro = "Ubuntu",
    [string]$LinuxUser = "ozaki",
    [string]$RepoPath = "/home/ozaki/project/kendo-keiko-scraping",
    [string]$Time = "18:00",
    [switch]$Publish,
    [switch]$Enable,
    [switch]$Apply,
    [switch]$AllowNonTokyo
)

$ErrorActionPreference = "Stop"
$tz = [System.TimeZoneInfo]::Local.Id
if (-not $AllowNonTokyo -and $tz -ne "Tokyo Standard Time") {
    throw "Windows timezone is '$tz', expected 'Tokyo Standard Time'. Use -AllowNonTokyo only after verifying the JST conversion."
}

if ($Time -notmatch '^(?:[01]\d|2[0-3]):[0-5]\d$') {
    throw "-Time must be HH:mm (recommended initial value: 18:00 JST)."
}

$mode = if ($Publish) { "--publish" } else { "--dry-run" }
$arguments = "-d $WslDistro -u $LinuxUser -- $RepoPath/scripts/run_instagram_reel.sh $mode"
$action = New-ScheduledTaskAction -Execute "wsl.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Wednesday -At ([DateTime]::ParseExact($Time, "HH:mm", $null))
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries

Write-Output "TaskName: $TaskName"
Write-Output "Windows user: $env:USERNAME"
Write-Output "Windows timezone: $tz"
Write-Output "WSL distro/user: $WslDistro / $LinuxUser"
Write-Output "Repository: $RepoPath"
Write-Output "Schedule: Wednesday $Time (Windows local time; verify it is JST)"
Write-Output "Action: wsl.exe $arguments"

if (-not $Apply) {
    Write-Output "DRY-RUN: no Windows task was created. Re-run with -Apply after verifying the values."
    exit 0
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Generate kendo-keiko.com weekend Instagram Reel ($mode)" -Force | Out-Null
if ($Enable) {
    Enable-ScheduledTask -TaskName $TaskName | Out-Null
    Write-Output "Task registered and ENABLED."
} else {
    Disable-ScheduledTask -TaskName $TaskName | Out-Null
    Write-Output "Task registered but DISABLED. Enable only after auth and dry-run review."
}
