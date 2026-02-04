const { app, BrowserWindow, ipcMain, shell, session, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');
const https = require('https');

// Load environment variables from .env file
require('dotenv').config({ path: path.join(__dirname, '..', '.env') });

// Set app name for protocol handler (makes browser say "Open ETTA-X" not "Open Electron")
app.setName('ETTA-X');

// ========== Logging Helper ==========
function log(message, type = 'INFO') {
    const timestamp = new Date().toISOString().replace('T', ' ').split('.')[0];
    const formattedMessage = `[${timestamp}] [${type}] ${message}`;
    
    // Always print to stdout for terminal visibility
    process.stdout.write(formattedMessage + '\n');
    
    // Also send to renderer if window exists
    if (mainWindow && mainWindow.webContents) {
        mainWindow.webContents.send('backend-log', { type, message, timestamp });
    }
}

function logBackend(message) {
    const timestamp = new Date().toISOString().replace('T', ' ').split('.')[0];
    const formattedMessage = `[${timestamp}] [BACKEND] ${message.trim()}`;
    
    // Print to stdout
    process.stdout.write(formattedMessage + '\n');
    
    // Send to renderer
    if (mainWindow && mainWindow.webContents) {
        mainWindow.webContents.send('backend-log', { type: 'BACKEND', message: message.trim(), timestamp });
    }
}

// Custom protocol for OAuth callback
const PROTOCOL_NAME = 'ettax';
const PROTOCOL_PREFIX = `${PROTOCOL_NAME}://`;

// Register as default protocol client (for deep linking)
// Note: On Windows, to fully change the name shown in the browser dialog,
// the app needs to be installed/built, or registry needs to be updated manually
if (process.defaultApp) {
    if (process.argv.length >= 2) {
        app.setAsDefaultProtocolClient(PROTOCOL_NAME, process.execPath, [path.resolve(process.argv[1])]);
    }
} else {
    app.setAsDefaultProtocolClient(PROTOCOL_NAME);
}

// Configuration
// Set USE_REMOTE_SERVER to true for client-server architecture (connects to remote backend)
// Set to false for standalone mode (runs backend locally)
const USE_REMOTE_SERVER = true;
const REMOTE_SERVER_URL = process.env.BACKEND_URL || 'https://etta.gowshik.online';
const LOCAL_PORT = 4567;

// API URL for backend calls
const API_URL = USE_REMOTE_SERVER ? REMOTE_SERVER_URL : `http://127.0.0.1:${LOCAL_PORT}`;
// Keep APP_URL for backwards compatibility
const APP_URL = API_URL;

// Log the backend URL being used
console.log(`[CONFIG] Backend URL: ${REMOTE_SERVER_URL}`);

// Path to local frontend pages
const FRONTEND_PATH = path.join(__dirname, '..', 'frontend', 'pages');

const isDev = process.argv.includes('--dev');
const forceSetup = process.argv.includes('--setup');

let mainWindow;
let backendProcess;
let currentTheme = 'light';

// Track if we're currently waiting for OAuth callback
let awaitingOAuth = false;

/**
 * Handle custom protocol URL (ettax://auth?token=xxx)
 */
function handleProtocolUrl(url) {
    log(`Received protocol URL: ${url}`);

    if (url.startsWith(PROTOCOL_PREFIX + 'auth')) {
        // Only process if we're actually awaiting OAuth
        if (!awaitingOAuth) {
            log('Ignoring stale OAuth callback - not awaiting OAuth');
            return;
        }

        // Parse the URL to get token
        const urlObj = new URL(url);
        const token = urlObj.searchParams.get('token');
        const setupMode = urlObj.searchParams.get('setup') === 'true';

        if (token && mainWindow) {
            awaitingOAuth = false; // Reset flag
            // Send token to renderer to complete auth
            mainWindow.webContents.send('oauth-callback', { token, setupMode });

            // Focus the window
            if (mainWindow.isMinimized()) mainWindow.restore();
            mainWindow.focus();
        }
    }
}

// Handle protocol URL on Windows (single instance)
const gotTheLock = app.requestSingleInstanceLock();

if (!gotTheLock) {
    app.quit();
} else {
    app.on('second-instance', (event, commandLine) => {
        // Someone tried to run a second instance, focus our window
        if (mainWindow) {
            if (mainWindow.isMinimized()) mainWindow.restore();
            mainWindow.focus();
        }

        // Handle the protocol URL from second instance
        const url = commandLine.find(arg => arg.startsWith(PROTOCOL_PREFIX));
        if (url) {
            handleProtocolUrl(url);
        }
    });
}

// Handle protocol URL on macOS
app.on('open-url', (event, url) => {
    event.preventDefault();
    handleProtocolUrl(url);
});

/**
 * Create the main application window
 */
function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1400,
        height: 900,
        minWidth: 1024,
        minHeight: 700,
        icon: path.join(__dirname, 'assets', 'icon.png'),

        // Frameless for custom title bar
        frame: false,
        titleBarStyle: 'hidden',

        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.js'),
            webSecurity: true,
            spellcheck: false
        },

        show: false,
        backgroundColor: currentTheme === 'dark' ? '#1e1e1e' : '#ffffff'
    });

    // Start maximized
    mainWindow.maximize();

    // Show window when ready
    mainWindow.once('ready-to-show', () => {
        mainWindow.show();
    });

    // ONLY intercept navigation to github.com - open OAuth in external browser
    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
        // Only external links that aren't our backend (local or remote)
        const isBackendUrl = url.startsWith(APP_URL) || 
                            url.includes('127.0.0.1') || 
                            url.includes('localhost') ||
                            url.includes('etta.gowshik.online');
        if (!isBackendUrl) {
            shell.openExternal(url);
            return { action: 'deny' };
        }
        return { action: 'allow' };
    });

    // Load the app - use local HTML files
    // fresh=true for setup mode to force clean state
    let startPage;
    if (forceSetup) {
        startPage = path.join(FRONTEND_PATH, 'setup.html');
    } else {
        startPage = path.join(FRONTEND_PATH, 'landing.html');
    }
    mainWindow.loadFile(startPage);

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

/**
 * Clear all session data
 */
async function clearAllSessionData() {
    const ses = session.defaultSession;
    await ses.clearStorageData({
        storages: ['cookies', 'localstorage', 'sessionstorage', 'cachestorage', 'indexdb']
    });
    await ses.clearCache();
    log('Session data cleared');

    if (mainWindow) {
        mainWindow.loadFile(path.join(FRONTEND_PATH, 'setup.html'));
    }
}

// ========== IPC Handlers for Custom Title Bar ==========

// Window controls
ipcMain.on('window-minimize', () => {
    if (mainWindow) mainWindow.minimize();
});

ipcMain.on('window-maximize', () => {
    if (mainWindow) {
        if (mainWindow.isMaximized()) {
            mainWindow.unmaximize();
        } else {
            mainWindow.maximize();
        }
    }
});

ipcMain.on('window-close', () => {
    if (mainWindow) mainWindow.close();
});

// App actions
ipcMain.on('app-reload', () => {
    if (mainWindow) mainWindow.reload();
});

ipcMain.on('app-clear-cache', async () => {
    await clearAllSessionData();
});

ipcMain.on('app-quit', () => {
    app.quit();
});

// Native confirm dialog - bypasses CSS stacking issues in frameless window
ipcMain.handle('show-confirm-dialog', async (event, options) => {
    const result = await dialog.showMessageBox(mainWindow, {
        type: options.type || 'question',
        title: options.title || 'Confirm',
        message: options.message,
        detail: options.detail || '',
        buttons: options.buttons || ['OK', 'Cancel'],
        defaultId: 0,
        cancelId: 1
    });
    return result.response === 0; // Returns true if first button (OK/Confirm) clicked
});

// OAuth - open GitHub auth URL in external browser
ipcMain.on('open-oauth', (event, { url }) => {
    log(`Opening OAuth URL in external browser: ${url}`);
    awaitingOAuth = true; // Mark that we're now waiting for OAuth callback
    shell.openExternal(url);
});

// View actions
ipcMain.on('view-zoom-in', () => {
    if (mainWindow) {
        const zoom = mainWindow.webContents.getZoomLevel();
        mainWindow.webContents.setZoomLevel(zoom + 0.5);
    }
});

ipcMain.on('view-zoom-out', () => {
    if (mainWindow) {
        const zoom = mainWindow.webContents.getZoomLevel();
        mainWindow.webContents.setZoomLevel(zoom - 0.5);
    }
});

ipcMain.on('view-reset-zoom', () => {
    if (mainWindow) {
        mainWindow.webContents.setZoomLevel(0);
    }
});

ipcMain.on('view-toggle-fullscreen', () => {
    if (mainWindow) {
        mainWindow.setFullScreen(!mainWindow.isFullScreen());
    }
});

ipcMain.on('view-toggle-devtools', () => {
    if (mainWindow) mainWindow.webContents.toggleDevTools();
});

// Help
ipcMain.on('help-about', () => {
    const { dialog } = require('electron');
    dialog.showMessageBox(mainWindow, {
        type: 'info',
        title: 'About ETTA-X',
        message: 'ETTA-X - AI Test Automation Platform',
        detail: 'Version 1.0.0\n\nIntelligent test automation powered by AI.',
        buttons: ['OK']
    });
});

// Theme handlers
ipcMain.handle('get-theme', () => currentTheme);

// Backend URL handler - returns the configured backend URL from environment
ipcMain.handle('get-backend-url', () => REMOTE_SERVER_URL);

ipcMain.handle('set-theme', (event, theme) => {
    currentTheme = theme;
    if (mainWindow) {
        mainWindow.setBackgroundColor(currentTheme === 'dark' ? '#1e1e1e' : '#ffffff');
    }
});

ipcMain.on('sync-theme', (event, theme) => {
    if (theme !== currentTheme) {
        currentTheme = theme;
        if (mainWindow) {
            mainWindow.setBackgroundColor(currentTheme === 'dark' ? '#1e1e1e' : '#ffffff');
        }
    }
});

// ========== Backend Management ==========

function startBackend() {
    return new Promise((resolve, reject) => {
        let pythonCmd;
        let uvicornArgs;

        // In dev mode, use the virtual environment Python with --reload
        if (isDev) {
            const venvPath = path.join(__dirname, '..', '.venv', 'Scripts', 'python.exe');
            pythonCmd = process.platform === 'win32' ? venvPath : 'python3';
            uvicornArgs = [
                '-m', 'uvicorn',
                'backend.app.app:app',
                '--host', '127.0.0.1',
                '--port', String(LOCAL_PORT),
                '--reload'
            ];
        } else {
            pythonCmd = process.platform === 'win32' ? 'python' : 'python3';
            uvicornArgs = [
                '-m', 'uvicorn',
                'backend.app.app:app',
                '--host', '127.0.0.1',
                '--port', String(LOCAL_PORT)
            ];
        }

        log('Starting backend server...');
        log(`Using Python: ${pythonCmd}`);

        // Quote the python path for Windows to handle spaces in directory names
        const spawnCmd = process.platform === 'win32' ? `"${pythonCmd}"` : pythonCmd;

        backendProcess = spawn(spawnCmd, uvicornArgs, {
            cwd: path.join(__dirname, '..'),
            stdio: ['pipe', 'pipe', 'pipe'],
            windowsHide: true,
            shell: true
        });

        backendProcess.stdout.on('data', (data) => {
            const output = data.toString();
            logBackend(output);
            if (output.includes('Application startup complete') || output.includes('Uvicorn running')) {
                resolve();
            }
        });

        backendProcess.stderr.on('data', (data) => {
            const output = data.toString();
            logBackend(output);
            if (output.includes('Application startup complete') || output.includes('Uvicorn running')) {
                resolve();
            }
        });

        backendProcess.on('error', (error) => {
            log(`Failed to start backend: ${error}`, 'ERROR');
            reject(error);
        });

        backendProcess.on('close', (code) => {
            log(`Backend process exited with code ${code}`, code === 0 ? 'INFO' : 'WARN');
        });

        setTimeout(resolve, 4000);
    });
}

function waitForBackend(maxRetries = 30, delay = 500) {
    return new Promise((resolve, reject) => {
        let retries = 0;
        // Use https module for HTTPS URLs, http for HTTP
        const httpModule = APP_URL.startsWith('https') ? https : http;

        const checkServer = () => {
            log(`Checking backend... attempt ${retries + 1}/${maxRetries}`);

            const req = httpModule.get(APP_URL + '/health', (res) => {
                if (res.statusCode === 200) {
                    log('Backend server is ready!');
                    resolve();
                } else {
                    retry();
                }
            });

            req.on('error', (err) => {
                log(`Connection error: ${err.message}`);
                retry();
            });
            req.setTimeout(5000, () => {
                req.destroy();
                retry();
            });
        };

        const retry = () => {
            retries++;
            if (retries >= maxRetries) {
                reject(new Error(USE_REMOTE_SERVER ? 'Failed to connect to remote server' : 'Backend server failed to start'));
            } else {
                setTimeout(checkServer, delay);
            }
        };

        checkServer();
    });
}

function stopBackend() {
    if (backendProcess) {
        log('Stopping backend server...');
        if (process.platform === 'win32') {
            spawn('taskkill', ['/pid', String(backendProcess.pid), '/f', '/t'], { shell: true });
        } else {
            backendProcess.kill('SIGTERM');
        }
        backendProcess = null;
    }
}

// ========== App Lifecycle ==========

app.whenReady().then(async () => {
    log('ETTA-X is starting...');
    log(`Mode: ${isDev ? 'Development' : 'Production'}`);
    log(`Force Setup: ${forceSetup}`);
    log(`Backend URL: ${APP_URL}`);

    // Clear session if force setup - do this BEFORE backend starts
    if (forceSetup) {
        const ses = session.defaultSession;
        // Clear ALL session data
        await ses.clearStorageData({
            storages: ['cookies', 'localstorage', 'sessionstorage', 'cachestorage', 'indexdb', 'serviceworkers']
        });
        await ses.clearCache();
        await ses.clearAuthCache();
        log('Cleared all session data for fresh setup');
    }

    // Start backend only if using local server (not remote)
    if (!USE_REMOTE_SERVER) {
        try {
            await startBackend();
        } catch (error) {
            log(`Failed to start backend: ${error}`, 'ERROR');
        }
    } else {
        log('Using remote server - skipping local backend startup');
    }

    try {
        await waitForBackend(USE_REMOTE_SERVER ? 10 : 30, 1000);

        // If force setup, also call logout API to clear any server-side session
        if (forceSetup) {
            try {
                http.get(`${APP_URL}/auth/github/logout`, (res) => {
                    log('Called logout API for fresh setup');
                }).on('error', () => { });
            } catch (e) {
                // Ignore logout errors
            }
        }

        createWindow();
    } catch (error) {
        log(`Backend not responding: ${error}`, 'ERROR');
        const { dialog } = require('electron');
        const errorDetail = USE_REMOTE_SERVER 
            ? `Unable to connect to the server at ${APP_URL}. Please check your internet connection and try again.`
            : 'The backend server failed to start. Please check that Python and dependencies are installed correctly.';
        
        const response = dialog.showMessageBoxSync({
            type: 'error',
            title: 'Connection Error',
            message: USE_REMOTE_SERVER ? 'Failed to connect to server.' : 'Failed to connect to backend server.',
            detail: errorDetail,
            buttons: ['Retry', 'Quit'],
            defaultId: 0
        });

        if (response === 0) {
            app.relaunch();
            app.exit();
        } else {
            app.quit();
        }
    }

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            createWindow();
        }
    });
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        stopBackend();
        app.quit();
    }
});

app.on('before-quit', () => stopBackend());
process.on('exit', () => stopBackend());
process.on('SIGINT', () => { stopBackend(); process.exit(); });
process.on('SIGTERM', () => { stopBackend(); process.exit(); });
