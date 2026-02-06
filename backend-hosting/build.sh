#!/bin/bash
# Build script for Render deployment
# This script prepares the backend-hosting folder for deployment

echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Copying frontend files..."
if [ -d "../frontend" ]; then
    cp -r ../frontend ./frontend
    echo "Frontend copied successfully"
else
    echo "Warning: Frontend folder not found at ../frontend"
fi

echo "Build complete!"
