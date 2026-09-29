@echo off
set "ISAAC_LINK_DIR=%~dp0"
powershell.exe -NoProfile -Command "$apps=@(Get-ChildItem -LiteralPath $env:ISAAC_LINK_DIR -Filter '*.exe' | Where-Object Name -ne 'updater.exe'); if($apps.Count -eq 1){Start-Process -FilePath $apps[0].FullName -WorkingDirectory ([System.IO.Path]::GetTempPath())}else{Write-Host 'Place this launcher next to the application EXE.'; Read-Host 'Press Enter'}"
