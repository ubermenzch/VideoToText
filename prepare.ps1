# Compatibility entry point. New users should run setup.cmd.
& "$PSScriptRoot\setup.ps1" @args
exit $LASTEXITCODE
