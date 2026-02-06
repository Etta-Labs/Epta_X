# Environment Configuration Guide

## Overview
ETTA-X uses environment variables to configure the backend URL. This setup allows the Electron app to be packaged with the correct backend URL without hardcoding it in the source code.

## Configuration Files

### 1. Backend CORS Configuration
**File:** `backend/app/app.py`

The backend allows requests from these origins:
- `http://localhost:8000` - Local development
- `http://127.0.0.1:8000` - Local development
- `https://etta.gowshik.in` - Production backend
- `app://.` - Electron app origin
- `file://` - Electron file:// origin

### 2. Electron Environment
**File:** `electron/.env`

This file is packaged with the Electron build and contains:
```env
BACKEND_URL=https://etta.gowshik.in
APP_ENV=production
```

### 3. Web Frontend Configuration
**File:** `frontend/config/app-config.json`

Web application configuration:
```json
{
  "api": {
    "productionUrl": "https://etta.gowshik.in"
  }
}
```

## How It Works

### Electron App
1. On startup, `main.js` loads the `.env` file
2. The `BACKEND_URL` environment variable is read: `process.env.BACKEND_URL`
3. If not found, falls back to: `https://etta.gowshik.in`
4. The URL is exposed to the renderer process via IPC

### Frontend (Web/Electron)
1. Uses `frontend/static/api-config.js` helper module
2. Automatically detects if running in Electron or web browser
3. In Electron: Gets URL from `electronAPI.getBackendUrl()`
4. In Web: Loads from `app-config.json`
5. Fallback: `https://etta.gowshik.in`

## Usage in Frontend Code

```javascript
// Import the API helper
import { getBackendUrl, apiRequest } from '/static/api-config.js';

// Get backend URL
const backendUrl = await getBackendUrl();
console.log('Backend URL:', backendUrl);

// Make API request
const response = await apiRequest('/api/repos', {
  method: 'GET'
});
const data = await response.json();
```

## Building the Electron App

When you build the Electron app, the `.env` file is automatically included:

```bash
# Build for Windows
npm run build:win

# Build for macOS
npm run build:mac

# Build for Linux
npm run build:linux
```

The packaged app will have:
- `electron/.env` → Packaged in the app
- Backend URL is read from environment variables
- No need to modify source code for different environments

## Changing Backend URL

### For Development
Edit `electron/.env`:
```env
BACKEND_URL=http://localhost:8000
```

### For Production
Edit `electron/.env`:
```env
BACKEND_URL=https://etta.gowshik.in
```

### For Different Deployments
Create different `.env` files for different builds:
- `.env.production`
- `.env.staging`
- `.env.development`

Then copy the appropriate one to `.env` before building.

## Command Line Flags

The Electron app supports these flags:
- `--dev` - Development mode (uses local backend)
- `--local` - Force local backend (http://127.0.0.1:8000)
- `--remote` - Force remote backend (from BACKEND_URL env var)

```bash
# Run with local backend
npm start -- --local

# Run with remote backend
npm start -- --remote
```

## Security Notes

1. **CORS Configuration**: The backend only accepts requests from whitelisted origins
2. **Environment Variables**: Sensitive data should NOT be in `.env` for frontend apps
3. **HTTPS**: Production always uses HTTPS (etta.gowshik.in)
4. **Credentials**: API requests include credentials (cookies) for authentication

## Troubleshooting

### Backend URL Not Working
1. Check `electron/.env` file exists
2. Verify `BACKEND_URL` is set correctly
3. Check browser console for the logged backend URL
4. Ensure backend CORS includes your domain

### Build Not Including .env
1. Verify `package.json` includes `.env` in `files` array
2. Check electron-builder output for included files
3. Manually verify `.env` in the packaged app

### CORS Errors
1. Verify the origin is in `ALLOWED_ORIGINS` in `backend/app/app.py`
2. Check backend logs for CORS-related errors
3. Ensure requests include credentials: `credentials: 'include'`
