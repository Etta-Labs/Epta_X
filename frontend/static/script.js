// App Configuration
let appConfig = null;
let isLoggedIn = false;
let lastUserData = null;



// Login Modal Functions
function showLoginModal() {
    const modal = document.getElementById('login-modal');
    if (modal) {
        modal.classList.add('active');

        // Check if there's a previous account stored
        const prevUsername = localStorage.getItem('lastUsername');
        const prevAvatar = localStorage.getItem('lastAvatar');
        const prevName = localStorage.getItem('lastName');

        if (prevUsername) {
            const section = document.getElementById('previous-account-section');
            const avatarEl = document.getElementById('prev-account-avatar');
            const nameEl = document.getElementById('prev-account-name');
            const usernameEl = document.getElementById('prev-account-username');

            if (section) section.style.display = 'block';
            if (avatarEl && prevAvatar) avatarEl.src = prevAvatar;
            if (nameEl) nameEl.textContent = prevName || prevUsername;
            if (usernameEl) usernameEl.textContent = '@' + prevUsername;
        }
    }
}

function closeLoginModal() {
    const modal = document.getElementById('login-modal');
    if (modal) {
        modal.classList.remove('active');
    }
}

// OAuth state tracking
let dashboardOAuthCompleted = false;
let dashboardOAuthTimeout = null;
const originalModalContent = null;

function loginWithGitHub() {
    dashboardOAuthCompleted = false;

    // Check if running in Electron
    if (window.electronAPI && window.electronAPI.openOAuth) {
        // Get the OAuth URL from the server and open in external browser
        fetch('/auth/github/login-url')
            .then(response => response.json())
            .then(data => {
                if (data.url) {
                    window.electronAPI.openOAuth(data.url);
                    // Update modal to show waiting state
                    const modal = document.getElementById('login-modal');
                    if (modal) {
                        const modalContent = modal.querySelector('.login-modal');
                        if (modalContent) {
                            modalContent.innerHTML = `
                                <img src="/static/assets/logo_bg_bl.png" alt="ETTA-X" class="login-modal-logo">
                                <h2>Complete Sign In</h2>
                                <p>Please complete the sign in on your browser.<br>This window will update automatically.</p>
                                <div style="margin: 24px 0;">
                                    <div style="width: 40px; height: 40px; border: 3px solid #e5e7eb; border-top-color: #3B82F6; border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto;"></div>
                                </div>
                                <button onclick="cancelOAuth()" style="padding: 10px 24px; background: transparent; border: 1px solid #e5e7eb; border-radius: 8px; cursor: pointer; color: inherit;">Cancel</button>
                                <style>@keyframes spin { to { transform: rotate(360deg); } }</style>
                            `;
                        }
                    }

                    // Set timeout to cancel after 2 minutes
                    dashboardOAuthTimeout = setTimeout(() => {
                        if (!dashboardOAuthCompleted) {
                            cancelOAuth();
                        }
                    }, 120000);

                } else {
                    console.error('Failed to get OAuth URL');
                }
            })
            .catch(error => {
                console.error('Error getting OAuth URL:', error);
            });
    } else {
        // Fallback for web browser
        window.location.href = '/auth/github/login';
    }
}

function loginWithPreviousAccount() {
    loginWithGitHub();
}

async function loginWithDifferentAccount() {
    // Clear stored account info
    localStorage.removeItem('lastUsername');
    localStorage.removeItem('lastAvatar');
    localStorage.removeItem('lastName');

    // Close the modal first
    closeLoginModal();

    // First logout to clear server-side cookies
    try {
        await fetch('/auth/github/logout', {
            method: 'GET',
            credentials: 'include'
        });
    } catch (e) {
        // Continue even if logout fails
    }

    // Check if running in Electron
    if (window.electronAPI && window.electronAPI.openOAuth) {
        dashboardOAuthCompleted = false;
        // Get the OAuth URL with force_login flag
        fetch('/auth/github/login-url?force_login=true')
            .then(response => response.json())
            .then(data => {
                if (data.url) {
                    window.electronAPI.openOAuth(data.url);
                    showLoginModal();
                    // Update modal to show waiting state
                    const modal = document.getElementById('login-modal');
                    if (modal) {
                        const modalContent = modal.querySelector('.login-modal');
                        if (modalContent) {
                            modalContent.innerHTML = `
                                <img src="/static/assets/logo_bg_bl.png" alt="ETTA-X" class="login-modal-logo">
                                <h2>Complete Sign In</h2>
                                <p>Please complete the sign in on your browser.<br>This window will update automatically.</p>
                                <div style="margin: 24px 0;">
                                    <div style="width: 40px; height: 40px; border: 3px solid #e5e7eb; border-top-color: #3B82F6; border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto;"></div>
                                </div>
                                <button onclick="cancelOAuth()" style="padding: 10px 24px; background: transparent; border: 1px solid #e5e7eb; border-radius: 8px; cursor: pointer; color: inherit;">Cancel</button>
                                <style>@keyframes spin { to { transform: rotate(360deg); } }</style>
                            `;
                        }
                    }

                    // Set timeout
                    dashboardOAuthTimeout = setTimeout(() => {
                        if (!dashboardOAuthCompleted) {
                            cancelOAuth();
                        }
                    }, 120000);
                }
            })
            .catch(error => {
                console.error('Error getting OAuth URL:', error);
            });
    } else {
        // Fallback for web browser
        window.location.href = '/auth/github/login?force_login=true';
    }
}

function cancelOAuth() {
    dashboardOAuthCompleted = true;
    if (dashboardOAuthTimeout) {
        clearTimeout(dashboardOAuthTimeout);
        dashboardOAuthTimeout = null;
    }
    closeLoginModal();
    // Re-init modal for next time
    setTimeout(() => {
        initLoginModal();
    }, 100);
}

// Detect window focus to check if OAuth was cancelled
window.addEventListener('focus', () => {
    setTimeout(() => {
        const modal = document.getElementById('login-modal');
        if (modal && modal.classList.contains('active') && !dashboardOAuthCompleted) {
            const modalContent = modal.querySelector('.login-modal');
            if (modalContent && modalContent.innerHTML.includes('Complete Sign In')) {
                // User came back, give time for callback
                setTimeout(() => {
                    if (!dashboardOAuthCompleted) {
                        // No callback received, likely cancelled
                        cancelOAuth();
                    }
                }, 2000);
            }
        }
    }, 500);
});

// Listen for OAuth callback from Electron (via custom protocol)
if (window.electronAPI && window.electronAPI.onOAuthCallback) {
    window.electronAPI.onOAuthCallback(async (data) => {
        console.log('Received OAuth callback:', data);
        dashboardOAuthCompleted = true;
        if (dashboardOAuthTimeout) clearTimeout(dashboardOAuthTimeout);

        try {
            // Set the token via API
            const response = await fetch('/auth/set-token', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ token: data.token }),
                credentials: 'include'
            });

            if (response.ok) {
                // Token set successfully, reload to apply auth
                closeLoginModal();
                window.location.reload();
            } else {
                console.error('Failed to set token');
                alert('Authentication failed. Please try again.');
                closeLoginModal();
            }
        } catch (error) {
            console.error('Error setting token:', error);
            alert('Authentication failed. Please try again.');
            closeLoginModal();
        }
    });
}

// Route Protection - Check if action requires login
function requireLogin(callback) {
    if (!isLoggedIn) {
        showLoginModal();
        return false;
    }
    if (callback) callback();
    return true;
}

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

// Load user profile from API
async function loadUserProfile() {
    try {
        const response = await fetch('/auth/github/status');
        const data = await response.json();

        // Get settings logout item to show/hide based on auth state
        const settingsLogoutItem = document.getElementById('settings-logout-item');

        if (data.authenticated && data.username) {
            isLoggedIn = true;

            // Show logged-in view, hide logged-out view
            const loggedInView = document.getElementById('logged-in-view');
            const loggedOutView = document.getElementById('logged-out-view');
            if (loggedInView) loggedInView.style.display = 'block';
            if (loggedOutView) loggedOutView.style.display = 'none';

            // Show logout in settings menu when logged in
            if (settingsLogoutItem) settingsLogoutItem.style.display = 'flex';

            // Store for future login modal
            localStorage.setItem('lastUsername', data.username);

            // Update profile elements
            const profileName = document.getElementById('profile-name');
            const profileUsername = document.getElementById('profile-username');
            const profileAvatar = document.getElementById('profile-avatar');
            const profileIcon = document.getElementById('profile-toggle');

            if (profileName) profileName.textContent = data.username;
            if (profileUsername) profileUsername.textContent = '@' + data.username;

            // Try to get full user info for avatar
            try {
                const userResponse = await fetch('/auth/github/user');
                if (userResponse.ok) {
                    const userData = await userResponse.json();
                    lastUserData = userData;

                    if (userData.avatar_url) {
                        if (profileAvatar) profileAvatar.src = userData.avatar_url;
                        if (profileIcon) profileIcon.src = userData.avatar_url;
                        localStorage.setItem('lastAvatar', userData.avatar_url);
                    }
                    if (userData.name) {
                        if (profileName) profileName.textContent = userData.name;
                        localStorage.setItem('lastName', userData.name);
                    }
                }
            } catch (e) {
                console.log('Could not load full user data');
            }
        } else {
            isLoggedIn = false;
            // Hide logout in settings menu when logged out
            if (settingsLogoutItem) settingsLogoutItem.style.display = 'none';
        }
    } catch (error) {
        console.error('Error loading user profile:', error);
        isLoggedIn = false;
    }
}

// Profile Dropdown Toggle
const profileToggle = document.getElementById('profile-toggle');
const profileDropdown = document.getElementById('profile-dropdown');

if (profileToggle && profileDropdown) {
    profileToggle.addEventListener('click', function (e) {
        e.stopPropagation();

        // Toggle dropdown for both logged-in and logged-out users
        const isOpen = profileDropdown.style.display === 'block';
        profileDropdown.style.display = isOpen ? 'none' : 'block';
        profileDropdown.classList.toggle('open', !isOpen);
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', function (e) {
        if (!profileDropdown.contains(e.target) && e.target !== profileToggle) {
            profileDropdown.style.display = 'none';
            profileDropdown.classList.remove('open');
        }
    });
}

// Close login modal when clicking outside
document.addEventListener('click', function (e) {
    const modal = document.getElementById('login-modal');
    const modalContent = document.querySelector('.login-modal');
    if (modal && modal.classList.contains('active')) {
        if (!modalContent.contains(e.target)) {
            closeLoginModal();
        }
    }
});

// Settings Dropdown Toggle
const settingsToggle = document.getElementById('settings-toggle');
const settingsDropdown = document.querySelector('.menu-item-dropdown');

if (settingsToggle) {
    settingsToggle.addEventListener('click', function (e) {
        e.preventDefault();
        if (settingsDropdown) {
            settingsDropdown.classList.toggle('open');
        }
    });
}

// Protect menu items - require login
document.querySelectorAll('.menu-item').forEach(item => {
    // Skip settings toggle as it has its own handler
    if (item.id === 'settings-toggle') return;

    item.addEventListener('click', function (e) {
        if (!isLoggedIn) {
            e.preventDefault();
            showLoginModal();
        }
    });
});

// Theme Toggle
const themeToggle = document.getElementById('theme-toggle');
const logoImg = document.getElementById('logo-img');

function updateLogo() {
    if (document.body.classList.contains('dark-theme')) {
        if (logoImg) logoImg.src = '/static/assets/logo_bg.png';
    } else {
        if (logoImg) logoImg.src = '/static/assets/logo_bg_bl.png';
    }
}

// Sync theme with Electron (if running in desktop app)
function syncThemeWithElectron(theme) {
    if (window.electronAPI && window.electronAPI.syncTheme) {
        window.electronAPI.syncTheme(theme);
    }
}

// Apply theme function
function applyTheme(theme) {
    if (theme === 'dark') {
        document.body.classList.add('dark-theme');
    } else {
        document.body.classList.remove('dark-theme');
    }
    updateLogo();
    localStorage.setItem('theme', theme);
    syncThemeWithElectron(theme);

    if (appConfig) {
        appConfig.theme = appConfig.theme || {};
        appConfig.theme.mode = theme;
    }
}

if (themeToggle) {
    themeToggle.addEventListener('click', function (e) {
        e.preventDefault();
        const currentTheme = document.body.classList.contains('dark-theme') ? 'light' : 'dark';
        applyTheme(currentTheme);
    });
}

// Listen for theme changes from Electron menu
if (window.electronAPI && window.electronAPI.onThemeChanged) {
    window.electronAPI.onThemeChanged((theme) => {
        applyTheme(theme);
    });
}

// Load saved theme on page load
document.addEventListener('DOMContentLoaded', async function () {
    // Load app configuration
    await loadAppConfig();

    // Load user profile
    await loadUserProfile();

    // Apply saved theme
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        document.body.classList.add('dark-theme');
    }
    updateLogo();

    // Dropdown login button - connect to GitHub auth
    const dropdownLoginBtn = document.getElementById('dropdown-login-btn');
    if (dropdownLoginBtn) {
        dropdownLoginBtn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();

            // Close the dropdown
            const dropdown = document.getElementById('profile-dropdown');
            if (dropdown) {
                dropdown.style.display = 'none';
                dropdown.classList.remove('open');
            }

            // Show login modal immediately
            showLoginModal();
        });
    }

    // GitHub Repository & Branch Functions
    const repoSelect = document.getElementById('repo-select');
    const branchSelect = document.getElementById('branch-select');
    const cloneBtn = document.getElementById('clone-btn');

    // Fetch user repositories from GitHub
    async function loadUserRepositories() {
        if (!isLoggedIn) {
            // Clear dropdowns when not logged in
            if (repoSelect) {
                repoSelect.innerHTML = '<option value="" disabled selected>Sign in to view repos</option>';
                repoSelect.disabled = true;
            }
            if (branchSelect) {
                branchSelect.innerHTML = '<option value="" disabled selected>Select Branch</option>';
                branchSelect.disabled = true;
            }
            return;
        }

        try {
            const response = await fetch('/api/github/repos', {
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error('Failed to fetch repositories');
            }

            const data = await response.json();
            const repos = data.repos || [];

            if (repoSelect) {
                repoSelect.innerHTML = '<option value="" disabled selected>Select Repository</option>';
                repoSelect.disabled = false;

                repos.forEach(repo => {
                    const option = document.createElement('option');
                    option.value = repo.full_name;
                    option.textContent = repo.full_name;
                    option.dataset.defaultBranch = repo.default_branch;
                    repoSelect.appendChild(option);
                });

                // Restore saved selection if available
                const savedRepo = localStorage.getItem('selectedRepo');
                if (savedRepo && repoSelect.querySelector(`option[value="${savedRepo}"]`)) {
                    repoSelect.value = savedRepo;
                    // Load branches for saved repo
                    await loadRepoBranches(savedRepo);
                }
            }
        } catch (error) {
            console.error('Error loading repositories:', error);
            if (repoSelect) {
                repoSelect.innerHTML = '<option value="" disabled selected>Error loading repos</option>';
            }
        }
    }

    // Fetch branches for a specific repository
    async function loadRepoBranches(fullRepoName) {
        if (!fullRepoName || !branchSelect) return;

        const [owner, repo] = fullRepoName.split('/');

        try {
            branchSelect.innerHTML = '<option value="" disabled selected>Loading...</option>';
            branchSelect.disabled = true;

            const response = await fetch(`/api/github/repos/${owner}/${repo}/branches`, {
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error('Failed to fetch branches');
            }

            const data = await response.json();
            const branches = data.branches || [];

            branchSelect.innerHTML = '<option value="" disabled selected>Select Branch</option>';
            branchSelect.disabled = false;

            // Get the default branch for this repo
            const selectedOption = repoSelect?.querySelector(`option[value="${fullRepoName}"]`);
            const defaultBranch = selectedOption?.dataset.defaultBranch || 'main';

            branches.forEach(branch => {
                const option = document.createElement('option');
                option.value = branch.name;
                option.textContent = branch.name + (branch.protected ? ' 🔒' : '');
                branchSelect.appendChild(option);
            });

            // Try to select the default branch or saved branch
            const savedBranch = localStorage.getItem('selectedBranch');
            if (savedBranch && branchSelect.querySelector(`option[value="${savedBranch}"]`)) {
                branchSelect.value = savedBranch;
            } else if (branchSelect.querySelector(`option[value="${defaultBranch}"]`)) {
                branchSelect.value = defaultBranch;
            }

            updateCloneButton();
        } catch (error) {
            console.error('Error loading branches:', error);
            branchSelect.innerHTML = '<option value="" disabled selected>Error loading branches</option>';
            branchSelect.disabled = true;
        }
    }

    // Enable/disable clone button based on selections
    function updateCloneButton() {
        if (repoSelect && branchSelect && cloneBtn) {
            const hasRepo = repoSelect.value !== '';
            const hasBranch = branchSelect.value !== '';
            cloneBtn.disabled = !(hasRepo && hasBranch);
        }
    }

    // Repository selection change handler
    if (repoSelect) {
        repoSelect.addEventListener('change', async function () {
            const selectedRepo = this.value;
            localStorage.setItem('selectedRepo', selectedRepo);

            // Clear and load branches for the selected repo
            if (branchSelect) {
                branchSelect.innerHTML = '<option value="" disabled selected>Loading...</option>';
                branchSelect.disabled = true;
            }

            await loadRepoBranches(selectedRepo);
        });
    }

    // Branch selection change handler
    if (branchSelect) {
        branchSelect.addEventListener('change', function () {
            localStorage.setItem('selectedBranch', this.value);
            updateCloneButton();
        });
    }

    // Clone button click handler
    if (cloneBtn) {
        cloneBtn.addEventListener('click', function () {
            if (!requireLogin()) return;

            const repo = repoSelect?.value;
            const branch = branchSelect?.value;

            if (repo && branch) {
                showCloneModal(repo, branch);
            }
        });
    }

    // Load repositories if user is logged in
    if (isLoggedIn) {
        loadUserRepositories();
    } else {
        // Disable selectors when not logged in
        if (repoSelect) {
            repoSelect.innerHTML = '<option value="" disabled selected>Sign in to view repos</option>';
            repoSelect.disabled = true;
        }
        if (branchSelect) {
            branchSelect.innerHTML = '<option value="" disabled selected>Select Branch</option>';
            branchSelect.disabled = true;
        }
    }

    // Initialize button state
    updateCloneButton();
});

// Clone Modal Functions
function showCloneModal(repo, branch) {
    const modal = document.getElementById('clone-modal');
    const repoText = document.getElementById('clone-repo-text');
    const branchText = document.getElementById('clone-branch-text');

    if (modal && repoText && branchText) {
        repoText.textContent = repo;
        branchText.textContent = branch;
        modal.classList.add('active');
    }
}

function closeCloneModal() {
    const modal = document.getElementById('clone-modal');
    if (modal) {
        modal.classList.remove('active');
    }
}

function confirmClone() {
    const repoSelect = document.getElementById('repo-select');
    const branchSelect = document.getElementById('branch-select');

    if (repoSelect && branchSelect) {
        const repo = repoSelect.value;
        const branch = branchSelect.value;

        // Save selections to localStorage
        localStorage.setItem('selectedRepo', repo);
        localStorage.setItem('selectedBranch', branch);

        console.log(`Cloning repository: ${repo} from branch: ${branch}`);

        // TODO: Add actual clone API call here
        // Example:
        // fetch('/api/clone', {
        //     method: 'POST',
        //     headers: { 'Content-Type': 'application/json' },
        //     body: JSON.stringify({ repo, branch })
        // });

        closeCloneModal();

        // Show success notification (you can customize this)
        alert(`Successfully initiated clone of ${repo} from ${branch} branch!`);
    }
}

function cancelClone() {
    const repoSelect = document.getElementById('repo-select');
    const branchSelect = document.getElementById('branch-select');

    // Reset to default (blank)
    if (repoSelect) {
        repoSelect.value = '';
    }
    if (branchSelect) {
        branchSelect.value = '';
    }

    // Clear localStorage
    localStorage.removeItem('selectedRepo');
    localStorage.removeItem('selectedBranch');

    // Disable clone button
    const cloneBtn = document.getElementById('clone-btn');
    if (cloneBtn) {
        cloneBtn.disabled = true;
    }

    closeCloneModal();
}

// Close clone modal when clicking outside
document.addEventListener('click', function (e) {
    const modal = document.getElementById('clone-modal');
    const modalContent = document.querySelector('.clone-modal');
    if (modal && modal.classList.contains('active')) {
        if (!modalContent.contains(e.target)) {
            closeCloneModal();
        }
    }
});


// ============================================
// Clone Settings Functions
// ============================================

let currentCloneSettings = null;

async function loadCloneSettings() {
    try {
        const response = await fetch('/api/repos/settings', {
            credentials: 'include'
        });

        if (response.ok) {
            currentCloneSettings = await response.json();
            return currentCloneSettings;
        }
    } catch (error) {
        console.error('Failed to load clone settings:', error);
    }
    return null;
}


function closeCloneSettings() {
    const modal = document.getElementById('clone-settings-modal');
    if (modal) {
        modal.style.display = 'none';
        modal.classList.remove('active');
    }
}

async function populateCloneSettings() {
    const settings = await loadCloneSettings();
    if (!settings) {
        console.error('Could not load settings');
        return;
    }

    const pathInput = document.getElementById('clone-path-input');
    const defaultPathEl = document.getElementById('default-clone-path');
    const autoFetchToggle = document.getElementById('auto-fetch-toggle');
    const storeDiffsToggle = document.getElementById('store-diffs-toggle');
    const maxCommitsInput = document.getElementById('max-commits-input');

    if (pathInput) pathInput.value = settings.clone_base_path || '';
    if (defaultPathEl) defaultPathEl.textContent = settings.default_clone_path || 'Not set';
    if (autoFetchToggle) autoFetchToggle.checked = settings.auto_fetch_on_open !== false;
    if (storeDiffsToggle) storeDiffsToggle.checked = settings.store_diffs_in_db !== false;
    if (maxCommitsInput) maxCommitsInput.value = settings.max_commits_to_analyze || 100;
}

async function saveCloneSettings() {
    const pathInput = document.getElementById('clone-path-input');
    const autoFetchToggle = document.getElementById('auto-fetch-toggle');
    const storeDiffsToggle = document.getElementById('store-diffs-toggle');
    const maxCommitsInput = document.getElementById('max-commits-input');

    const newSettings = {
        clone_base_path: pathInput ? pathInput.value.trim() : null,
        auto_fetch_on_open: autoFetchToggle ? autoFetchToggle.checked : true,
        store_diffs_in_db: storeDiffsToggle ? storeDiffsToggle.checked : true,
        max_commits_to_analyze: maxCommitsInput ? parseInt(maxCommitsInput.value) || 100 : 100
    };

    try {
        const response = await fetch('/api/repos/settings', {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include',
            body: JSON.stringify(newSettings)
        });

        if (response.ok) {
            const result = await response.json();
            currentCloneSettings = result.settings;
            showNotification('Settings saved successfully!', 'success');
            closeCloneSettings();
        } else {
            showNotification('Failed to save settings', 'error');
        }
    } catch (error) {
        console.error('Failed to save settings:', error);
        showNotification('Failed to save settings', 'error');
    }
}

async function resetCloneSettings() {
    if (!currentCloneSettings) return;

    const pathInput = document.getElementById('clone-path-input');
    const autoFetchToggle = document.getElementById('auto-fetch-toggle');
    const storeDiffsToggle = document.getElementById('store-diffs-toggle');
    const maxCommitsInput = document.getElementById('max-commits-input');

    if (pathInput) pathInput.value = currentCloneSettings.default_clone_path || '';
    if (autoFetchToggle) autoFetchToggle.checked = true;
    if (storeDiffsToggle) storeDiffsToggle.checked = true;
    if (maxCommitsInput) maxCommitsInput.value = 100;

    showNotification('Settings reset to defaults', 'info');
}

function browseClonePath() {
    // In Electron, we can use the dialog API
    if (window.electronAPI && window.electronAPI.selectFolder) {
        window.electronAPI.selectFolder().then(path => {
            if (path) {
                const pathInput = document.getElementById('clone-path-input');
                if (pathInput) pathInput.value = path;
            }
        });
    } else {
        showNotification('Folder browser is only available in the desktop app', 'info');
    }
}

function openClonePath() {
    const pathInput = document.getElementById('clone-path-input');
    const path = pathInput ? pathInput.value.trim() : '';

    if (!path) {
        showNotification('No path specified', 'error');
        return;
    }

    if (window.electronAPI && window.electronAPI.openPath) {
        window.electronAPI.openPath(path);
    } else {
        // Copy path to clipboard as fallback
        navigator.clipboard.writeText(path).then(() => {
            showNotification('Path copied to clipboard: ' + path, 'info');
        });
    }
}


// ============================================
// Settings Tabs Functions
// ============================================

function switchSettingsTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.settings-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === tabName);
    });

    // Update tab content
    document.querySelectorAll('.settings-tab-content').forEach(content => {
        content.classList.toggle('active', content.id === `tab-${tabName}`);
    });

    // Load data for specific tabs
    if (tabName === 'webhooks') {
        loadSettingsWebhooks();
    } else if (tabName === 'application') {
        updateThemeSelector();
    }
}

async function loadSettingsWebhooks() {
    const listEl = document.getElementById('settings-webhooks-list');
    if (!listEl) return;

    listEl.innerHTML = `
        <div class="loading-repos">
            <div class="spinner"></div>
            <span>Loading webhooks...</span>
        </div>
    `;

    try {
        // Load webhook status
        const statusResponse = await fetch('/api/webhooks/status', {
            credentials: 'include'
        });

        if (statusResponse.ok) {
            const statusData = await statusResponse.json();
            const statusEl = document.getElementById('settings-webhook-service-status');
            const eventsEl = document.getElementById('settings-webhook-total-events');
            const activeEl = document.getElementById('settings-webhook-active-count');

            if (statusEl) {
                statusEl.textContent = statusData.status === 'active' ? 'Active' : 'Inactive';
                statusEl.className = 'status-value ' + (statusData.status === 'active' ? 'active' : '');
            }
            if (eventsEl) eventsEl.textContent = statusData.total_events_received || 0;
            if (activeEl) activeEl.textContent = statusData.active_webhooks || 0;
        }

        // Load repositories and webhooks
        const reposResponse = await fetch('/api/repos/cloned', {
            credentials: 'include'
        });

        const webhooksResponse = await fetch('/api/webhooks', {
            credentials: 'include'
        });

        if (reposResponse.ok && webhooksResponse.ok) {
            const reposData = await reposResponse.json();
            const webhooksData = await webhooksResponse.json();

            const repos = reposData.repositories || [];
            const webhooks = webhooksData.webhooks || [];

            // Create a map of repo_id to webhook
            const webhookMap = {};
            webhooks.forEach(w => {
                webhookMap[w.cloned_repo_id] = w;
            });

            renderSettingsWebhooks(repos, webhookMap, listEl);
        } else {
            listEl.innerHTML = `
                <div class="empty-webhooks">
                    <p>Unable to load webhooks. Please try again.</p>
                </div>
            `;
        }
    } catch (error) {
        console.error('Failed to load webhooks:', error);
        listEl.innerHTML = `
            <div class="empty-webhooks">
                <p>Failed to load webhooks</p>
            </div>
        `;
    }
}

function renderSettingsWebhooks(repos, webhookMap, listEl) {
    if (repos.length === 0) {
        listEl.innerHTML = `
            <div class="empty-webhooks">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="40" height="40">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                </svg>
                <p style="margin-top: 12px;">No cloned repositories</p>
                <p class="hint" style="color: #6B7280; font-size: 13px;">Clone a repository first to set up webhooks</p>
            </div>
        `;
        return;
    }

    listEl.innerHTML = repos.map(repo => {
        const webhook = webhookMap[repo.id];
        const hasWebhook = !!webhook;
        const isActive = webhook && webhook.is_active;

        return `
            <div class="webhook-card" data-repo-id="${repo.id}">
                <div class="webhook-card-info">
                    <div class="webhook-card-name">
                        ${repo.full_name}
                        ${hasWebhook ?
                `<span class="webhook-badge ${isActive ? 'active' : 'inactive'}">${isActive ? '✓ Active' : 'Inactive'}</span>` :
                '<span class="webhook-badge pending">Not Enabled</span>'
            }
                    </div>
                    <div class="webhook-card-path">${repo.local_path}</div>
                </div>
                <div class="webhook-card-actions">
                    ${hasWebhook ? `
                        <button class="webhook-action-btn" onclick="triggerManualPull(${repo.id}, '${repo.full_name}')" title="Pull now">
                            Pull
                        </button>
                        <button class="webhook-action-btn danger" onclick="deleteWebhook(${webhook.id}, '${repo.full_name}')" title="Remove">
                            Remove
                        </button>
                    ` : `
                        <button class="webhook-action-btn primary" onclick="registerWebhook(${repo.id}, '${repo.full_name}')">
                            Enable
                        </button>
                    `}
                </div>
            </div>
        `;
    }).join('');
}

// Theme Functions
function setTheme(theme) {
    localStorage.setItem('theme', theme);

    if (theme === 'system') {
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        document.body.classList.toggle('dark-theme', prefersDark);
    } else if (theme === 'dark') {
        document.body.classList.add('dark-theme');
    } else {
        document.body.classList.remove('dark-theme');
    }

    updateThemeSelector();
    updateLogoForTheme();
}

function updateThemeSelector() {
    const currentTheme = localStorage.getItem('theme') || 'system';

    document.querySelectorAll('.theme-option').forEach(option => {
        option.classList.toggle('active', option.dataset.theme === currentTheme);
    });
}

function updateLogoForTheme() {
    const isDark = document.body.classList.contains('dark-theme');
    const aboutLogo = document.getElementById('about-logo-img');

    if (aboutLogo) {
        aboutLogo.src = isDark ? '/static/assets/logo_bg_w.png' : '/static/assets/logo_bg_bl.png';
    }
}

// Save All Settings (for the comprehensive settings modal)
async function saveAllSettings() {
    // Save clone settings first
    await saveCloneSettings();
}

// Override openCloneSettings to load webhooks when Webhooks tab is active
const originalOpenCloneSettings = window.openCloneSettings || openCloneSettings;

function openCloneSettings() {
    console.log('Opening settings modal...');
    const modal = document.getElementById('clone-settings-modal');
    console.log('Modal element:', modal);
    if (modal) {
        // Use inline style to ensure it displays
        modal.style.display = 'flex';
        modal.classList.add('active');
        console.log('Modal opened with inline style');
        populateCloneSettings();
        updateThemeSelector();
    } else {
        console.error('Settings modal not found!');
    }
}

function closeCloneSettings() {
    const modal = document.getElementById('clone-settings-modal');
    if (modal) {
        modal.style.display = 'none';
        modal.classList.remove('active');
    }
}
// ============================================
// Cloned Repositories Modal Functions
// ============================================

function openClonedReposModal() {
    const modal = document.getElementById('cloned-repos-modal');
    if (modal) {
        modal.classList.add('active');
        loadClonedRepositories();
    }
}

function closeClonedReposModal() {
    const modal = document.getElementById('cloned-repos-modal');
    if (modal) {
        modal.classList.remove('active');
    }
}

async function loadClonedRepositories() {
    const listEl = document.getElementById('cloned-repos-list');
    if (!listEl) return;

    listEl.innerHTML = `
        <div class="loading-repos">
            <div class="spinner"></div>
            <span>Loading repositories...</span>
        </div>
    `;

    try {
        const response = await fetch('/api/repos/cloned', {
            credentials: 'include'
        });

        if (response.ok) {
            const data = await response.json();
            renderClonedRepos(data.repositories || []);
        } else if (response.status === 401) {
            listEl.innerHTML = `
                <div class="empty-repos">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10" />
                        <line x1="12" y1="8" x2="12" y2="12" />
                        <line x1="12" y1="16" x2="12.01" y2="16" />
                    </svg>
                    <p>Please sign in to view cloned repositories</p>
                </div>
            `;
        } else {
            throw new Error('Failed to load repositories');
        }
    } catch (error) {
        console.error('Failed to load cloned repos:', error);
        listEl.innerHTML = `
            <div class="empty-repos">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="15" y1="9" x2="9" y2="15" />
                    <line x1="9" y1="9" x2="15" y2="15" />
                </svg>
                <p>Failed to load repositories</p>
            </div>
        `;
    }
}

function renderClonedRepos(repos) {
    const listEl = document.getElementById('cloned-repos-list');
    if (!listEl) return;

    if (repos.length === 0) {
        listEl.innerHTML = `
            <div class="empty-repos">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                </svg>
                <p>No cloned repositories yet</p>
                <p style="font-size: 13px; color: #9ca3af;">Clone a repository using the dropdown in the header</p>
            </div>
        `;
        return;
    }

    listEl.innerHTML = repos.map(repo => `
        <div class="repo-card" data-repo-id="${repo.id}">
            <div class="repo-card-info">
                <div class="repo-card-name">${repo.full_name}</div>
                <div class="repo-card-path">${repo.local_path}</div>
                <div class="repo-card-status ${repo.clone_status}">
                    ${getStatusIcon(repo.clone_status)}
                    ${repo.clone_status === 'completed' ? 'Cloned' : repo.clone_status === 'pending' ? 'Pending' : 'Failed'}
                    ${repo.current_branch ? ` • ${repo.current_branch}` : ''}
                </div>
            </div>
            <div class="repo-card-actions">
                <button class="repo-action-btn" onclick="openRepoInExplorer(${repo.id}, '${repo.local_path.replace(/\\/g, '\\\\')}')" title="Open in Explorer">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                    </svg>
                </button>
                <button class="repo-action-btn delete" onclick="deleteClonedRepo(${repo.id}, '${repo.full_name}')" title="Delete">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6" />
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                </button>
            </div>
        </div>
    `).join('');
}

function getStatusIcon(status) {
    if (status === 'completed') {
        return '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12" /></svg>';
    } else if (status === 'pending') {
        return '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>';
    } else {
        return '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" /></svg>';
    }
}

function refreshClonedRepos() {
    loadClonedRepositories();
}

function openRepoInExplorer(repoId, path) {
    if (window.electronAPI && window.electronAPI.openPath) {
        window.electronAPI.openPath(path);
    } else {
        navigator.clipboard.writeText(path).then(() => {
            showNotification('Path copied to clipboard: ' + path, 'info');
        });
    }
}

async function deleteClonedRepo(repoId, repoName) {
    if (!confirm(`Are you sure you want to remove "${repoName}" from your cloned repositories?\n\nThis will only remove the record. Local files will remain.`)) {
        return;
    }

    try {
        const response = await fetch(`/api/repos/${repoId}?delete_files=false`, {
            method: 'DELETE',
            credentials: 'include'
        });

        if (response.ok) {
            showNotification('Repository removed', 'success');
            loadClonedRepositories();
        } else {
            showNotification('Failed to remove repository', 'error');
        }
    } catch (error) {
        console.error('Failed to delete repo:', error);
        showNotification('Failed to remove repository', 'error');
    }
}


// ============================================
// Notification Helper
// ============================================

function showNotification(message, type = 'info') {
    // Remove existing notification
    const existing = document.querySelector('.notification-toast');
    if (existing) existing.remove();

    const notification = document.createElement('div');
    notification.className = `notification-toast ${type}`;
    notification.innerHTML = `
        <span>${message}</span>
        <button onclick="this.parentElement.remove()">&times;</button>
    `;

    // Add styles if not already present
    if (!document.getElementById('notification-styles')) {
        const style = document.createElement('style');
        style.id = 'notification-styles';
        style.textContent = `
            .notification-toast {
                position: fixed;
                bottom: 24px;
                right: 24px;
                padding: 14px 20px;
                border-radius: 8px;
                background: #1f2937;
                color: #ffffff;
                font-size: 14px;
                display: flex;
                align-items: center;
                gap: 12px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
                z-index: 10002;
                animation: slideIn 0.3s ease;
            }
            .notification-toast.success { background: #065F46; }
            .notification-toast.error { background: #991B1B; }
            .notification-toast.info { background: #1E40AF; }
            .notification-toast button {
                background: none;
                border: none;
                color: inherit;
                font-size: 18px;
                cursor: pointer;
                opacity: 0.7;
            }
            .notification-toast button:hover { opacity: 1; }
            @keyframes slideIn {
                from { transform: translateY(20px); opacity: 0; }
                to { transform: translateY(0); opacity: 1; }
            }
        `;
        document.head.appendChild(style);
    }

    document.body.appendChild(notification);

    // Auto-remove after 4 seconds
    setTimeout(() => {
        if (notification.parentElement) {
            notification.remove();
        }
    }, 4000);
}


// ============================================
// Update Clone Modal to Show Path
// ============================================

async function updateCloneModalPath(repoFullName) {
    const pathDisplay = document.getElementById('clone-path-display');
    if (!pathDisplay) return;

    if (!currentCloneSettings) {
        await loadCloneSettings();
    }

    if (currentCloneSettings && repoFullName) {
        const basePath = currentCloneSettings.clone_base_path || currentCloneSettings.default_clone_path || '';
        const fullPath = basePath + '\\' + repoFullName.replace('/', '\\');
        pathDisplay.textContent = fullPath;
    } else {
        pathDisplay.textContent = 'Loading...';
    }
}

// Override showCloneModal to include path display
const originalShowCloneModal = typeof showCloneModal === 'function' ? showCloneModal : null;

function showCloneModal(repo, branch) {
    const modal = document.getElementById('clone-modal');
    const repoText = document.getElementById('clone-repo-text');
    const branchText = document.getElementById('clone-branch-text');

    if (modal && repoText && branchText) {
        repoText.textContent = repo;
        branchText.textContent = branch;
        modal.classList.add('active');

        // Update clone path display
        updateCloneModalPath(repo);
    }
}

// Close settings modals when clicking outside
document.addEventListener('click', function (e) {
    // Clone settings modal
    const cloneSettingsModal = document.getElementById('clone-settings-modal');
    const cloneSettingsContent = cloneSettingsModal ? cloneSettingsModal.querySelector('.settings-modal') : null;
    if (cloneSettingsModal && cloneSettingsModal.classList.contains('active')) {
        if (cloneSettingsContent && !cloneSettingsContent.contains(e.target)) {
            closeCloneSettings();
        }
    }

    // Cloned repos modal
    const clonedReposModal = document.getElementById('cloned-repos-modal');
    const clonedReposContent = clonedReposModal ? clonedReposModal.querySelector('.settings-modal') : null;
    if (clonedReposModal && clonedReposModal.classList.contains('active')) {
        if (clonedReposContent && !clonedReposContent.contains(e.target)) {
            closeClonedReposModal();
        }
    }

    // Webhooks modal
    const webhooksModal = document.getElementById('webhooks-modal');
    const webhooksContent = webhooksModal ? webhooksModal.querySelector('.settings-modal') : null;
    if (webhooksModal && webhooksModal.classList.contains('active')) {
        if (webhooksContent && !webhooksContent.contains(e.target)) {
            closeWebhooksModal();
        }
    }
});


// ============================================
// Webhooks Modal Functions
// ============================================

function openWebhooksModal() {
    const modal = document.getElementById('webhooks-modal');
    if (modal) {
        modal.classList.add('active');
        loadWebhooks();
        loadWebhookStatus();
    }
}

function closeWebhooksModal() {
    const modal = document.getElementById('webhooks-modal');
    if (modal) {
        modal.classList.remove('active');
    }
}

async function loadWebhookStatus() {
    try {
        const response = await fetch('/api/webhooks/status', {
            credentials: 'include'
        });

        if (response.ok) {
            const data = await response.json();
            const statusEl = document.getElementById('webhook-service-status');
            const eventsEl = document.getElementById('webhook-total-events');

            if (statusEl) {
                statusEl.textContent = data.status === 'active' ? 'Active' : 'Inactive';
                statusEl.className = 'status-value ' + (data.status === 'active' ? 'active' : '');
            }
            if (eventsEl) {
                eventsEl.textContent = data.total_events_received || 0;
            }
        }
    } catch (error) {
        console.error('Failed to load webhook status:', error);
    }
}

async function loadWebhooks() {
    const listEl = document.getElementById('webhooks-list');
    if (!listEl) return;

    listEl.innerHTML = `
        <div class="loading-repos">
            <div class="spinner"></div>
            <span>Loading webhooks...</span>
        </div>
    `;

    try {
        // First load cloned repos to show which can have webhooks
        const reposResponse = await fetch('/api/repos/cloned', {
            credentials: 'include'
        });

        const webhooksResponse = await fetch('/api/webhooks', {
            credentials: 'include'
        });

        if (reposResponse.ok && webhooksResponse.ok) {
            const reposData = await reposResponse.json();
            const webhooksData = await webhooksResponse.json();

            const repos = reposData.repositories || [];
            const webhooks = webhooksData.webhooks || [];

            // Create a map of repo_id to webhook
            const webhookMap = {};
            webhooks.forEach(w => {
                webhookMap[w.cloned_repo_id] = w;
            });

            renderWebhooks(repos, webhookMap);
        } else if (reposResponse.status === 401 || webhooksResponse.status === 401) {
            listEl.innerHTML = `
                <div class="empty-webhooks">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10" />
                        <line x1="12" y1="8" x2="12" y2="12" />
                        <line x1="12" y1="16" x2="12.01" y2="16" />
                    </svg>
                    <p>Please sign in to manage webhooks</p>
                </div>
            `;
        } else {
            throw new Error('Failed to load data');
        }
    } catch (error) {
        console.error('Failed to load webhooks:', error);
        listEl.innerHTML = `
            <div class="empty-webhooks">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="15" y1="9" x2="9" y2="15" />
                    <line x1="9" y1="9" x2="15" y2="15" />
                </svg>
                <p>Failed to load webhooks</p>
            </div>
        `;
    }
}

function renderWebhooks(repos, webhookMap) {
    const listEl = document.getElementById('webhooks-list');
    if (!listEl) return;

    if (repos.length === 0) {
        listEl.innerHTML = `
            <div class="empty-webhooks">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                </svg>
                <p>No cloned repositories</p>
                <p class="hint">Clone a repository first to set up webhooks</p>
            </div>
        `;
        return;
    }

    listEl.innerHTML = repos.map(repo => {
        const webhook = webhookMap[repo.id];
        const hasWebhook = !!webhook;
        const isActive = webhook && webhook.is_active;

        return `
            <div class="webhook-card" data-repo-id="${repo.id}">
                <div class="webhook-card-info">
                    <div class="webhook-card-name">
                        ${repo.full_name}
                        ${hasWebhook ?
                `<span class="webhook-badge ${isActive ? 'active' : 'inactive'}">${isActive ? '✓ Webhook Active' : 'Inactive'}</span>` :
                '<span class="webhook-badge pending">No Webhook</span>'
            }
                    </div>
                    <div class="webhook-card-path">${repo.local_path}</div>
                    ${hasWebhook ? `
                        <div class="webhook-card-stats">
                            <span class="webhook-card-stat">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                                </svg>
                                ${webhook.events_received || 0} events
                            </span>
                            ${webhook.last_event_at ? `
                                <span class="webhook-card-stat">
                                    Last: ${new Date(webhook.last_event_at).toLocaleDateString()}
                                </span>
                            ` : ''}
                        </div>
                    ` : ''}
                </div>
                <div class="webhook-card-actions">
                    ${hasWebhook ? `
                        <button class="webhook-action-btn" onclick="triggerManualPull(${repo.id}, '${repo.full_name}')" title="Pull latest changes">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                                <polyline points="7 10 12 15 17 10" />
                                <line x1="12" y1="15" x2="12" y2="3" />
                            </svg>
                            Pull Now
                        </button>
                        <button class="webhook-action-btn" onclick="showWebhookSetup(${repo.id}, '${repo.full_name}')" title="View webhook setup">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <circle cx="12" cy="12" r="3" />
                                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4" />
                            </svg>
                            Setup
                        </button>
                        <button class="webhook-action-btn danger" onclick="deleteWebhook(${webhook.id}, '${repo.full_name}')" title="Remove webhook">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="3 6 5 6 21 6" />
                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                            </svg>
                        </button>
                    ` : `
                        <button class="webhook-action-btn primary" onclick="registerWebhook(${repo.id}, '${repo.full_name}')">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <line x1="12" y1="5" x2="12" y2="19" />
                                <line x1="5" y1="12" x2="19" y2="12" />
                            </svg>
                            Enable Auto-Pull
                        </button>
                    `}
                </div>
            </div>
        `;
    }).join('');
}

function refreshWebhooks() {
    loadWebhooks();
    loadWebhookStatus();
}

async function registerWebhook(repoId, repoName) {
    try {
        showNotification(`Registering webhook for ${repoName}...`, 'info');

        const response = await fetch(`/api/webhooks/register/${repoId}`, {
            method: 'POST',
            credentials: 'include'
        });

        if (response.ok) {
            const data = await response.json();
            showWebhookSetupInstructions(data, repoName);
            loadWebhooks();
        } else {
            const error = await response.json();
            showNotification(error.detail || 'Failed to register webhook', 'error');
        }
    } catch (error) {
        console.error('Failed to register webhook:', error);
        showNotification('Failed to register webhook', 'error');
    }
}

function showWebhookSetupInstructions(data, repoName) {
    const instructions = data.instructions;

    const message = `
Webhook registered for ${repoName}!

To complete setup, add this webhook in GitHub:

1. Go to: ${instructions.step1.replace('Go to GitHub repository settings: ', '')}
2. Payload URL: ${data.webhook_url}
3. Content type: application/json
4. Secret: ${data.secret}
5. Select "Just the push event"
6. Click "Add webhook"

The secret has been copied to your clipboard.
    `.trim();

    // Copy secret to clipboard
    navigator.clipboard.writeText(data.secret).catch(() => { });

    alert(message);
    showNotification('Webhook secret copied to clipboard!', 'success');
}

async function showWebhookSetup(repoId, repoName) {
    try {
        const response = await fetch(`/api/webhooks/register/${repoId}`, {
            method: 'POST',
            credentials: 'include'
        });

        if (response.ok) {
            const data = await response.json();
            showWebhookSetupInstructions(data, repoName);
        }
    } catch (error) {
        console.error('Failed to get webhook setup:', error);
        showNotification('Failed to get webhook setup info', 'error');
    }
}

async function deleteWebhook(webhookId, repoName) {
    if (!confirm(`Remove webhook for "${repoName}"?\n\nNote: You'll also need to delete the webhook from GitHub settings.`)) {
        return;
    }

    try {
        const response = await fetch(`/api/webhooks/${webhookId}`, {
            method: 'DELETE',
            credentials: 'include'
        });

        if (response.ok) {
            showNotification('Webhook removed', 'success');
            loadWebhooks();
        } else {
            showNotification('Failed to remove webhook', 'error');
        }
    } catch (error) {
        console.error('Failed to delete webhook:', error);
        showNotification('Failed to remove webhook', 'error');
    }
}

async function triggerManualPull(repoId, repoName) {
    try {
        showNotification(`Pulling latest changes for ${repoName}...`, 'info');

        const response = await fetch(`/api/webhooks/${repoId}/pull`, {
            method: 'POST',
            credentials: 'include'
        });

        if (response.ok) {
            const data = await response.json();
            showNotification(`Pulling ${data.branch} branch...`, 'success');
        } else {
            const error = await response.json();
            showNotification(error.detail || 'Failed to trigger pull', 'error');
        }
    } catch (error) {
        console.error('Failed to trigger pull:', error);
        showNotification('Failed to trigger pull', 'error');
    }
}

// ============================================
// Dropdown Toggle Functions
// ============================================

function initializeDropdowns() {
    console.log('Initializing dropdowns...');

    // Settings dropdown toggle
    const settingsToggle = document.getElementById('settings-toggle');
    console.log('Settings toggle element:', settingsToggle);

    if (settingsToggle) {
        settingsToggle.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation(); // Prevent document click from immediately closing
            console.log('Settings toggle clicked');
            const dropdown = this.closest('.menu-item-dropdown');
            if (dropdown) {
                dropdown.classList.toggle('open');
                console.log('Dropdown toggled, open:', dropdown.classList.contains('open'));
            }
        });
    } else {
        console.error('Settings toggle not found!');
    }

    // Close dropdown when clicking outside
    document.addEventListener('click', function (e) {
        const dropdowns = document.querySelectorAll('.menu-item-dropdown.open');
        dropdowns.forEach(dropdown => {
            if (!dropdown.contains(e.target)) {
                dropdown.classList.remove('open');
            }
        });
    });

    console.log('Dropdowns initialized');
}


// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function () {
    initializeDropdowns();

    // Apply saved theme on load
    const savedTheme = localStorage.getItem('theme') || 'system';
    if (savedTheme === 'dark') {
        document.body.classList.add('dark-theme');
    } else if (savedTheme === 'system') {
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        document.body.classList.toggle('dark-theme', prefersDark);
    }
});
