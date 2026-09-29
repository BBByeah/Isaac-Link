$ErrorActionPreference = 'Stop'
try {
    $appFolder = Join-Path (Split-Path $PSScriptRoot -Parent) 'dist\Isaac-Link'
    $apps = @(Get-ChildItem -LiteralPath $appFolder -Filter '*.exe' | Where-Object Name -ne 'updater.exe')
    if ($apps.Count -ne 1) { throw 'Cannot find the desktop application in dist\Isaac-Link.' }
    Start-Process -FilePath $apps[0].FullName -WorkingDirectory $appFolder
} catch {
    Write-Host ('Unable to start Isaac-Link: ' + $_.Exception.Message)
    Read-Host 'Press Enter to close'
    exit 1
}
