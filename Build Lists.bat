@echo off
REM Build the charity and advisor lists for the Mieruka console, from public filings only. Safe to run again.
REM Charities: IRS lists and each charity's latest 990. Advisors: the SEC file you saved in C:\Mieruka\Data\advisors.
setlocal
cd /d "%~dp0"
set "V=%~dp0.venv\Scripts\python.exe"
if exist "%V%" goto :ready
echo First run: setting up Python for these tools (a minute or two)...
set "PY="
if exist "%USERPROFILE%\miniconda3\python.exe" set "PY=%USERPROFILE%\miniconda3\python.exe"
if not defined PY if exist "%USERPROFILE%\anaconda3\python.exe" set "PY=%USERPROFILE%\anaconda3\python.exe"
if not defined PY for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%P"
if not defined PY for /f "delims=" %%P in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%P"
if not defined PY goto :nopython
"%PY%" -m venv .venv
if errorlevel 1 goto :fail
:ready
"%V%" -m pip install -q -e .
if errorlevel 1 goto :fail
if not exist "C:\Mieruka\Data\advisors" mkdir "C:\Mieruka\Data\advisors"
echo.
echo === Charities: reads up to 400 filings from the IRS, gently (about 20 to 40 minutes) ===
"%V%" -m funders charities --out "C:\Mieruka\Data\charities" --targets "C:\Mieruka\Data\outreach_targets_charities.csv"
echo.
echo === Advisors: from the SEC file in C:\Mieruka\Data\advisors ===
"%V%" -m funders advisors --sec-file "C:\Mieruka\Data\advisors" --out "C:\Mieruka\Data\advisors" --targets "C:\Mieruka\Data\outreach_targets_advisors.csv"
echo.
echo Done. Next: Import Charities.bat and Import Advisors.bat in C:\Mieruka\SweepConsole.
pause
exit /b 0
:nopython
echo Python 3.11 or newer wasn't found. Install it from python.org, then run this again.
pause
exit /b 1
:fail
echo Something went wrong above. Copy the messages to Claude.
pause
exit /b 1
