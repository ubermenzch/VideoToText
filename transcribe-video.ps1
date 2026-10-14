param(
    [Parameter(Mandatory = $true)][string]$Url,
    [string]$Language = '',
    [int]$Speakers = 0,
    [ValidateSet('auto','cuda','cpu')][string]$Device = '',
    [ValidateSet('tiny','base','small','medium','large-v3')][string]$Model = '',
    [switch]$DownloadOnly
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\use-env.ps1"
$config = Get-ProjectConfig
if (-not $Device) { $Device = $config.device }
if (-not $Model) { $Model = $config.model }
New-Item -ItemType Directory -Force "$PSScriptRoot\logs" | Out-Null
$logFile = "$PSScriptRoot\logs\transcribe-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
Start-Transcript -LiteralPath $logFile | Out-Null
$exitCode = 1
try {
    if (-not ('TranscriptionPower' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class TranscriptionPower {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint state);
}
'@
    }
    [TranscriptionPower]::SetThreadExecutionState([uint32]2147483649) | Out-Null
    $env:PYTHONUNBUFFERED = '1'
    $env:VIDEO_TO_TEXT_LOG = "$PSScriptRoot\logs\transcribe-$(Get-Date -Format 'yyyyMMdd-HHmmss').console.log"
    $env:HF_HUB_DOWNLOAD_TIMEOUT = '120'
    $env:HF_HUB_ETAG_TIMEOUT = '60'
    $arguments = @('-u', "$PSScriptRoot\transcribe_video.py", $Url)
    if ($Language) { $arguments += @('--language', $Language) }
    if ($Speakers -gt 0) { $arguments += @('--speakers', "$Speakers") }
    $arguments += @('--device',$Device,'--model',$Model)
    if ($DownloadOnly) { $arguments += '--download-only' }
    & $ProjectPython @arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) { throw "Transcription failed. See $logFile" }
}
finally {
    if ('TranscriptionPower' -as [type]) { [TranscriptionPower]::SetThreadExecutionState([uint32]2147483648) | Out-Null }
    Stop-Transcript | Out-Null
}
exit $exitCode
