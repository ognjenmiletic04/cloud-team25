@echo off

call .venv\Scripts\activate.bat

echo ============================================
echo PYTHON VERSION
echo ============================================
python --version

echo.
echo ============================================
echo AWS CLI VERSION
echo ============================================
call aws --version

echo.
echo ============================================
echo CDK VERSION
echo ============================================
call cdk --version

echo.
echo ============================================
echo CDK SYNTH
echo ============================================
call cdk synth

echo.
echo ============================================
echo AWS IDENTITY
echo ============================================
call aws sts get-caller-identity

echo.
echo ============================================
echo DEPLOY
echo ============================================
call cdk deploy --all --require-approval never

echo.
echo ============================================
echo S3 CONTENTS
echo ============================================
call aws s3 ls s3://social-media-bronze-cloud-team25/bronze/ --recursive

echo.
echo DONE
pause