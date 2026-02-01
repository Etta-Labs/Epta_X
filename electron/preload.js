const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods for renderer process
contextBridge.exposeInMainWorld('electronAPI', {
    // Window controls
    minimize: () => ipcRenderer.send('window-minimize'),
    maximize: () => ipcRenderer.send('window-maximize'),
    close: () => ipcRenderer.send('window-close'),

    // App actions
    reload: () => ipcRenderer.send('app-reload'),
    clearCache: () => ipcRenderer.send('app-clear-cache'),
    quit: () => ipcRenderer.send('app-quit'),

    // View actions
    zoomIn: () => ipcRenderer.send('view-zoom-in'),
    zoomOut: () => ipcRenderer.send('view-zoom-out'),
    resetZoom: () => ipcRenderer.send('view-reset-zoom'),
    toggleFullscreen: () => ipcRenderer.send('view-toggle-fullscreen'),
    toggleDevTools: () => ipcRenderer.send('view-toggle-devtools'),

    // Help
    showAbout: () => ipcRenderer.send('help-about'),

    // Theme sync
    getTheme: () => ipcRenderer.invoke('get-theme'),
    setTheme: (theme) => ipcRenderer.invoke('set-theme', theme),
    syncTheme: (theme) => ipcRenderer.send('sync-theme', theme),
    onThemeChanged: (callback) => {
        ipcRenderer.on('theme-changed', (event, theme) => callback(theme));
    },

    // OAuth - open in external browser and receive callback
    openOAuth: (url) => ipcRenderer.send('open-oauth', { url }),
    onOAuthCallback: (callback) => {
        ipcRenderer.on('oauth-callback', (event, data) => callback(data));
    },

    // Platform info
    platform: process.platform,
    isElectron: true
});
