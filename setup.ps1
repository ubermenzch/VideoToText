param(
    [ValidateSet('venv','system')][string]$InstallMode = 'venv',
    [ValidateSet('auto','cuda','cpu')][string]$Device = 'auto',
    [ValidateSet('tiny','base','small','medium','large-v3')][string]$Model = '',
    [string]$Python = '',
    [string[]]$AlignmentLanguages = @(),
    [switch]$SkipModels,
    [switch]$NoTokenPrompt
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. "$PSScriptRoot\project-runtime.ps1"
Set-ProjectEnvironment
$tools = Join-Path $PSScriptRoot '.tools'
$logs = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Force -Path $tools,$logs | Out-Null
$statusFile = Join-Path $logs 'prepare-status.json'
$logFile = Join-Path $logs ('prepare-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
$step = 'Bootstrap Python'
$oldToken = $env:HF_TOKEN
$transcribing = $false

function Invoke-Checked {
    param([string]$Executable,[string[]]$CommandArgs)
    & $Executable @CommandArgs
    if ($LASTEXITCODE -ne 0) { throw "Command failed in '$script:step' (exit $LASTEXITCODE)." }
}
function Invoke-Retry {
    param([scriptblock]$Action)
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try { & $Action; return } catch {
            if ($attempt -eq 3) { throw }
            Write-Host "Attempt $attempt failed. Retrying in 10 seconds..."
            Start-Sleep -Seconds 10
        }
    }
}
function Set-Step([string]$Name) {
    $script:step = $Name
    Write-Host "`n>>> $Name" -ForegroundColor Cyan
    @{status='running';step=$Name;updated=(Get-Date).ToString('o')} |
        ConvertTo-Json | Set-Content -LiteralPath $statusFile -Encoding UTF8
}
function Test-Python([string]$Candidate) {
    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate)) { return $false }
    & $Candidate -c "import sys,struct; sys.exit(0 if sys.version_info[:2]==(3,11) and struct.calcsize('P')==8 else 1)" 2>$null
    return $LASTEXITCODE -eq 0
}
function Download-Bootstrap([string]$Url,[string]$Destination) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-Retry { Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination }
    $signature = Get-AuthenticodeSignature -LiteralPath $Destination
    $publisher = if ($Url -match 'python.org') { 'Python Software Foundation' } else { 'Microsoft Corporation' }
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch [regex]::Escape($publisher)) {
        throw "Invalid installer signature or publisher: $Destination"
    }
}
function Get-Archive([string]$Url,[string]$Destination) {
    $part = "$Destination.part"
    Invoke-Retry { Invoke-Checked $script:python @('-u',"$PSScriptRoot\download_asset.py",$Url,$part) }
    Move-Item -LiteralPath $part -Destination $Destination -Force
}
try {
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
        throw 'This installer supports Windows x64 only.'
    }
    Set-Step 'Locate or install Python 3.11 x64'
    if ($Python) {
        $basePython = (Resolve-Path -LiteralPath $Python).Path
        if (-not (Test-Python $basePython)) { throw '-Python must point to Python 3.11 x64.' }
    } else {
        $candidates = @("$tools\python\python.exe")
        $pyCommand = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($pyCommand) {
            try {
                $located = & $pyCommand.Source -3.11 -c 'import sys; print(sys.executable)' 2>$null
                if ($LASTEXITCODE -eq 0) { $candidates += [string]$located }
            } catch { $located = $null }
        }
        $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($pythonCommand) { $candidates += $pythonCommand.Source }
        # Discover official installers even when neither PATH nor py lists them.
        foreach ($registryPath in @(
            'HKCU:\Software\Python\PythonCore\3.11\InstallPath',
            'HKLM:\Software\Python\PythonCore\3.11\InstallPath'
        )) {
            $entry = Get-ItemProperty -LiteralPath $registryPath -ErrorAction SilentlyContinue
            if ($entry -and $entry.'(default)') {
                $candidates += Join-Path $entry.'(default)' 'python.exe'
            }
        }
        if ($InstallMode -eq 'venv') { $candidates += "$PSScriptRoot\.venv\Scripts\python.exe" }
        $basePython = $candidates | Where-Object { Test-Python $_ } | Select-Object -First 1
        if (-not $basePython) {
            $installer = Join-Path $tools 'python-3.11.9-amd64.exe'
            Download-Bootstrap 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' $installer
            $installArgs = @('/quiet','InstallAllUsers=0',('TargetDir="' + "$tools\python" + '"'),
                'Include_launcher=0','PrependPath=0','Include_test=0','Include_doc=0','Shortcuts=0')
            $process = Start-Process $installer -ArgumentList $installArgs -Wait -PassThru -WindowStyle Hidden
            if ($process.ExitCode -notin @(0,3010)) { throw "Python installer failed ($($process.ExitCode))." }
            $basePython = "$tools\python\python.exe"
            if (-not (Test-Python $basePython)) { throw 'Python installation could not be verified.' }
        }
    }
    if ($InstallMode -eq 'system') {
        & $basePython -c 'import sys; sys.exit(1 if sys.prefix != sys.base_prefix else 0)'
        if ($LASTEXITCODE -ne 0) { throw 'System mode requires a non-venv interpreter. Specify -Python.' }
        $python = $basePython
        Write-Host "Installing directly into: $python (existing packages may change)."
    } else {
        $python = "$PSScriptRoot\.venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $python)) { Invoke-Checked $basePython @('-m','venv',"$PSScriptRoot\.venv") }
        if (-not (Test-Python $python)) { throw 'Existing .venv is incompatible. Rename it and rerun setup.' }
    }
    Set-Step 'Check Microsoft Visual C++ runtime'
    if (-not (Test-Path -LiteralPath "$env:WINDIR\System32\vcruntime140_1.dll")) {
        $vcInstaller = Join-Path $tools 'vc_redist.x64.exe'
        Download-Bootstrap 'https://aka.ms/vs/17/release/vc_redist.x64.exe' $vcInstaller
        Write-Host 'The Microsoft runtime installer may request Windows administrator authorization.'
        $process = Start-Process $vcInstaller -ArgumentList '/install /quiet /norestart' -Wait -PassThru -WindowStyle Hidden
        if ($process.ExitCode -notin @(0,3010,1638)) { throw "VC++ runtime installer failed ($($process.ExitCode))." }
    }
    if ($Device -eq 'auto') {
        $nvidia = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
        $Device = 'cpu'
        if ($nvidia) {
            & $nvidia.Source --query-gpu=name --format=csv,noheader 2>$null | Out-Host
            if ($LASTEXITCODE -eq 0) { $Device = 'cuda' }
        }
    }
    if (-not $Model) { $Model = if ($Device -eq 'cuda') { 'large-v3' } else { 'small' } }
    # Hidden token input happens before console recording starts.
    Import-ProjectToken
    if (-not $SkipModels -and -not $env:HF_TOKEN) {
        if ($NoTokenPrompt) { throw 'Provide HF_TOKEN, or use -SkipModels for dependency-only setup.' }
        Write-Host 'Accept model conditions: https://huggingface.co/pyannote/speaker-diarization-community-1'
        Write-Host 'Create a read token: https://huggingface.co/settings/tokens'
        $secureToken = Read-Host 'Hugging Face read token (hidden input)' -AsSecureString
        $env:HF_TOKEN = [Net.NetworkCredential]::new('', $secureToken).Password
        try {
            $encrypted = ConvertFrom-SecureString -SecureString $secureToken
            New-Item -ItemType Directory -Force "$PSScriptRoot\.secrets" | Out-Null
            $encrypted | Set-Content -LiteralPath "$PSScriptRoot\.secrets\huggingface-token.encrypted" -Encoding ASCII
            $legacyKey = "$PSScriptRoot\.secrets\token.key"
            if (Test-Path -LiteralPath $legacyKey) { Remove-Item -LiteralPath $legacyKey }
        } catch {
            Write-Host 'Credential encryption unavailable. Token remains in this process only; set HF_TOKEN next time.'
        }
    }
    Start-Transcript -LiteralPath $logFile | Out-Null
    $transcribing = $true
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    $env:PIP_NO_CACHE_DIR = '1'
    Set-Step 'Install portable FFmpeg shared and Deno'
    $ffmpegBin = "$tools\ffmpeg\ffmpeg-7.1.1-full_build-shared\bin"
    if (-not (Test-Path -LiteralPath "$ffmpegBin\avcodec-61.dll")) {
        Get-Archive 'https://github.com/GyanD/codexffmpeg/releases/download/7.1.1/ffmpeg-7.1.1-full_build-shared.zip' "$tools\ffmpeg.zip"
        Expand-Archive -LiteralPath "$tools\ffmpeg.zip" -DestinationPath "$tools\ffmpeg" -Force
    }
    if (-not (Test-Path -LiteralPath "$tools\deno\deno.exe")) {
        Get-Archive 'https://github.com/denoland/deno/releases/download/v2.9.7/deno-x86_64-pc-windows-msvc.zip' "$tools\deno.zip"
        Expand-Archive -LiteralPath "$tools\deno.zip" -DestinationPath "$tools\deno" -Force
    }
    Invoke-Checked "$ffmpegBin\ffmpeg.exe" @('-version')
    Invoke-Checked "$tools\deno\deno.exe" @('--version')
    Set-Step 'Install Python packages'
    Invoke-Retry { Invoke-Checked $python @('-m','pip','install','--upgrade','pip','setuptools','wheel') }
    if ($Device -eq 'cuda') {
        Invoke-Retry { Invoke-Checked $python @('-u',"$PSScriptRoot\download_pytorch.py") }
        $torchPackages = @('torch-2.8.0+cu128','torchvision-0.23.0+cu128','torchaudio-2.8.0+cu128') |
            ForEach-Object { "$tools\wheels\$_-cp311-cp311-win_amd64.whl" }
        Invoke-Retry { Invoke-Checked $python (@('-m','pip','install','--timeout','120') + $torchPackages) }
    } else {
        Invoke-Retry { Invoke-Checked $python @('-m','pip','install','torch==2.8.0','torchvision==0.23.0','torchaudio==2.8.0','--index-url','https://download.pytorch.org/whl/cpu') }
    }
    Invoke-Retry { Invoke-Checked $python @('-m','pip','install','--timeout','120','-r',"$PSScriptRoot\requirements.txt") }
    Invoke-Checked $python @('-m','pip','check')
    Set-Step 'Validate runtime and prepare selected models'
    $prepareArgs = @('-u',"$PSScriptRoot\prepare_models.py",'--device',$Device,'--model',$Model)
    if ($SkipModels) { $prepareArgs += '--skip-models' }
    if ($AlignmentLanguages.Count) { $prepareArgs += @('--alignment-languages') + $AlignmentLanguages }
    Invoke-Checked $python $prepareArgs
    $storedPython = $python
    if ($python.StartsWith($PSScriptRoot + '\',[StringComparison]::OrdinalIgnoreCase)) {
        $storedPython = $python.Substring($PSScriptRoot.Length + 1)
    }
    @{python=$storedPython;device=$Device;model=$Model;installMode=$InstallMode} |
        ConvertTo-Json | Set-Content -LiteralPath "$PSScriptRoot\.videototext.json" -Encoding UTF8
    & $python -m pip freeze | Set-Content -LiteralPath "$logs\installed-packages.txt" -Encoding UTF8
    @{status='success';modelsPrepared=(-not $SkipModels.IsPresent);updated=(Get-Date).ToString('o')} |
        ConvertTo-Json | Set-Content -LiteralPath $statusFile -Encoding UTF8
    Write-Host "`nSUCCESS. Run: .\transcribe.cmd https://www.youtube.com/watch?v=VIDEO_ID" -ForegroundColor Green
} catch {
    $safeError = $_.Exception.Message -replace 'hf_[A-Za-z0-9]+','[REDACTED]'
    @{status='failed';step=$step;error=$safeError;updated=(Get-Date).ToString('o')} |
        ConvertTo-Json | Set-Content -LiteralPath $statusFile -Encoding UTF8
    Write-Host "`nFAILED at $step`: $safeError" -ForegroundColor Red
    exit 1
} finally {
    $env:HF_TOKEN = $oldToken
    if ($transcribing) { Stop-Transcript | Out-Null }
}
