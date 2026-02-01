# ETTA-X Desktop Application

Electron-based desktop application for ETTA-X - AI Test Automation Platform.

## Features

- **Custom Title Bar**: Frameless window with dynamic theming
- **Theme Synchronization**: Menu bar and app theme stay in sync
- **Integrated Backend**: Automatically starts the FastAPI backend server
- **Cross-Platform**: Builds available for Windows, macOS, and Linux

## Development Setup

### Prerequisites

- Node.js 18+ installed
- Python 3.9+ installed
- Project dependencies installed

### Install Dependencies

```bash
cd electron
npm install
```

### Run in Development Mode

Make sure the backend server is running first:

```bash
# In the project root
python -m uvicorn backend.app.app:app --reload --port 8000
```

Then start the Electron app in dev mode:

```bash
cd electron
npm run dev
```

### Run in Production Mode

This will start the backend server automatically:

```bash
cd electron
npm start
```

## Building for Production

### Windows

```bash
npm run build:win
```

### macOS

```bash
npm run build:mac
```

### Linux

```bash
npm run build:linux
```

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Shift+T` | Toggle Theme |
| `Ctrl+R` | Reload |
| `Ctrl+Shift+I` | Toggle Developer Tools |
| `F11` | Toggle Fullscreen |

## Project Structure

```
electron/
├── main.js          # Main Electron process
├── preload.js       # Secure bridge for IPC
├── package.json     # Dependencies and build config
├── assets/          # App icons and assets
│   ├── icon.png     # App icon (Linux)
│   ├── icon.ico     # App icon (Windows)
│   └── icon.icns    # App icon (macOS)
└── README.md        # This file
```
