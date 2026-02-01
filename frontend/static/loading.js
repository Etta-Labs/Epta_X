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

// Check if setup is needed (like real app first-run check)
async function checkSetupStatus() {
    try {
        // Check backend setup status
        const setupResponse = await fetch('/api/setup/status');
        const setupData = await setupResponse.json();
        
        // If first run or no users, needs setup
        if (setupData.is_first_run || !setupData.has_users) {
            return { needsSetup: true, reason: 'first_run' };
        }
        
        // Check if user is authenticated
        const authResponse = await fetch('/auth/github/status');
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
        const userCheckResponse = await fetch('/api/setup/check-user');
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
    
    // Get loading duration from config or use default
    const loadingDuration = config?.app?.loadingDuration || 3000;
    
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
    
    // Redirect after loading animation
    setTimeout(() => {
        if (setupStatus.needsSetup) {
            window.location.href = '/setup';
        } else {
            window.location.href = '/dashboard';
        }
    }, loadingDuration);
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', initializeLoadingScreen);
