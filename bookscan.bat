@echo off
REM Start the bookscan console and open it in the browser.
REM
REM This is the whole interface: job list, per-page inspection, re-run,
REM assemble, render, and the text editor are all pages of the one server.
REM Double-click this file; close the window to stop the server.
REM
REM The server binds 0.0.0.0 on purpose - the phone app uploads to it over the
REM local Wi-Fi, so it has to be reachable from the LAN, not just localhost.

setlocal
cd /d "%~dp0"

set PORT=8000
if not "%~1"=="" set PORT=%~1

echo Starting bookscan on port %PORT% ...
start "" http://127.0.0.1:%PORT%/
python -m uvicorn server.app:app --host 0.0.0.0 --port %PORT%

echo.
echo Server stopped.
pause
