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
