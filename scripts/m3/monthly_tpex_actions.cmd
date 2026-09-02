@echo off
REM Monthly refresh of the TPEx corporate-action lane for the current year.
REM
REM WHY THIS IS MONTHLY AND NOT DAILY
REM
REM TPEx publishes no range-based historical endpoint. Its only official
REM historical route is MOPS, queried one symbol-year at a time, and each
REM listing response is followed by one detail request per announcement. For
REM 2026 that is about 894 listing queries plus roughly 700 details -- some
REM 1,600 requests at the 6-second floor, so about two and a half hours.
REM
REM Estimated 2026-09-02, before scheduling anything. A daily run of this
REM would spend most of the day asking MOPS the same questions.
REM
REM WHY A FRESH OUTPUT ROOT EVERY TIME
REM
REM `capture_tpex_actions` skips a symbol-year it already holds as
REM hash-verified. That is right for resuming an interrupted run and wrong for
REM picking up new announcements: re-running into the same root would skip all
REM 894 symbol-years and find nothing. So each run gets its own dated root and
REM the lane is the union of them.
REM
REM WHY THE SYMBOL LIST IS DERIVED AND NOT REUSED
REM
REM The list is every TPEx symbol the exchange printed a close for during the
REM year, across every price table that covers part of it. Measured on
REM 2026-09-02: 894 symbols that way against 857 in the day's universe. The 37
REM difference is names that stopped trading during the year, and asking
REM today's membership about them finds nothing while reporting success.
REM
REM WHY keep_awake
REM
REM M3.17: the six-year staging build was killed by system sleep after six
REM minutes with no output, and two days earlier the TPEx capture died at 655
REM of 4,310 for the same reason. A run this long on a machine that sleeps
REM will not finish, and this capture cannot usefully resume -- see above.
REM
REM `keep_awake.py` holds a thread-level execution-state request. It changes
REM no setting, lapses when the process exits, and leaves the display free to
REM sleep. If a run still dies, the machine is on modern standby and the power
REM configuration is a person's decision; nothing here changes it.
REM
REM Register with Windows Task Scheduler (monthly, first day, 02:00 -- outside
REM market hours and outside the daily lanes):
REM
REM   schtasks /Create /TN "tw-alpha-tpex-actions-monthly" /SC MONTHLY /D 1 ^
REM     /ST 02:00 /TR "\"%~f0\"" /F

setlocal
set PYTHON=C:\project\tw-sepa-screener\.venv\Scripts\python.exe
set REPO=%~dp0..\..
set PYTHONIOENCODING=utf-8

REM Every price table that covers part of the target year. Add the current
REM daily-lane output here once M9's lane is scheduled, or the last weeks of
REM the year will be missing from the symbol list.
set PRICES_A=C:\tmp\tw-alpha-m3-pit-prices-12
set PRICES_B=C:\tmp\tw-alpha-m3-gap-2026-08\prices

for /f %%y in ('%PYTHON% -c "import datetime;print(datetime.date.today().year)"') do set YEAR=%%y
for /f %%s in ('%PYTHON% -c "import datetime;print(datetime.date.today().isoformat())"') do set TODAY=%%s

set SYMBOLS=C:\tmp\tw-alpha-tpex-symbols\%YEAR%.json
set OUT=C:\tmp\tw-alpha-m3-tpex-actions-%YEAR%-refresh-%TODAY%
set FAILLOG=C:\tmp\tw-alpha-m3-tpex-actions-failures.log

REM ROC year = Gregorian - 1911.
for /f %%r in ('%PYTHON% -c "print(%YEAR% - 1911)"') do set ROC=%%r

echo [%TODAY%] 1/2 deriving the %YEAR% TPEx symbol list
"%PYTHON%" "%REPO%\scripts\m3\tpex_symbols_for_year.py" ^
  --prices-root "%PRICES_A%" --prices-root "%PRICES_B%" ^
  --year %YEAR% --out "%SYMBOLS%"
if errorlevel 1 goto :failed

echo [%TODAY%] 2/2 capturing, held awake, roughly two and a half hours
"%PYTHON%" "%REPO%\scripts\m3\keep_awake.py" --label "tpex-actions-%YEAR%" -- ^
  "%PYTHON%" "%REPO%\scripts\m3\capture_tpex_actions.py" ^
  --output-root "%OUT%" --symbols "%SYMBOLS%" --roc-years %ROC% --interval 6.0
if errorlevel 1 goto :failed

echo [%TODAY%] ok  %OUT%
exit /b 0

:failed
REM Recorded rather than swallowed. A capture that fails quietly leaves the
REM lane short by an unknown amount, and the coverage ledger is the only thing
REM that would eventually notice -- after the fact.
echo %TODAY% FAILED with %ERRORLEVEL% >> "%FAILLOG%"
exit /b 1
