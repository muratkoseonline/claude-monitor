@echo off
echo Claude Monitor kurulum basliyor...
echo.

REM Python kontrolu
python --version >nul 2>&1
if errorlevel 1 (
    echo HATA: Python bulunamadi!
    echo python.org adresinden Python 3.10+ kurun
    pause
    exit /b 1
)

echo Python bulundu. Bagimliliklar yukleniyor...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if errorlevel 1 (
    echo HATA: Paket kurulumu basarisiz
    pause
    exit /b 1
)

echo.
echo Kurulum tamamlandi!
echo.
echo Calistirmak icin: run.bat veya run_background.bat (konsol penceresi olmadan)
echo.
pause
