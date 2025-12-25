# AWS Deployment Guide

This guide covers deploying the OrderBot application to AWS App Runner using Amazon ECR.

## Prerequisites

1. **AWS CLI** installed and configured
   ```bash
   aws configure
   ```

2. **Docker** installed and running

3. **AWS IAM Permissions** - Your AWS user/role needs:
   - `ecr:CreateRepository`
   - `ecr:GetAuthorizationToken`
   - `ecr:BatchCheckLayerAvailability`
   - `ecr:PutImage`
   - `ecr:InitiateLayerUpload`
   - `ecr:UploadLayerPart`
   - `ecr:CompleteLayerUpload`

## Step 1: Push Image to ECR

### Windows
```cmd
cd deploy
ecr-push.bat [region] [repository-name]

# Examples:
ecr-push.bat                      # Uses defaults: us-east-1, orderbot-app
ecr-push.bat us-west-2            # Custom region
ecr-push.bat us-east-1 myapp      # Custom region and repo name
```

### Linux/Mac
```bash
cd deploy
chmod +x ecr-push.sh
./ecr-push.sh [region] [repository-name]

# Examples:
./ecr-push.sh                     # Uses defaults: us-east-1, orderbot-app
./ecr-push.sh us-west-2           # Custom region
./ecr-push.sh us-east-1 myapp     # Custom region and repo name
```

## Step 2: Set Up Database

App Runner doesn't include a database. Choose one of these options:

### Option A: Amazon RDS PostgreSQL (Recommended for production)
1. Go to AWS Console > RDS > Create database
2. Choose PostgreSQL
3. Configure:
   - DB instance identifier: `orderbot-db`
   - Master username: `orderbot`
   - Create a password
   - Enable public access (or use VPC connector with App Runner)
4. Note the endpoint URL after creation

### Option B: Neon (Serverless PostgreSQL - simpler setup)
1. Go to https://neon.tech
2. Create a new project
3. Copy the connection string

## Step 3: Create App Runner Service

1. Go to **AWS Console > App Runner > Create service**

2. **Source configuration:**
   - Repository type: Container registry
   - Provider: Amazon ECR
   - Browse and select your image

3. **Deployment settings:**
   - Deployment trigger: Manual (or Automatic for CI/CD)
   - ECR access role: Create new or use existing

4. **Service settings:**
   - Service name: `orderbot-app`
   - Port: `8006`
   - CPU: 1 vCPU (adjust as needed)
   - Memory: 2 GB (adjust as needed)

5. **Environment variables:**
   ```
   DATABASE_URL=postgresql://user:password@host:5432/zuckers_db
   VAPI_API_KEY=your-vapi-key
   OPENAI_API_KEY=your-openai-key
   # Add other env vars from your .env file
   ```

6. **Health check:**
   - Path: `/health`
   - Protocol: HTTP

7. Click **Create & deploy**

## Step 4: Configure Custom Domain (Optional)

1. In your App Runner service, go to **Custom domains**
2. Click **Link domain**
3. Enter your domain name
4. Add the provided CNAME records to your DNS

## Environment Variables Reference

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `VAPI_API_KEY` | VAPI API key for voice | Yes |
| `OPENAI_API_KEY` | OpenAI API key | Yes |
| `ADMIN_USERNAME` | Admin panel username | Yes |
| `ADMIN_PASSWORD` | Admin panel password | Yes |

## Troubleshooting

### Image push fails with "no basic auth credentials"
```bash
# Re-authenticate with ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com
```

### App Runner service fails to start
- Check the App Runner logs in the AWS Console
- Verify all environment variables are set correctly
- Ensure the database is accessible from App Runner

### Database connection issues
- If using RDS, ensure security group allows inbound traffic on port 5432
- For private RDS, set up a VPC connector in App Runner
