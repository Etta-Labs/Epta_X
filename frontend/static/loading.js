// Get API base URL from config (set by api-config.js)
function getApiUrl(endpoint) {
    return window.ETTA_API ? `${window.ETTA_API.baseUrl}${endpoint}` : endpoint;
}

// Load configuration from JSON (local file, not API)
async function loadConfig() {
    try {
        const response = await fetch('../config/app-config.json');
        const config = await response.json();
        return config;
    } catch (error) {
        console.error('Error loading config:', error);
        return null;
    }
}

// Check if this is a fresh app start (not just navigation)
function isAppStartup() {
    // Check if we came from another page in the app (session exists)
    const hasSession = sessionStorage.getItem('ettax_session_started');
    if (hasSession) {
        return false; // Not a fresh start, skip loading
    }
    // Mark session as started
    sessionStorage.setItem('ettax_session_started', 'true');
    return true;
}

// Check if setup is needed (like real app first-run check)
async function checkSetupStatus() {
    try {
        // Check backend setup status
        const setupResponse = await fetch(getApiUrl('/api/setup/status'), { credentials: 'include' });
        const setupData = await setupResponse.json();
        
        // If first run or no users, needs setup
        if (setupData.is_first_run || !setupData.has_users) {
            return { needsSetup: true, reason: 'first_run' };
        }
        
        // Check if user is authenticated
        const authResponse = await fetch(getApiUrl('/auth/github/status'), { credentials: 'include' });
        const authData = await authResponse.json();
        
        if (!authData.authenticated) {
            // Not authenticated, check if local setup was done
            const localSetup = localStorage.getItem('setupComplete');
            if (!localSetup) {
                // Never set up on this device, go to setup
                return { needsSetup: true, reason: 'not_authenticated' };
            }
            // Was set up before but not logged in, still go to setup for login
            return { needsSetup: true, reason: 'session_expired' };
        }
        
        // Check if user exists in database
        const userCheckResponse = await fetch(getApiUrl('/api/setup/check-user'), { credentials: 'include' });
        const userCheckData = await userCheckResponse.json();
        
        if (!userCheckData.exists) {
            // User authenticated but not in database, needs setup
            return { needsSetup: true, reason: 'user_not_registered' };
        }
        
        // User is authenticated and exists - go to dashboard
        return { needsSetup: false };
    } catch (error) {
        console.error('Error checking setup status:', error);
        // On error, check localStorage as fallback
        const localSetup = localStorage.getItem('setupComplete');
        if (!localSetup) {
            return { needsSetup: true, reason: 'error_fallback' };
        }
        // Try dashboard, it will handle auth errors
        return { needsSetup: false };
    }
}

// Apply theme based on config and localStorage
async function initializeLoadingScreen() {
    // Check if this is a fresh app startup or just navigation
    const isFreshStart = isAppStartup();
    
    // Quick check for authenticated users who just navigated here
    if (!isFreshStart) {
        try {
            const authResponse = await fetch(getApiUrl('/auth/github/status'), { credentials: 'include' });
            const authData = await authResponse.json();
            
            if (authData.authenticated) {
                // User is authenticated and this isn't startup - skip loading
                window.location.replace('/pages/index.html');
                return;
            }
        } catch (e) {
            // Continue with normal flow on error
        }
    }
    
    const config = await loadConfig();
    const loadingLogo = document.getElementById('loading-logo');
    const versionText = document.getElementById('version-text');
    const loadingText = document.querySelector('.loading-text');
    
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
    
    // Get loading duration from config or use default (shorter for non-startup)
    const loadingDuration = isFreshStart ? (config?.app?.loadingDuration || 3000) : 500;
    
    // Check setup status
    const setupStatus = await checkSetupStatus();
    
    // Update loading text based on destination
    if (loadingText) {
        if (setupStatus.needsSetup) {
            loadingText.textContent = 'Preparing setup...';
        } else {
            loadingText.textContent = 'Loading ETTA-X...';
        }
    }
    
    // Redirect after loading animation (use relative paths for Electron local files)
    setTimeout(() => {
        if (setupStatus.needsSetup) {
            window.location.href = 'setup.html';
        } else {
            window.location.href = 'index.html';
        }
    }, loadingDuration);
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', initializeLoadingScreen);
