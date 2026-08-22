@echo off
REM Daily trading-status snapshot (D13).
REM
REM Six of the eight sources this captures are current-state: they say what is
REM true today and keep no history. A suspension, a delisting or a change of
REM trading method is therefore observable only if somebody was looking that
REM day. Nothing recovers a day that was not captured -- 1589 永冠-KY was
REM suspended in April 2026 and no official source can now say when.
REM
REM Safe to run every day and safe to run twice: sources already held for the
REM day are skipped without asking the exchange again.
REM
REM Register with Windows Task Scheduler (run as the logged-in user, daily
REM at 18:00, after both markets have published):
REM
REM   schtasks /Create /TN "tw-alpha-daily-status" /SC DAILY /ST 18:00 ^
REM     /TR "\"%~f0\"" /F
REM
REM Check it afterwards with:  schtasks /Query /TN "tw-alpha-daily-status"

setlocal
set PYTHON=C:\project\tw-sepa-screener\.venv\Scripts\python.exe
set REPO=%~dp0..\..
set STORE=C:\tmp\tw-alpha-m3-trading-status-01
set PYTHONIOENCODING=utf-8

"%PYTHON%" "%REPO%\scripts\m3\capture_trading_status.py" --out-root "%STORE%"
set RESULT=%ERRORLEVEL%

REM A non-zero exit means at least one source neither captured nor was
REM already held. That is worth seeing rather than swallowing: the run is
REM appended to capture_ledger.jsonl either way, so the failure is on record.
if not "%RESULT%"=="0" (
  echo daily status snapshot FAILED with %RESULT% >> "%STORE%\capture_failures.log"
  echo %DATE% %TIME% >> "%STORE%\capture_failures.log"
)
exit /b %RESULT%
