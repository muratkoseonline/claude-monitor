@echo off
set SHORTCUT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ClaudeMonitor.lnk

if exist "%SHORTCUT%" (
    del "%SHORTCUT%"
    echo Baslangiç kisayolu kaldirildi.
) else (
    echo Baslangiç kisayolu zaten mevcut degil.
)
pause
