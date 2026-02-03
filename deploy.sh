#!/bin/bash

# ETTA-X Backend Deployment Script for Linux
# Usage: ./deploy.sh [--prod] [--port PORT]

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PORT=4567
ENVIRONMENT="development"
PYTHON_CMD="python3"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/venv"

# Parse command-line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --prod)
            ENVIRONMENT="production"
            shift
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--prod] [--port PORT]"
            exit 1
            ;;
    esac
done

# Print header
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}ETTA-X Backend Deployment${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "Environment: ${YELLOW}${ENVIRONMENT}${NC}"
echo -e "Port: ${YELLOW}${PORT}${NC}"
echo -e "Project Directory: ${YELLOW}${PROJECT_DIR}${NC}"
echo ""

# Check Python installation
echo -e "${YELLOW}[1/6] Checking Python installation...${NC}"
if ! command -v $PYTHON_CMD &> /dev/null; then
    echo -e "${RED}Error: Python 3 is not installed${NC}"
    exit 1
fi
PYTHON_VERSION=$($PYTHON_CMD --version)
echo -e "${GREEN}✓ Found: ${PYTHON_VERSION}${NC}"
echo ""

# Create virtual environment if it doesn't exist
echo -e "${YELLOW}[2/6] Setting up virtual environment...${NC}"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    $PYTHON_CMD -m venv "$VENV_DIR"
else
    echo "Virtual environment already exists"
fi
source "${VENV_DIR}/bin/activate"
echo -e "${GREEN}✓ Virtual environment ready${NC}"
echo ""

# Upgrade pip
echo -e "${YELLOW}[3/6] Upgrading pip...${NC}"
pip install --upgrade pip setuptools wheel > /dev/null
echo -e "${GREEN}✓ Pip upgraded${NC}"
echo ""

# Install dependencies
echo -e "${YELLOW}[4/6] Installing dependencies...${NC}"
pip install -q -r "${PROJECT_DIR}/requirements.txt"
echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

# Check and update .env
echo -e "${YELLOW}[5/6] Validating configuration...${NC}"
if [ ! -f "${PROJECT_DIR}/.env" ]; then
    echo -e "${RED}Warning: .env file not found${NC}"
    echo "Please create .env file with required configuration"
else
    echo -e "${GREEN}✓ .env file found${NC}"
    
    # Update APP_ENV in .env
    if grep -q "^APP_ENV=" "${PROJECT_DIR}/.env"; then
        sed -i "s/^APP_ENV=.*/APP_ENV=${ENVIRONMENT}/" "${PROJECT_DIR}/.env"
    else
        echo "APP_ENV=${ENVIRONMENT}" >> "${PROJECT_DIR}/.env"
    fi
fi
echo ""

# Test import
echo -e "${YELLOW}[6/6] Testing backend imports...${NC}"
$PYTHON_CMD -c "from backend.app.app import app; print('✓ Backend imports successful')"
echo ""

# Print startup command
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${YELLOW}To start the backend server, run:${NC}"
echo ""
echo -e "  ${GREEN}source ${VENV_DIR}/bin/activate${NC}"
echo -e "  ${GREEN}uvicorn backend.app.app:app --host 0.0.0.0 --port ${PORT}${NC}"
echo ""
echo -e "${YELLOW}Or use this command for production with workers:${NC}"
echo ""
echo -e "  ${GREEN}source ${VENV_DIR}/bin/activate${NC}"
echo -e "  ${GREEN}uvicorn backend.app.app:app --host 0.0.0.0 --port ${PORT} --workers 4${NC}"
echo ""
echo -e "${YELLOW}Optional: Using Gunicorn (for production):${NC}"
echo ""
echo -e "  ${GREEN}pip install gunicorn${NC}"
echo -e "  ${GREEN}gunicorn --workers 4 --bind 0.0.0.0:${PORT} --worker-class uvicorn.workers.UvicornWorker backend.app.app:app${NC}"
echo ""
echo -e "${YELLOW}API Health Check:${NC}"
echo -e "  ${GREEN}curl http://localhost:${PORT}/health${NC}"
echo ""
