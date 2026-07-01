@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ============================================
echo CURRENT DIRECTORY
echo ============================================
cd

if not exist "cdk.json" (
    echo ERROR: cdk.json nije pronadjen. Skripta mora da bude u root folderu projekta hacker-news-x.
    goto error
)

if not exist "app.py" (
    echo ERROR: app.py nije pronadjen. Skripta mora da bude u root folderu projekta hacker-news-x.
    goto error
)

echo.
echo ============================================
echo ACTIVATE VENV
echo ============================================
if not exist ".venv\Scripts\activate.bat" (
    echo ERROR: .venv nije pronadjen. Napravi ga komandom:
    echo python -m venv .venv
    goto error
)

call .venv\Scripts\activate.bat
if errorlevel 1 goto error

echo.
echo ============================================
echo TARGET DATE
echo ============================================
if "%~1"=="" (
    for /f %%i in ('powershell -NoProfile -Command "(Get-Date).ToUniversalTime().AddDays(-1).ToString('yyyy-MM-dd')"') do set TARGET_DATE=%%i
) else (
    set TARGET_DATE=%~1
)

echo Target date: %TARGET_DATE%

echo.
echo ============================================
echo TARGET SOURCE
echo ============================================
if "%~2"=="" (
    set TARGET_SOURCE=hacker-news
) else (
    set TARGET_SOURCE=%~2
)

if "%TARGET_SOURCE%"=="hacker-news" (
    set SOURCES_JSON=["hacker-news"]
) else if "%TARGET_SOURCE%"=="x" (
    set SOURCES_JSON=["x"]
) else if "%TARGET_SOURCE%"=="all" (
    set SOURCES_JSON=["hacker-news","x"]
) else (
    echo ERROR: Nepoznat source: %TARGET_SOURCE%
    echo Dozvoljeno:
    echo   hacker-news
    echo   x
    echo   all
    goto error
)

echo Target source: %TARGET_SOURCE%
echo Sources JSON: %SOURCES_JSON%

echo.
echo Primeri pokretanja:
echo   setup_and_test_silver.bat 2026-06-29 hacker-news
echo   setup_and_test_silver.bat 2020-07-25 x
echo   setup_and_test_silver.bat 2026-06-29 all

echo.
echo ============================================
echo PYTHON VERSION
echo ============================================
python --version
if errorlevel 1 goto error

echo.
echo ============================================
echo AWS CLI VERSION
echo ============================================
call aws --version
if errorlevel 1 goto error

echo.
echo ============================================
echo CDK VERSION
echo ============================================
call cdk --version
if errorlevel 1 goto error

echo.
echo ============================================
echo AWS IDENTITY
echo ============================================
call aws sts get-caller-identity
if errorlevel 1 goto error

echo.
echo ============================================
echo CDK SYNTH
echo ============================================
call cdk synth
if errorlevel 1 goto error

echo.
echo ============================================
echo DEPLOY DATA LAKE + SILVER
echo ============================================
call cdk deploy SocialMediaDataLakeStack SilverStack --require-approval never
if errorlevel 1 goto error

echo.
echo ============================================
echo FIND SILVER NORMALIZER LAMBDA
echo ============================================
for /f "delims=" %%F in ('aws lambda list-functions --query "Functions[?contains(FunctionName, 'SilverNormalizerLambda')].FunctionName | [0]" --output text') do set SILVER_LAMBDA=%%F

echo Silver Lambda: %SILVER_LAMBDA%

if "%SILVER_LAMBDA%"=="None" (
    echo ERROR: SilverNormalizerLambda nije pronadjena.
    goto error
)

if "%SILVER_LAMBDA%"=="" (
    echo ERROR: SilverNormalizerLambda nije pronadjena.
    goto error
)

echo.
echo ============================================
echo CREATE SILVER PAYLOAD
echo ============================================
echo {"target_date":"%TARGET_DATE%","sources":%SOURCES_JSON%,"mode":"overwrite_partitions"}> silver_payload.json

echo Payload:
type silver_payload.json

echo.
echo ============================================
echo INVOKE SILVER NORMALIZER
echo ============================================
call aws lambda invoke ^
  --function-name "%SILVER_LAMBDA%" ^
  --cli-binary-format raw-in-base64-out ^
  --cli-read-timeout 900 ^
  --cli-connect-timeout 60 ^
  --payload file://silver_payload.json ^
  silver_response.json > silver_invoke_result.json

if errorlevel 1 goto error

echo Invoke result:
type silver_invoke_result.json

findstr /C:"FunctionError" silver_invoke_result.json >nul
if not errorlevel 1 (
    echo.
    echo ERROR: Lambda returned FunctionError.
    echo Lambda response:
    type silver_response.json
    goto error
)

echo.
echo ============================================
echo SILVER RESPONSE
echo ============================================
type silver_response.json

echo.
echo.
echo ============================================
echo RELEVANT SILVER S3 CONTENTS
echo ============================================

if "%TARGET_SOURCE%"=="hacker-news" (
    call aws s3 ls s3://social-media-silver-cloud-team25/silver/posts/platform=hacker_news/ --recursive
    call aws s3 ls s3://social-media-silver-cloud-team25/silver/users/platform=hacker_news/ --recursive
) else if "%TARGET_SOURCE%"=="x" (
    call aws s3 ls s3://social-media-silver-cloud-team25/silver/posts/platform=x/ --recursive
    call aws s3 ls s3://social-media-silver-cloud-team25/silver/users/platform=x/ --recursive
) else (
    call aws s3 ls s3://social-media-silver-cloud-team25/silver/ --recursive
)

echo.
echo ============================================
echo DONE - SILVER TEST COMPLETED SUCCESSFULLY
echo ============================================
pause
exit /b 0

:error
echo.
echo ============================================
echo ERROR - CHECK MESSAGE ABOVE
echo ============================================
pause
exit /b 1