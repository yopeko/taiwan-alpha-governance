@echo off
REM M9 daily pipeline-shadow observation (option B, D22).
REM
REM Captures the day's official closing tables straight from TWSE and TPEx,
REM turns them into the same tables by the same code as the six-year build,
REM and writes one observation for that session.
REM
REM WHY THE CAPTURE IS HERE AND NOT A READ OF THE WAREHOUSE
REM
REM Until 2026-09-01 `capture_observation.py` read the warehouse, and so did
REM `observe_session.py` -- the same `PRICES` root on both sides. Divergence
REM could then only come from the warehouse having been rebuilt, never from
REM "what the day actually showed differs from what the warehouse says", which
REM is the one thing the shadow observation contract section 1 exists to
REM measure. Two sides reading one table is one answer compared with itself.
REM
REM This lane makes the observation an independent source. That is the whole
REM point of it, and the reason it captures rather than reads.
REM
REM COST, MEASURED BEFORE IT WAS BUILT
REM
REM A full staging rebuild is 79.8 minutes (M3.17) and generations are
REM additive, so a daily full rebuild was never viable. One capture root
REM through the same builders is 9 seconds plus 1, measured 2026-09-01 on an
REM existing archive. The capture itself is bounded by the 6-second politeness
REM interval, so a day is minutes.
REM
REM Registered 2026-09-03 (D24) as `tw-alpha-m9-observation`, daily at
REM **18:30** -- not the 18:00 this comment used to say.
REM
REM `tw-alpha-daily-status` has held 18:00 since 2026-08-22 and it also
REM captures from the exchanges. Two capture lanes starting together defeats
REM the per-lane politeness interval, and a 0.7-second interval once had this
REM machine's address refused by twse.com.tw for more than a day. The status
REM snapshot is eight sources and finishes in under a minute; half an hour is
REM more clearance than it needs, and clearance is the cheap side.
REM
REM   schtasks /Create /TN "tw-alpha-m9-observation" /SC DAILY /ST 18:30 ^
REM     /TR "\"%~f0\"" /F
REM
REM Safe to run on a non-trading day: the capture preserves the exchange's
REM non-trading response as evidence, and the observation records
REM `official-closed` rather than inventing a session.
REM
REM Safe to run twice: each day gets its own root and the second run refuses
REM on the non-empty staging directory rather than appending to it.

setlocal
set PYTHON=C:\project\tw-sepa-screener\.venv\Scripts\python.exe
set REPO=%~dp0..\..
set PYTHONIOENCODING=utf-8

REM Today, as yyyy-MM-dd, without depending on the machine's date format.
for /f %%d in ('%PYTHON% -c "import datetime;print(datetime.date.today().isoformat())"') do set SESSION=%%d

set LANE=C:\tmp\tw-alpha-m9-daily\%SESSION%
set FAILLOG=C:\tmp\tw-alpha-m9-daily\failures.log

echo [%SESSION%] 1/4 capture
"%PYTHON%" "%REPO%\scripts\m3\capture_window.py" ^
  --output-root "%LANE%\raw" --start %SESSION% --end %SESSION% --interval 6.0
if errorlevel 1 goto :failed

echo [%SESSION%] 2/4 staging
"%PYTHON%" "%REPO%\scripts\m3\build_staging.py" ^
  --staging-root "%LANE%\staging" --archive "%LANE%\raw"
if errorlevel 1 goto :failed

echo [%SESSION%] 3/4 prices
"%PYTHON%" "%REPO%\scripts\m3\build_prices_actions.py" ^
  --staging-root "%LANE%\staging" --out-root "%LANE%\prices"
if errorlevel 1 goto :failed

REM No --backfill-unusable: this must run on the session date or not at all.
REM A file written later is a reconstruction, and comparing a reconstruction
REM against the warehouse's reconstruction is one answer compared with itself.
echo [%SESSION%] 4/4 observation
"%PYTHON%" "%REPO%\scripts\m9\capture_observation.py" ^
  --out "%LANE%\observation.json" --session %SESSION% ^
  --prices-root "%LANE%\prices" --status-root "%LANE%\prices"
if errorlevel 1 goto :failed

echo [%SESSION%] ok
exit /b 0

:failed
REM A failed day is not counted -- shadow observation contract section 4 says
REM capture failures do not count towards the 60. Recorded rather than
REM swallowed, because a lane that fails silently reaches 60 on fewer days
REM than it claims.
echo %SESSION% FAILED with %ERRORLEVEL% >> "%FAILLOG%"
exit /b 1
