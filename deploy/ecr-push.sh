#!/bin/bash

# ECR Deployment Script for Linux/Mac
# Usage: ./ecr-push.sh [region] [repository-name]

set -e

REGION="${1:-us-east-1}"
REPO_NAME="${2:-orderbot-app}"
IMAGE_NAME="openbot-app"

echo "========================================"
echo "ECR Deployment Script"
echo "Region: $REGION"
echo "Repository: $REPO_NAME"
echo "========================================"

# Get AWS Account ID
echo ""
echo "[1/6] Getting AWS Account ID..."
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)

if [ -z "$ACCOUNT_ID" ]; then
    echo "ERROR: Could not get AWS Account ID. Make sure AWS CLI is configured."
    echo "Run: aws configure"
    exit 1
fi
echo "Account ID: $ACCOUNT_ID"

ECR_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"
FULL_URI="$ECR_URI/$REPO_NAME"

# Create ECR repository if it doesn't exist
echo ""
echo "[2/6] Creating ECR repository if it doesn't exist..."
if ! aws ecr describe-repositories --repository-names "$REPO_NAME" --region "$REGION" >/dev/null 2>&1; then
    echo "Creating repository $REPO_NAME..."
    aws ecr create-repository \
        --repository-name "$REPO_NAME" \
        --region "$REGION" \
        --image-scanning-configuration scanOnPush=true
else
    echo "Repository already exists."
fi

# Login to ECR
echo ""
echo "[3/6] Logging in to ECR..."
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_URI"

# Build the Docker image
echo ""
echo "[4/6] Building Docker image..."
docker build -t "$IMAGE_NAME:latest" .

# Tag the image
echo ""
echo "[5/6] Tagging image for ECR..."
docker tag "$IMAGE_NAME:latest" "$FULL_URI:latest"

# Generate a version tag based on git commit
GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "")
if [ -n "$GIT_SHA" ]; then
    docker tag "$IMAGE_NAME:latest" "$FULL_URI:$GIT_SHA"
    echo "Tagged with git SHA: $GIT_SHA"
fi

# Push to ECR
echo ""
echo "[6/6] Pushing image to ECR..."
docker push "$FULL_URI:latest"

if [ -n "$GIT_SHA" ]; then
    docker push "$FULL_URI:$GIT_SHA"
fi

echo ""
echo "========================================"
echo "SUCCESS! Image pushed to ECR"
echo ""
echo "Image URI: $FULL_URI:latest"
[ -n "$GIT_SHA" ] && echo "Git SHA tag: $FULL_URI:$GIT_SHA"
echo ""
echo "Next steps:"
echo "1. Go to AWS Console > App Runner"
echo "2. Create a new service"
echo "3. Select 'Container registry' > 'Amazon ECR'"
echo "4. Choose the image: $FULL_URI:latest"
echo "5. Configure port: 8004"
echo "6. Add environment variables (DATABASE_URL, etc.)"
echo "========================================"
