// Impact Analysis Page JavaScript
// Automatic pipeline results from webhook triggers

// Global state
let isLoggedIn = false;
let lastUserData = null;
let selectedEventId = null;
let autoRefreshInterval = null;
let allResults = [];

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', async function() {
    // Apply saved theme
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        document.body.classList.add('dark-theme');
        updateLogo();
    }
    
    // Load user profile
    await loadUserProfile();
    
    // Initialize UI components
    initThemeToggle();
    initProfileDropdown();
    initSettingsDropdown();
    initFilterHandlers();
    initRefreshButton();
    
    // Load data if logged in
    if (isLoggedIn) {
        await loadRepositories();
        await loadPipelineResults();
        await loadPipelineStats();
        startAutoRefresh();
    } else {
        showEmptyState('Please sign in to view Impact Analysis results');
    }
});

// Load user profile
async function loadUserProfile() {
    try {
        const response = await fetch('/auth/github/status');
        const data = await response.json();
        
        const settingsLogoutItem = document.getElementById('settings-logout-item');
        
        if (data.authenticated && data.username) {
            isLoggedIn = true;
            
            const loggedInView = document.getElementById('logged-in-view');
            const loggedOutView = document.getElementById('logged-out-view');
            if (loggedInView) loggedInView.style.display = 'block';
            if (loggedOutView) loggedOutView.style.display = 'none';
            if (settingsLogoutItem) settingsLogoutItem.style.display = 'flex';
            
            localStorage.setItem('lastUsername', data.username);
            
            const profileName = document.getElementById('profile-name');
            const profileUsername = document.getElementById('profile-username');
            const profileAvatar = document.getElementById('profile-avatar');
            const profileIcon = document.getElementById('profile-toggle');
            
            if (profileName) profileName.textContent = data.username;
            if (profileUsername) profileUsername.textContent = '@' + data.username;
            
            try {
                const userResponse = await fetch('/auth/github/user');
                if (userResponse.ok) {
                    const userData = await userResponse.json();
                    lastUserData = userData;
                    
                    if (userData.avatar_url) {
                        if (profileAvatar) profileAvatar.src = userData.avatar_url;
                        if (profileIcon) profileIcon.src = userData.avatar_url;
                    }
                    if (userData.name && profileName) {
                        profileName.textContent = userData.name;
                    }
                }
            } catch (e) {
                console.log('Could not load full user data');
            }
        } else {
            isLoggedIn = false;
            if (settingsLogoutItem) settingsLogoutItem.style.display = 'none';
        }
    } catch (error) {
        console.error('Error loading user profile:', error);
        isLoggedIn = false;
    }
}

// Load user repositories for filter dropdown
async function loadRepositories() {
    const repoFilter = document.getElementById('filter-repo');
    
    try {
        const response = await fetch('/api/github/repos', { credentials: 'include' });
        if (!response.ok) throw new Error('Failed to fetch repositories');
        
        const data = await response.json();
        const repos = data.repos || [];
        
        if (repoFilter) {
            repoFilter.innerHTML = '<option value="all">All Repositories</option>';
            repos.forEach(repo => {
                const option = document.createElement('option');
                option.value = repo.full_name;
                option.textContent = repo.full_name;
                repoFilter.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Error loading repositories:', error);
    }
}

// Load pipeline results (automatic analysis from webhooks)
async function loadPipelineResults() {
    const loadingState = document.getElementById('loading-state');
    const emptyState = document.getElementById('empty-state');
    const resultsList = document.getElementById('results-list');
    
    try {
        // Show loading
        if (loadingState) loadingState.style.display = 'flex';
        if (emptyState) emptyState.style.display = 'none';
        
        // Remove any existing result items
        const existingItems = resultsList?.querySelectorAll('.result-item');
        existingItems?.forEach(item => item.remove());
        
        const response = await fetch('/api/pipeline/recent?limit=50', { credentials: 'include' });
        
        if (!response.ok) {
            throw new Error('Failed to load pipeline results');
        }
        
        const data = await response.json();
        allResults = data.results || [];
        
        // Hide loading
        if (loadingState) loadingState.style.display = 'none';
        
        // Apply filters and render
        filterAndRenderResults();
        
    } catch (error) {
        console.error('Error loading pipeline results:', error);
        if (loadingState) loadingState.style.display = 'none';
        showEmptyState('Failed to load results. Please try again.');
    }
}

// Filter and render results based on current filter values
function filterAndRenderResults() {
    const riskFilter = document.getElementById('filter-risk');
    const repoFilter = document.getElementById('filter-repo');
    const searchInput = document.getElementById('filter-search');
    
    const riskValue = riskFilter?.value || 'all';
    const repoValue = repoFilter?.value || 'all';
    const searchValue = (searchInput?.value || '').toLowerCase().trim();
    
    let filtered = [...allResults];
    
    // Apply risk filter
    if (riskValue !== 'all') {
        filtered = filtered.filter(r => 
            r.impact_analysis && r.impact_analysis.risk_level.toLowerCase() === riskValue
        );
    }
    
    // Apply repo filter
    if (repoValue !== 'all') {
        filtered = filtered.filter(r => r.repository === repoValue);
    }
    
    // Apply search filter
    if (searchValue) {
        filtered = filtered.filter(r => {
            const repo = (r.repository || '').toLowerCase();
            const commit = (r.commit_sha || '').toLowerCase();
            const branch = (r.branch || '').toLowerCase();
            return repo.includes(searchValue) || commit.includes(searchValue) || branch.includes(searchValue);
        });
    }
    
    // Render results
    renderResults(filtered);
}

// Render results list
function renderResults(results) {
    const resultsList = document.getElementById('results-list');
    const emptyState = document.getElementById('empty-state');
    
    if (!resultsList) return;
    
    // Remove existing items (keep loading and empty states)
    const existingItems = resultsList.querySelectorAll('.result-item');
    existingItems.forEach(item => item.remove());
    
    if (results.length === 0) {
        if (emptyState) emptyState.style.display = 'flex';
        return;
    }
    
    if (emptyState) emptyState.style.display = 'none';
    
    results.forEach(result => {
        const impact = result.impact_analysis;
        const riskLevel = impact ? impact.risk_level.toLowerCase() : 'low';
        const riskScore = impact ? (impact.risk_score * 100).toFixed(0) : '0';
        const commitShort = result.commit_sha ? result.commit_sha.substring(0, 7) : '--';
        const timeAgo = formatTimeAgo(result.created_at);
        const filesChanged = impact?.files_changed || 0;
        const linesChanged = impact?.lines_changed || 0;
        
        const itemDiv = document.createElement('div');
        itemDiv.className = 'result-item';
        itemDiv.dataset.eventId = result.event_id;
        itemDiv.onclick = () => selectResult(result);
        
        itemDiv.innerHTML = `
            <div class="result-risk-indicator">
                <div class="risk-circle ${riskLevel}">${riskScore}</div>
            </div>
            <div class="result-info">
                <div class="result-repo">${result.repository || 'Unknown Repository'}</div>
                <div class="result-commit">${commitShort}</div>
                <div class="result-meta">
                    <span>${timeAgo}</span>
                    <span>${filesChanged} files</span>
                    <span>${linesChanged} lines</span>
                    <span class="result-badge ${riskLevel}">${riskLevel}</span>
                </div>
            </div>
        `;
        
        resultsList.appendChild(itemDiv);
    });
    
    // Auto-select first result if none selected
    if (results.length > 0 && !selectedEventId) {
        selectResult(results[0]);
    }
}

// Select a result to view details
function selectResult(result) {
    selectedEventId = result.event_id;
    
    // Highlight selected item
    document.querySelectorAll('.result-item').forEach(item => {
        item.classList.remove('selected');
        if (item.dataset.eventId == result.event_id) {
            item.classList.add('selected');
        }
    });
    
    // Show detail content
    const placeholder = document.getElementById('detail-placeholder');
    const detailContent = document.getElementById('detail-content');
    
    if (placeholder) placeholder.style.display = 'none';
    if (detailContent) {
        detailContent.style.display = 'block';
        renderDetailView(result);
    }
}

// Render detail view
function renderDetailView(result) {
    const impact = result.impact_analysis;
    if (!impact) return;
    
    const riskLevel = impact.risk_level.toLowerCase();
    const riskScore = (impact.risk_score * 100).toFixed(0);
    
    // Update risk circle
    const riskCircle = document.getElementById('detail-risk-circle');
    const riskValue = document.getElementById('detail-risk-value');
    if (riskCircle) {
        riskCircle.className = `risk-score-circle ${riskLevel}`;
    }
    if (riskValue) {
        riskValue.textContent = riskScore;
    }
    
    // Update meta info
    const repoName = document.getElementById('detail-repo-name');
    const commitEl = document.getElementById('detail-commit');
    const branchEl = document.getElementById('detail-branch');
    const timeEl = document.getElementById('detail-time');
    
    if (repoName) repoName.textContent = result.repository || 'Unknown Repository';
    if (commitEl) {
        const commitSpan = commitEl.querySelector('span');
        if (commitSpan) commitSpan.textContent = result.commit_sha ? result.commit_sha.substring(0, 7) : '--';
    }
    if (branchEl) {
        const branchSpan = branchEl.querySelector('span');
        if (branchSpan) branchSpan.textContent = result.branch || 'main';
    }
    if (timeEl) {
        const timeSpan = timeEl.querySelector('span');
        if (timeSpan) timeSpan.textContent = formatTimeAgo(result.created_at);
    }
    
    // Update risk badge
    const riskBadge = document.getElementById('detail-risk-badge');
    if (riskBadge) {
        riskBadge.className = `detail-risk-badge ${riskLevel}`;
        riskBadge.querySelector('.badge-text').textContent = `${impact.risk_level} Risk`;
    }
    
    // Update summary
    document.getElementById('detail-files').textContent = impact.files_changed || 0;
    document.getElementById('detail-lines').textContent = impact.lines_changed || 0;
    document.getElementById('detail-change-type').textContent = impact.change_type || '--';
    document.getElementById('detail-component').textContent = impact.component_type || '--';
    
    // Update action
    const actionBox = document.getElementById('detail-action');
    const actionText = document.getElementById('detail-action-text');
    if (actionBox && actionText) {
        const actionClass = getActionClass(impact.recommended_action);
        actionBox.className = `action-box ${actionClass}`;
        actionText.textContent = impact.recommended_action || 'No specific action recommended';
    }
    
    // Update scope
    const scopeContainer = document.getElementById('detail-scope');
    if (scopeContainer) {
        const scopes = impact.affected_scope || [];
        if (scopes.length > 0) {
            scopeContainer.innerHTML = scopes.map(s => `<span class="scope-tag">${s}</span>`).join('');
        } else {
            scopeContainer.innerHTML = '<p class="no-scope">No specific scope detected</p>';
        }
    }
    
    // Update pipeline info
    document.getElementById('detail-event-type').textContent = result.event_type || 'push';
    document.getElementById('detail-author').textContent = result.author || '--';
    document.getElementById('detail-analysis-time').textContent = result.created_at ? 
        new Date(result.created_at).toLocaleString() : '--';
}

// Get action class for styling
function getActionClass(action) {
    if (!action) return '';
    const lower = action.toLowerCase();
    if (lower.includes('full') || lower.includes('comprehensive')) return 'run-full-suite';
    if (lower.includes('impacted') || lower.includes('targeted')) return 'run-impacted-tests';
    return 'run-smoke-tests';
}

// Load pipeline statistics
async function loadPipelineStats() {
    try {
        const response = await fetch('/api/pipeline/stats', { credentials: 'include' });
        if (!response.ok) return;
        
        const stats = await response.json();
        
        // Update stat cards
        const statTotal = document.getElementById('stat-total');
        const statHighRisk = document.getElementById('stat-high-risk');
        const statMediumRisk = document.getElementById('stat-medium-risk');
        const statLowRisk = document.getElementById('stat-low-risk');
        
        if (statTotal) statTotal.textContent = stats.total_analyses || 0;
        if (statHighRisk) statHighRisk.textContent = stats.high_risk_changes || 0;
        if (statMediumRisk) statMediumRisk.textContent = stats.medium_risk_changes || 0;
        if (statLowRisk) statLowRisk.textContent = stats.low_risk_changes || 0;
        
    } catch (error) {
        console.error('Error loading pipeline stats:', error);
    }
}

// Format time ago
function formatTimeAgo(dateString) {
    if (!dateString) return 'Unknown';
    
    const date = new Date(dateString);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);
    
    if (seconds < 60) return 'Just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
    
    return date.toLocaleDateString();
}

// Show empty state with custom message
function showEmptyState(message) {
    const loadingState = document.getElementById('loading-state');
    const emptyState = document.getElementById('empty-state');
    
    if (loadingState) loadingState.style.display = 'none';
    if (emptyState) {
        emptyState.style.display = 'flex';
        const h3 = emptyState.querySelector('h3');
        if (h3 && message) h3.textContent = message;
    }
}

// Initialize filter handlers
function initFilterHandlers() {
    const riskFilter = document.getElementById('filter-risk');
    const repoFilter = document.getElementById('filter-repo');
    const searchInput = document.getElementById('filter-search');
    
    if (riskFilter) {
        riskFilter.addEventListener('change', filterAndRenderResults);
    }
    if (repoFilter) {
        repoFilter.addEventListener('change', filterAndRenderResults);
    }
    if (searchInput) {
        searchInput.addEventListener('input', debounce(filterAndRenderResults, 300));
    }
}

// Initialize refresh button
function initRefreshButton() {
    const refreshBtn = document.getElementById('refresh-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', async () => {
            refreshBtn.disabled = true;
            refreshBtn.querySelector('svg').style.animation = 'spin 0.5s linear infinite';
            
            await loadPipelineResults();
            await loadPipelineStats();
            
            refreshBtn.disabled = false;
            refreshBtn.querySelector('svg').style.animation = '';
        });
    }
}

// Auto-refresh pipeline results
function startAutoRefresh() {
    // Refresh every 30 seconds
    autoRefreshInterval = setInterval(async () => {
        await loadPipelineResults();
        await loadPipelineStats();
    }, 30000);
}

// Debounce helper
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Update logo for theme
function updateLogo() {
    const logo = document.getElementById('logo-img');
    if (logo) {
        const isDark = document.body.classList.contains('dark-theme');
        logo.src = isDark ? '/static/assets/logo_bg.png' : '/static/assets/logo_bg_bl.png';
    }
}

// Initialize theme toggle
function initThemeToggle() {
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', (e) => {
            e.preventDefault();
            document.body.classList.toggle('dark-theme');
            const isDark = document.body.classList.contains('dark-theme');
            localStorage.setItem('theme', isDark ? 'dark' : 'light');
            updateLogo();
        });
    }
}

// Initialize profile dropdown
function initProfileDropdown() {
    const profileToggle = document.getElementById('profile-toggle');
    const profileDropdown = document.getElementById('profile-dropdown');
    
    if (profileToggle && profileDropdown) {
        profileToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            const isVisible = profileDropdown.style.display === 'block';
            profileDropdown.style.display = isVisible ? 'none' : 'block';
        });
        
        document.addEventListener('click', (e) => {
            if (!profileDropdown.contains(e.target) && e.target !== profileToggle) {
                profileDropdown.style.display = 'none';
            }
        });
    }
    
    // Login button
    const loginBtn = document.getElementById('dropdown-login-btn');
    if (loginBtn) {
        loginBtn.addEventListener('click', (e) => {
            e.preventDefault();
            window.location.href = '/auth/github/login';
        });
    }
}

// Initialize settings dropdown
function initSettingsDropdown() {
    const settingsToggle = document.getElementById('settings-toggle');
    const menuDropdown = settingsToggle?.closest('.menu-item-dropdown');
    
    if (settingsToggle && menuDropdown) {
        settingsToggle.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            menuDropdown.classList.toggle('open');
        });
        
        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (!menuDropdown.contains(e.target)) {
                menuDropdown.classList.remove('open');
            }
        });
    }
}

// Clean up on page unload
window.addEventListener('beforeunload', () => {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
    }
});
