# Shared project-relative configuration. Never changes the user's persistent PATH.
$script:ProjectRoot = $PSScriptRoot
$script:ConfigFile = Join-Path $ProjectRoot '.videototext.json'

function Get-ProjectConfig {
    if (Test-Path -LiteralPath $ConfigFile) {
        return Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    return [pscustomobject]@{ python = '.venv\Scripts\python.exe'; device = 'cuda'; model = 'large-v3' }
}

function Get-ProjectPython {
    $config = Get-ProjectConfig
    $path = [string]$config.python
    if (-not [System.IO.Path]::IsPathRooted($path)) { $path = Join-Path $ProjectRoot $path }
    if (-not (Test-Path -LiteralPath $path)) { throw 'Python environment missing. Run setup.cmd first.' }
    return $path
}

function Set-ProjectEnvironment {
    $env:VIDEO_TO_TEXT_ROOT = $ProjectRoot
    $env:HF_HOME = Join-Path $ProjectRoot '.cache\huggingface'
    $env:TORCH_HOME = Join-Path $ProjectRoot '.cache\torch'
    $env:NLTK_DATA = Join-Path $ProjectRoot '.cache\nltk'
    $env:MPLCONFIGDIR = Join-Path $ProjectRoot '.cache\matplotlib'
    $env:HF_HUB_DOWNLOAD_TIMEOUT = '120'
    $env:HF_HUB_ETAG_TIMEOUT = '60'
    $env:HF_HUB_DISABLE_TELEMETRY = '1'
    $env:HF_HUB_DISABLE_XET = '1'
    $env:PYANNOTE_METRICS_ENABLED = '0'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONUNBUFFERED = '1'
    $env:Path = "$(Join-Path $ProjectRoot '.tools\ffmpeg\ffmpeg-7.1.1-full_build-shared\bin');$(Join-Path $ProjectRoot '.tools\deno');$env:Path"
}

function Import-ProjectToken {
    if ($env:HF_TOKEN) { return }
    $secret = Join-Path $ProjectRoot '.secrets\huggingface-token.encrypted'
    if (Test-Path -LiteralPath $secret) {
        $key = Join-Path $ProjectRoot '.secrets\token.key'
        if (Test-Path -LiteralPath $key) {
            # Compatibility with credentials created by the original local setup.
            $credential = Get-Content -LiteralPath $secret -Raw | ConvertTo-SecureString -Key ([IO.File]::ReadAllBytes($key))
        } else {
            $credential = Get-Content -LiteralPath $secret -Raw | ConvertTo-SecureString
        }
        $env:HF_TOKEN = [Net.NetworkCredential]::new('', $credential).Password
    }
}
