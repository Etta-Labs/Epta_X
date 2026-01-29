// Load configuration from JSON
async function loadConfig() {
    try {
        const response = await fetch('/config/app-config.json');
        const config = await response.json();
        return config;
    } catch (error) {
        console.error('Error loading config:', error);
        return null;
    }
}

// Apply theme based on config and localStorage
async function initializeLoadingScreen() {
    const config = await loadConfig();
    const loadingLogo = document.getElementById('loading-logo');
    const versionText = document.getElementById('version-text');
    
    // Check saved theme preference
    const savedTheme = localStorage.getItem('theme');
    
    if (savedTheme === 'dark') {
        document.body.classList.add('dark-theme');
        // Use dark theme logo
        if (config && config.theme.dark.loadingScreen.logo) {
            loadingLogo.src = config.theme.dark.loadingScreen.logo;
        } else {
            loadingLogo.src = '/static/assets/logo_bg.png';
        }
    } else {
        // Use light theme logo (default)
        if (config && config.theme.loadingScreen.logo) {
            loadingLogo.src = config.theme.loadingScreen.logo;
        } else {
            loadingLogo.src = '/static/assets/logo_bg_bl.png';
        }
    }
    
    // Set version text
    if (config && config.app.version) {
        versionText.textContent = 'v' + config.app.version;
    }
    
    // Get loading duration from config or use default
    const loadingDuration = config?.app?.loadingDuration || 3000;
    
    // Redirect to main dashboard after loading
    setTimeout(() => {
        window.location.href = '/dashboard';
    }, loadingDuration + 500);
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', initializeLoadingScreen);
