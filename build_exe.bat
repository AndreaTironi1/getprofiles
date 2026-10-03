@echo off
rem Crea dist\GetProfiles-<versione>.exe (un solo file). Eseguire dalla cartella del progetto.
if not exist .venv\Scripts\python.exe (
  echo Manca .venv: creala con "python -m venv .venv" e installa requirements.txt
  exit /b 1
)
for /f %%v in ('.venv\Scripts\python -c "from version import __version__; print(__version__)"') do set VER=%%v
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\python -m PyInstaller --onefile --windowed --name GetProfiles-%VER% gui.py
echo.
echo Fatto. Copia dist\GetProfiles-%VER%.exe dove vuoi e mettigli accanto config.ini.
