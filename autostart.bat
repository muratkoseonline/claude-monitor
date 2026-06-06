@echo off
REM Windows baslangicindan itibaren otomatik calistirma
REM Bu dosyayi bir kez calistirin

set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set SCRIPT_DIR=%~dp0

REM VBScript ile gorünmez kısayol olustur (konsol penceresi olmadan)
set VBS_FILE=%TEMP%\create_shortcut.vbs

echo Set oWS = WScript.CreateObject("WScript.Shell") > "%VBS_FILE%"
echo sLinkFile = "%STARTUP%\ClaudeMonitor.lnk" >> "%VBS_FILE%"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%VBS_FILE%"
echo oLink.TargetPath = "pythonw.exe" >> "%VBS_FILE%"
echo oLink.Arguments = """%SCRIPT_DIR%claude_monitor.py""" >> "%VBS_FILE%"
echo oLink.WorkingDirectory = "%SCRIPT_DIR%" >> "%VBS_FILE%"
echo oLink.Description = "Claude Usage Monitor" >> "%VBS_FILE%"
echo oLink.Save >> "%VBS_FILE%"

cscript //nologo "%VBS_FILE%"
del "%VBS_FILE%"

echo.
echo Baslangiç kisayolu olusturuldu:
echo %STARTUP%\ClaudeMonitor.lnk
echo.
echo Windows her yeniden basladiginda otomatik calisacak.
echo Kaldirmak icin remove_autostart.bat calistirin.
pause
