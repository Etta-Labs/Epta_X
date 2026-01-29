// App Configuration
let appConfig = null;

// Load configuration from JSON
async function loadAppConfig() {
    try {
        const response = await fetch('/config/app-config.json');
        appConfig = await response.json();
        return appConfig;
    } catch (error) {
        console.error('Error loading config:', error);
        return null;
    }
}

// Settings Dropdown Toggle
const settingsToggle = document.getElementById('settings-toggle');
const settingsDropdown = document.querySelector('.menu-item-dropdown');

settingsToggle.addEventListener('click', function(e) {
    e.preventDefault();
    settingsDropdown.classList.toggle('open');
});

// Theme Toggle
const themeToggle = document.getElementById('theme-toggle');
const logoImg = document.getElementById('logo-img');

function updateLogo() {
    if (document.body.classList.contains('dark-theme')) {
        logoImg.src = '/static/assets/logo_bg.png';
    } else {
        logoImg.src = '/static/assets/logo_bg_bl.png';
    }
}

themeToggle.addEventListener('click', function(e) {
    e.preventDefault();
    document.body.classList.toggle('dark-theme');
    
    // Update logo
    updateLogo();
    
    // Save theme preference to localStorage
    const currentTheme = document.body.classList.contains('dark-theme') ? 'dark' : 'light';
    localStorage.setItem('theme', currentTheme);
    
    // Update config theme mode (for future backend integration)
    if (appConfig) {
        appConfig.theme.mode = currentTheme;
    }
});

// Load saved theme on page load
document.addEventListener('DOMContentLoaded', async function() {
    // Load app configuration
    await loadAppConfig();
    
    // Apply saved theme
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        document.body.classList.add('dark-theme');
    }
    updateLogo();
});
