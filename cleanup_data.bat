@echo off
setlocal EnableExtensions EnableDelayedExpansion
pushd "%~dp0"

set "APP_ROOT=%CD%"
set "PERSIST_DIR=%APP_ROOT%\infrastructure\persistence\data"
set "RUNTIME_DIR=%APP_ROOT%\infrastructure\runtime"
set "TMP_DIR=%RUNTIME_DIR%\tmp"
set "LOGS_DIR=%RUNTIME_DIR%\logs"
set "AUDIO_DIR=%RUNTIME_DIR%\audio\assignments"
set "LEXICON_DB=%PERSIST_DIR%\lexicon.sqlite3"

set "ASSIGNMENTS_DB_RAW=%ASSIGNMENTS_DB_PATH%"
if not defined ASSIGNMENTS_DB_RAW set "ASSIGNMENTS_DB_RAW=assignments.db"
set "ASSIGNMENTS_DB=%ASSIGNMENTS_DB_RAW%"
if "%ASSIGNMENTS_DB:~1,1%"==":" (
    rem absolute path
) else if "%ASSIGNMENTS_DB:~0,2%"=="\\" (
    rem UNC path
) else (
    set "ASSIGNMENTS_DB=%PERSIST_DIR%\%ASSIGNMENTS_DB%"
)
if /I "%ASSIGNMENTS_DB%"=="%LEXICON_DB%" set "ASSIGNMENTS_DB=%PERSIST_DIR%\assignments.db"

:menu
cls
echo =====================================================
echo   CLEANUP MANAGER
echo =====================================================
echo Project root    : %APP_ROOT%
echo Lexicon DB      : %LEXICON_DB%
echo Assignments DB  : %ASSIGNMENTS_DB%
echo Audio directory : %AUDIO_DIR%
echo.
echo [1] Delete cache files only
echo [2] Delete all DB files ^(persistence + runtime^)
echo [3] Delete generated audio files only
echo [4] Delete audio metadata in table assignment_audio only
echo [5] Delete generated audio files + assignment_audio metadata
echo [6] Clear all DB tables ^(keep DB files^)
echo [7] FULL cleanup ^(cache + DB + audio files + audio metadata^)
echo [0] Exit
echo.
echo [WARNING] After confirmation, selected data WILL be deleted permanently.
echo.
set /p "CHOICE=Select option: "

if "%CHOICE%"=="0" goto :end
if "%CHOICE%"=="1" goto :option_cache
if "%CHOICE%"=="2" goto :option_db
if "%CHOICE%"=="3" goto :option_audio
if "%CHOICE%"=="4" goto :option_audio_meta
if "%CHOICE%"=="5" goto :option_audio_all
if "%CHOICE%"=="6" goto :option_db_truncate
if "%CHOICE%"=="7" goto :option_full

echo Invalid choice.
pause
goto :menu

:option_cache
call :confirm_action "Delete cache files and runtime cache directories?"
if errorlevel 1 goto :menu
call :clean_cache
goto :done

:option_db
call :confirm_action "Delete ALL database files from persistence/runtime?"
if errorlevel 1 goto :menu
call :clean_databases
goto :done

:option_audio
call :confirm_action "Delete all generated audio files?"
if errorlevel 1 goto :menu
call :clean_audio_files
goto :done

:option_audio_meta
call :confirm_action "Delete all rows from assignment_audio metadata table?"
if errorlevel 1 goto :menu
call :clean_audio_metadata
goto :done

:option_audio_all
call :confirm_action "Delete generated audio files and assignment_audio metadata?"
if errorlevel 1 goto :menu
call :clean_audio_files
call :clean_audio_metadata
goto :done

:option_full
call :confirm_action "Run FULL cleanup (cache + DB + audio files + assignment_audio metadata)?"
if errorlevel 1 goto :menu
call :clean_cache
call :clean_audio_files
call :clean_audio_metadata
call :clean_databases
goto :done

:option_db_truncate
call :confirm_action "Clear ALL data from DB tables (keep DB files)?"
if errorlevel 1 goto :menu
call :truncate_databases
goto :done

:confirm_action
echo.
echo [WARNING] %~1
set "CONFIRM="
set /p "CONFIRM=Type YES to continue: "
if /I "!CONFIRM!"=="YES" exit /b 0
echo Operation cancelled.
pause
exit /b 1

:clean_cache
echo [STEP] Removing Python/cache artifacts...
for /d /r "%APP_ROOT%" %%D in (__pycache__) do (
    if exist "%%~fD" rd /s /q "%%~fD" >nul 2>&1
)
for /r "%APP_ROOT%" %%F in (*.pyc) do del /f /q "%%~fF" >nul 2>&1
for /r "%APP_ROOT%" %%F in (*.pyo) do del /f /q "%%~fF" >nul 2>&1
for /r "%APP_ROOT%" %%F in (*.pyd) do del /f /q "%%~fF" >nul 2>&1

for %%D in (
    ".pytest_cache"
    "htmlcov"
    ".mypy_cache"
    ".ruff_cache"
    ".tmp"
    "tmp"
    "temp"
) do (
    if /I "%%~D"==".tmp" (
        call :clear_dir_contents "%APP_ROOT%\%%~D" ".gitignore"
    ) else (
        if exist "%APP_ROOT%\%%~D" rd /s /q "%APP_ROOT%\%%~D" >nul 2>&1
    )
)

for /r "%APP_ROOT%" %%F in (*.tmp) do del /f /q "%%~fF" >nul 2>&1
for /r "%APP_ROOT%" %%F in (*.temp) do del /f /q "%%~fF" >nul 2>&1
for /r "%APP_ROOT%" %%F in (*.cache) do del /f /q "%%~fF" >nul 2>&1
for /r "%APP_ROOT%" %%F in (*.log) do del /f /q "%%~fF" >nul 2>&1

if exist "%APP_ROOT%\.coverage" del /f /q "%APP_ROOT%\.coverage" >nul 2>&1
del /f /q "%APP_ROOT%\.coverage.*" >nul 2>&1
if exist "%APP_ROOT%\coverage.json" del /f /q "%APP_ROOT%\coverage.json" >nul 2>&1

call :clear_dir_contents "%TMP_DIR%" ".gitignore"
call :clear_dir_contents "%LOGS_DIR%" ""
echo [OK] Cache cleanup completed.
exit /b 0

:clean_databases
echo [STEP] Deleting database files...
if exist "%PERSIST_DIR%" (
    for /r "%PERSIST_DIR%" %%F in (*.sqlite3) do call :delete_db_file "%%~fF"
    for /r "%PERSIST_DIR%" %%F in (*.db) do call :delete_db_file "%%~fF"
)
if exist "%RUNTIME_DIR%" (
    for /r "%RUNTIME_DIR%" %%F in (*.sqlite3) do call :delete_db_file "%%~fF"
    for /r "%RUNTIME_DIR%" %%F in (*.db) do call :delete_db_file "%%~fF"
)
echo [OK] Database cleanup completed.
exit /b 0

:clean_audio_files
echo [STEP] Deleting generated audio files...
if exist "%AUDIO_DIR%" rd /s /q "%AUDIO_DIR%" >nul 2>&1
mkdir "%AUDIO_DIR%" >nul 2>&1
echo [OK] Audio files deleted.
exit /b 0

:clean_audio_metadata
echo [STEP] Deleting assignment_audio metadata rows...
call :resolve_python
if errorlevel 1 (
    echo [ERROR] Python runtime not found. Cannot clear assignment_audio metadata.
    exit /b 1
)

set "TARGET_ASSIGNMENTS_DB=%ASSIGNMENTS_DB%"
set "TMP_PY=%TEMP%\cleanup_assignment_audio_%RANDOM%_%RANDOM%.py"
> "%TMP_PY%" (
    echo import os
    echo import pathlib
    echo import sqlite3
    echo import sys
    echo db_path = pathlib.Path^(os.environ.get^("TARGET_ASSIGNMENTS_DB", ""^)^).expanduser^(^)
    echo if not db_path.exists^(^):
    echo ^    print^(f"[SKIP] assignments DB not found: {db_path}"^)
    echo ^    raise SystemExit^(0^)
    echo conn = sqlite3.connect^(db_path^)
    echo try:
    echo ^    cursor = conn.execute^("DELETE FROM assignment_audio"^)
    echo ^    conn.commit^(^)
    echo ^    deleted = cursor.rowcount if cursor.rowcount ^>= 0 else 0
    echo ^    print^(f"[OK] assignment_audio rows deleted: {deleted}"^)
    echo except sqlite3.OperationalError as exc:
    echo ^    if "no such table" in str^(exc^).lower^(^):
    echo ^        print^("[SKIP] table assignment_audio not found."^)
    echo ^        raise SystemExit^(0^)
    echo ^    raise
    echo finally:
    echo ^    conn.close^(^)
)

if defined PYTHON_ARGS (
    "%PYTHON_EXE%" %PYTHON_ARGS% "%TMP_PY%"
) else (
    "%PYTHON_EXE%" "%TMP_PY%"
)
set "PY_RC=%ERRORLEVEL%"
del /f /q "%TMP_PY%" >nul 2>&1
if not "%PY_RC%"=="0" (
    echo [ERROR] Failed to clear assignment_audio metadata.
    exit /b 1
)
echo [OK] Audio metadata cleanup completed.
exit /b 0

:truncate_databases
echo [STEP] Clearing all DB tables without deleting DB files...
call :resolve_python
if errorlevel 1 (
    echo [ERROR] Python runtime not found. Cannot truncate DB tables.
    exit /b 1
)
if exist "%PERSIST_DIR%" (
    for /r "%PERSIST_DIR%" %%F in (*.sqlite3) do call :truncate_db_file "%%~fF"
    for /r "%PERSIST_DIR%" %%F in (*.db) do call :truncate_db_file "%%~fF"
)
if exist "%RUNTIME_DIR%" (
    for /r "%RUNTIME_DIR%" %%F in (*.sqlite3) do call :truncate_db_file "%%~fF"
    for /r "%RUNTIME_DIR%" %%F in (*.db) do call :truncate_db_file "%%~fF"
)
echo [OK] DB table cleanup completed.
exit /b 0

:resolve_python
set "PYTHON_EXE="
set "PYTHON_ARGS="
if exist "%APP_ROOT%\.venv\Scripts\python.exe" set "PYTHON_EXE=%APP_ROOT%\.venv\Scripts\python.exe"
if not defined PYTHON_EXE (
    where python >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
    where py >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3"
    )
)
if not defined PYTHON_EXE exit /b 1
exit /b 0

:clear_dir_contents
set "TARGET_DIR=%~1"
set "KEEP_NAME=%~2"
if not exist "!TARGET_DIR!" exit /b 0
for /f "delims=" %%I in ('dir /b /a "!TARGET_DIR!" 2^>nul') do (
    if /I not "%%~I"=="!KEEP_NAME!" (
        if exist "!TARGET_DIR!\%%~I\*" (
            rd /s /q "!TARGET_DIR!\%%~I" >nul 2>&1
        ) else (
            del /f /q "!TARGET_DIR!\%%~I" >nul 2>&1
        )
    )
)
exit /b 0

:delete_db_file
set "DB_FILE=%~1"
if not defined DB_FILE exit /b 0
if exist "!DB_FILE!" (
    del /f /q "!DB_FILE!" >nul 2>&1
    echo [OK] Deleted: !DB_FILE!
)
for %%S in (-wal -shm -journal .journal) do (
    if exist "!DB_FILE!%%~S" (
        del /f /q "!DB_FILE!%%~S" >nul 2>&1
        echo [OK] Deleted: !DB_FILE!%%~S
    )
)
exit /b 0

:truncate_db_file
set "DB_FILE=%~1"
if not defined DB_FILE exit /b 0
if not exist "!DB_FILE!" exit /b 0
set "TARGET_DB_PATH=!DB_FILE!"
set "TMP_PY=%TEMP%\cleanup_db_truncate_%RANDOM%_%RANDOM%.py"
> "%TMP_PY%" (
    echo import os
    echo import pathlib
    echo import sqlite3
    echo db_path = pathlib.Path^(os.environ.get^("TARGET_DB_PATH", ""^)^).expanduser^(^)
    echo if not db_path.exists^(^):
    echo ^    raise SystemExit^(0^)
    echo conn = sqlite3.connect^(db_path^)
    echo try:
    echo ^    conn.execute^("PRAGMA foreign_keys=OFF"^)
    echo ^    table_rows = conn.execute^(
    echo ^        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%%' ORDER BY name"
    echo ^    ^).fetchall^(^)
    echo ^    table_names = [row[0] for row in table_rows if row and row[0]]
    echo ^    conn.execute^("BEGIN"^)
    echo ^    for table_name in table_names:
    echo ^        safe_table = str^(table_name^).replace^('"', '""'^)
    echo ^        conn.execute^(f'DELETE FROM "{safe_table}"'^)
    echo ^    try:
    echo ^        conn.execute^("DELETE FROM sqlite_sequence"^)
    echo ^    except sqlite3.OperationalError:
    echo ^        pass
    echo ^    conn.commit^(^)
    echo ^    print^(f"[OK] Cleared DB tables: {db_path} (tables={len^(table_names^)})"^)
    echo except Exception:
    echo ^    conn.rollback^(^)
    echo ^    raise
    echo finally:
    echo ^    conn.close^(^)
)
if defined PYTHON_ARGS (
    "%PYTHON_EXE%" %PYTHON_ARGS% "%TMP_PY%"
) else (
    "%PYTHON_EXE%" "%TMP_PY%"
)
set "PY_RC=%ERRORLEVEL%"
del /f /q "%TMP_PY%" >nul 2>&1
if not "%PY_RC%"=="0" (
    echo [ERROR] Failed to clear DB tables in: !DB_FILE!
    exit /b 1
)
exit /b 0

:done
echo.
echo [DONE] Selected cleanup operations finished.
echo [WARNING] Data has been deleted permanently.
echo.
pause
goto :menu

:end
echo Exit.
popd
exit /b 0
