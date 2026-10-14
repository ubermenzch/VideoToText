# Dot-source: . .\use-env.ps1
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\project-runtime.ps1"
Set-ProjectEnvironment
Import-ProjectToken
$script:ProjectPython = Get-ProjectPython
$env:Path = "$(Split-Path -Parent $ProjectPython);$env:Path"
