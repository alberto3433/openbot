@echo off
setlocal enabledelayedexpansion

REM ECR Deployment Script for Windows
REM Usage: ecr-push.bat [region] [repository-name]

set REGION=%1
if "%REGION%"=="" set REGION=us-east-1

set REPO_NAME=%2
if "%REPO_NAME%"=="" set REPO_NAME=orderbot-app

set IMAGE_NAME=openbot-app

echo ========================================
echo ECR Deployment Script
echo Region: %REGION%
echo Repository: %REPO_NAME%
echo ========================================

REM Get AWS Account ID
echo.
echo [1/6] Getting AWS Account ID...
for /f "tokens=*" %%i in ('aws sts get-caller-identity --query Account --output text 2^>nul') do set ACCOUNT_ID=%%i

if "%ACCOUNT_ID%"=="" (
    echo ERROR: Could not get AWS Account ID. Make sure AWS CLI is configured.
    echo Run: aws configure
    exit /b 1
)
echo Account ID: %ACCOUNT_ID%

set ECR_URI=%ACCOUNT_ID%.dkr.ecr.%REGION%.amazonaws.com
set FULL_URI=%ECR_URI%/%REPO_NAME%

REM Create ECR repository if it doesn't exist
echo.
echo [2/6] Creating ECR repository if it doesn't exist...
aws ecr describe-repositories --repository-names %REPO_NAME% --region %REGION% >nul 2>&1
if errorlevel 1 (
    echo Creating repository %REPO_NAME%...
    aws ecr create-repository --repository-name %REPO_NAME% --region %REGION% --image-scanning-configuration scanOnPush=true
    if errorlevel 1 (
        echo ERROR: Failed to create ECR repository
        exit /b 1
    )
) else (
    echo Repository already exists.
)

REM Login to ECR
echo.
echo [3/6] Logging in to ECR...
aws ecr get-login-password --region %REGION% | docker login --username AWS --password-stdin %ECR_URI%
if errorlevel 1 (
    echo ERROR: Failed to login to ECR
    exit /b 1
)

REM Build the Docker image
echo.
echo [4/6] Building Docker image...
docker build -t %IMAGE_NAME%:latest .
if errorlevel 1 (
    echo ERROR: Failed to build Docker image
    exit /b 1
)

REM Tag the image
echo.
echo [5/6] Tagging image for ECR...
docker tag %IMAGE_NAME%:latest %FULL_URI%:latest

REM Generate a version tag based on git commit
for /f "tokens=*" %%i in ('git rev-parse --short HEAD 2^>nul') do set GIT_SHA=%%i
if not "%GIT_SHA%"=="" (
    docker tag %IMAGE_NAME%:latest %FULL_URI%:%GIT_SHA%
    echo Tagged with git SHA: %GIT_SHA%
)

REM Push to ECR
echo.
echo [6/6] Pushing image to ECR...
docker push %FULL_URI%:latest
if errorlevel 1 (
    echo ERROR: Failed to push image to ECR
    exit /b 1
)

if not "%GIT_SHA%"=="" (
    docker push %FULL_URI%:%GIT_SHA%
)

echo.
echo ========================================
echo SUCCESS! Image pushed to ECR
echo.
echo Image URI: %FULL_URI%:latest
if not "%GIT_SHA%"=="" echo Git SHA tag: %FULL_URI%:%GIT_SHA%
echo.
echo Next steps:
echo 1. Go to AWS Console ^> App Runner
echo 2. Create a new service
echo 3. Select "Container registry" ^> "Amazon ECR"
echo 4. Choose the image: %FULL_URI%:latest
echo 5. Configure port: 8006
echo 6. Add environment variables (DATABASE_URL, etc.)
echo ========================================

endlocal
