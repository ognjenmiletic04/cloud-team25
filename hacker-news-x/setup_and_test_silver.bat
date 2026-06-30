@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ============================================
echo ACTIVATE VENV
echo ============================================
call .venv\Scripts\activate.bat

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
echo {"target_date":"%TARGET_DATE%","sources":["hacker-news","x"],"mode":"overwrite_partitions"}> silver_payload.json

echo Payload:
type silver_payload.json

echo.
echo ============================================
echo INVOKE SILVER NORMALIZER
echo ============================================
call aws lambda invoke ^
  --function-name "%SILVER_LAMBDA%" ^
  --cli-binary-format raw-in-base64-out ^
  --payload file://silver_payload.json ^
  silver_response.json

if errorlevel 1 goto error

echo.
echo ============================================
echo SILVER RESPONSE
echo ============================================
type silver_response.json

echo.
echo.
echo ============================================
echo SILVER S3 CONTENTS
echo ============================================
call aws s3 ls s3://social-media-silver-cloud-team25/silver/ --recursive

echo.
echo ============================================
echo DONE - SILVER TEST COMPLETED
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