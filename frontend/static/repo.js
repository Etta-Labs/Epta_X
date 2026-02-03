/**
 * ETTA-X Repositories View
 * DevOps-style repository inspection interface
 */

// Get API base URL from config (set by api-config.js)
function getApiUrl(endpoint) {
    return window.ETTA_API ? `${window.ETTA_API.baseUrl}${endpoint}` : endpoint;
}

// Handle logout - call API and redirect to setup
async function handleLogout(event) {
    if (event) event.preventDefault();
    try {
        await window.ETTA_API.authFetch(getApiUrl('/auth/github/logout'), {
            method: 'GET'
        });
    } catch (e) {
        console.error('Logout error:', e);
    }
    // Clear stored token
    if (window.ETTA_API && window.ETTA_API.clearToken) {
        window.ETTA_API.clearToken();
    }
    // Clear local storage
    localStorage.removeItem('lastUsername');
    localStorage.removeItem('lastAvatar');
    localStorage.removeItem('lastName');
    localStorage.removeItem('selectedRepo');
    localStorage.removeItem('selectedBranch');
    localStorage.removeItem('setupComplete');
    // Redirect to setup page
    window.location.href = 'setup.html';
}

document.addEventListener('DOMContentLoaded', function () {
    // ==================== STATE ====================
    let currentView = 'raw'; // 'raw' or 'logical'
    let selectedRepo = null;
    let selectedFile = null;
    let repositoriesData = [];
    let currentAnalysis = null;
    let lastEventId = null;  // Track last event for polling
    let pollInterval = null; // Polling interval reference

    // ==================== DOM ELEMENTS ====================
    const rawViewBtn = document.getElementById('raw-view-btn');
    const logicalViewBtn = document.getElementById('logical-view-btn');
    const refreshBtn = document.getElementById('refresh-btn');
    const repoList = document.getElementById('repo-list');
    const repoCount = document.getElementById('repo-count');
    const summaryPanel = document.getElementById('summary-panel');
    const historyPanel = document.getElementById('history-panel');
    const diffPanel = document.getElementById('diff-panel');
    const logicalPanel = document.getElementById('logical-panel');
    const emptyStatePanel = document.getElementById('empty-state-panel');
    const fileTree = document.getElementById('file-tree');
    const diffContent = document.getElementById('diff-content');
    const fileFilterInput = document.getElementById('file-filter-input');
    const historyList = document.getElementById('history-list');
    const historyCount = document.getElementById('history-count');

    // Theme toggle
    const themeToggle = document.getElementById('theme-toggle');
    const settingsToggle = document.getElementById('settings-toggle');

    // ==================== INITIALIZATION ====================
    initTheme();
    initEventListeners();
    loadRepositories();

    // ==================== THEME ====================
    function initTheme() {
        const savedTheme = localStorage.getItem('theme');
        if (savedTheme === 'dark') {
            document.body.classList.add('dark-theme');
        }
    }

    function toggleTheme() {
        document.body.classList.toggle('dark-theme');
        const isDark = document.body.classList.contains('dark-theme');
        localStorage.setItem('theme', isDark ? 'dark' : 'light');
    }

    // Make toggleTheme globally available
    window.toggleTheme = toggleTheme;

    // ==================== EVENT LISTENERS ====================
    function initEventListeners() {
        // View toggle
        rawViewBtn?.addEventListener('click', () => switchView('raw'));
        logicalViewBtn?.addEventListener('click', () => switchView('logical'));

        // Refresh
        refreshBtn?.addEventListener('click', refreshData);

        // File filter
        fileFilterInput?.addEventListener('input', filterFiles);

        // Theme toggle
        themeToggle?.addEventListener('click', (e) => {
            e.preventDefault();
            toggleTheme();
        });

        // Settings dropdown
        settingsToggle?.addEventListener('click', (e) => {
            e.preventDefault();
            const dropdown = document.querySelector('.menu-item-dropdown');
            dropdown?.classList.toggle('open');
        });
    }

    // ==================== VIEW SWITCHING ====================
    function switchView(view) {
        currentView = view;

        // Update buttons
        rawViewBtn?.classList.toggle('active', view === 'raw');
        logicalViewBtn?.classList.toggle('active', view === 'logical');

        // Update panel title
        const diffPanelTitle = document.getElementById('diff-panel-title');
        if (diffPanelTitle) {
            diffPanelTitle.textContent = view === 'raw' ? 'Changed Files' : 'Logical Changes';
        }

        // Toggle panels
        if (selectedRepo && currentAnalysis) {
            diffPanel.style.display = view === 'raw' ? 'flex' : 'none';
            logicalPanel.style.display = view === 'logical' ? 'flex' : 'none';
            logicalPanel.classList.toggle('active', view === 'logical');
        }
    }

    // ==================== DATA LOADING ====================
    async function loadRepositories() {
        showLoading(repoList);

        try {
            const response = await window.ETTA_API.authFetch(getApiUrl('/api/repositories/connected'));

            if (!response.ok) {
                if (response.status === 401) {
                    showEmptyState(repoList, 'Sign in to view repositories');
                    return;
                }
                throw new Error('Failed to load repositories');
            }

            const data = await response.json();
            repositoriesData = data.repositories || [];
            renderRepositories();

        } catch (error) {
            console.error('Error loading repositories:', error);
            showEmptyState(repoList, 'Failed to load repositories');
        }
    }

    function renderRepositories() {
        if (repositoriesData.length === 0) {
            showEmptyState(repoList, 'No connected repositories');
            repoCount.textContent = '0 repositories';
            return;
        }

        repoCount.textContent = `${repositoriesData.length} repositor${repositoriesData.length === 1 ? 'y' : 'ies'}`;

        repoList.innerHTML = repositoriesData.map(repo => `
            <div class="repo-item" data-repo-id="${repo.id}" data-full-name="${repo.full_name}">
                <div class="repo-item-header">
                    <div class="repo-icon">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                        </svg>
                    </div>
                    <span class="repo-name" title="${repo.full_name}">${repo.name}</span>
                    ${repo.is_private ? '<span class="repo-private-badge">Private</span>' : ''}
                </div>
                <div class="repo-item-meta">
                    <span class="repo-branch">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="6" y1="3" x2="6" y2="15"></line>
                            <circle cx="18" cy="6" r="3"></circle>
                            <circle cx="6" cy="18" r="3"></circle>
                            <path d="M18 9a9 9 0 0 1-9 9"></path>
                        </svg>
                        ${repo.default_branch || 'main'}
                    </span>
                    ${repo.last_commit ? `
                        <span class="repo-commit">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <circle cx="12" cy="12" r="4"></circle>
                                <line x1="1.05" y1="12" x2="7" y2="12"></line>
                                <line x1="17.01" y1="12" x2="22.96" y2="12"></line>
                            </svg>
                            ${repo.last_commit.substring(0, 7)}
                        </span>
                    ` : ''}
                </div>
                <div class="repo-item-footer">
                    <div class="repo-webhook-status">
                        <span class="webhook-indicator ${repo.webhook_active ? 'active' : ''}"></span>
                        ${repo.webhook_active ? 'Webhook active' : 'No webhook'}
                    </div>
                    ${repo.last_event_at ? `
                        <span class="repo-last-event">${formatRelativeTime(repo.last_event_at)}</span>
                    ` : ''}
                </div>
            </div>
        `).join('');

        // Add click listeners
        repoList.querySelectorAll('.repo-item').forEach(item => {
            item.addEventListener('click', () => selectRepository(item));
        });
    }

    async function selectRepository(element) {
        // Update selection UI
        repoList.querySelectorAll('.repo-item').forEach(i => i.classList.remove('selected'));
        element.classList.add('selected');

        const repoId = element.dataset.repoId;
        const fullName = element.dataset.fullName;
        selectedRepo = repositoriesData.find(r => r.id == repoId);

        // Hide empty state, show panels
        emptyStatePanel.classList.add('hidden');
        summaryPanel.style.display = 'block';
        
        if (currentView === 'raw') {
            diffPanel.style.display = 'flex';
            logicalPanel.style.display = 'none';
        } else {
            diffPanel.style.display = 'none';
            logicalPanel.style.display = 'flex';
            logicalPanel.classList.add('active');
        }

        // Load analysis data and history
        await Promise.all([
            loadRepositoryAnalysis(fullName),
            loadCommitHistory(fullName)
        ]);
        
        // Start polling for updates
        startPolling(fullName);
    }

    async function loadCommitHistory(fullName) {
        if (!historyList) return;
        
        historyList.innerHTML = '<div class="loading-state"><div class="spinner"></div><span>Loading history...</span></div>';
        
        try {
            const response = await window.ETTA_API.authFetch(getApiUrl(`/api/repositories/${encodeURIComponent(fullName)}/events?limit=10`));
            
            if (!response.ok) throw new Error('Failed to load history');
            
            const data = await response.json();
            const events = data.events || [];
            
            if (historyCount) {
                historyCount.textContent = `${events.length} events`;
            }
            
            if (events.length === 0) {
                historyList.innerHTML = '<div class="empty-state"><p>No commit history</p></div>';
                return;
            }
            
            historyList.innerHTML = events.map((event, index) => `
                <div class="history-item ${index === 0 ? 'selected' : ''}" data-event-id="${event.id}" data-commit="${event.commit_sha}">
                    <div class="history-icon">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="4"></circle>
                            <line x1="1.05" y1="12" x2="7" y2="12"></line>
                            <line x1="17.01" y1="12" x2="22.96" y2="12"></line>
                        </svg>
                    </div>
                    <div class="history-content">
                        <div class="history-commit">
                            <span class="history-sha">${event.commit_sha ? event.commit_sha.slice(0, 7) : 'unknown'}</span>
                            <span class="history-time">${formatRelativeTime(event.created_at)}</span>
                        </div>
                        <div class="history-message">${event.event_type === 'push' ? 'Push to ' + (event.branch || 'main') : event.event_type}</div>
                        <div class="history-stats">
                            <span class="history-stat files">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                                </svg>
                                ${event.processed ? 'âœ“ Processed' : 'Pending'}
                            </span>
                        </div>
                    </div>
                </div>
            `).join('');
            
            // Add click listeners to load specific commits
            historyList.querySelectorAll('.history-item').forEach(item => {
                item.addEventListener('click', async () => {
                    historyList.querySelectorAll('.history-item').forEach(i => i.classList.remove('selected'));
                    item.classList.add('selected');
                    
                    const eventId = item.dataset.eventId;
                    if (eventId && selectedRepo) {
                        await loadEventAnalysis(selectedRepo.full_name, eventId);
                    }
                });
            });
            
        } catch (error) {
            console.error('Error loading history:', error);
            historyList.innerHTML = '<div class="empty-state"><p>Failed to load history</p></div>';
        }
    }

    async function loadEventAnalysis(fullName, eventId) {
        showLoading(fileTree);
        clearDiffContent();

        try {
            const response = await window.ETTA_API.authFetch(getApiUrl(`/api/repositories/${encodeURIComponent(fullName)}/analysis?event_id=${eventId}`));

            if (!response.ok) {
                throw new Error('Failed to load analysis');
            }

            const data = await response.json();
            console.log('Event analysis received:', data);
            currentAnalysis = data;

            renderSummary(data);
            renderFileTree(data.files || []);
            renderLogicalChanges(data);

        } catch (error) {
            console.error('Error loading event analysis:', error);
            showEmptyState(fileTree, 'No analysis data available');
        }
    }

    async function loadRepositoryAnalysis(fullName) {
        showLoading(fileTree);
        clearDiffContent();

        try {
            const response = await window.ETTA_API.authFetch(getApiUrl(`/api/repositories/${encodeURIComponent(fullName)}/analysis`));

            if (!response.ok) {
                throw new Error('Failed to load analysis');
            }

            const data = await response.json();
            console.log('Analysis data received:', data);
            console.log('Files:', data.files);
            currentAnalysis = data;

            renderSummary(data);
            renderFileTree(data.files || []);
            renderLogicalChanges(data);

        } catch (error) {
            console.error('Error loading analysis:', error);
            showEmptyState(fileTree, 'No analysis data available');
        }
    }

    // ==================== POLLING FOR UPDATES ====================
    async function startPolling(fullName) {
        // Clear any existing polling
        stopPolling();
        
        // First, get the current latest event ID so we only notify on NEW events
        try {
            const initResponse = await window.ETTA_API.authFetch(getApiUrl(`/api/repositories/${encodeURIComponent(fullName)}/latest-event`));
            if (initResponse.ok) {
                const initData = await initResponse.json();
                if (initData.has_update && initData.event_id) {
                    lastEventId = initData.event_id;
                    console.log('Initialized lastEventId:', lastEventId);
                }
            }
        } catch (e) {
            console.error('Failed to initialize polling:', e);
        }
        
        // Poll every 5 seconds for updates
        pollInterval = setInterval(async () => {
            if (!selectedRepo) {
                stopPolling();
                return;
            }
            
            try {
                const response = await window.ETTA_API.authFetch(getApiUrl(`/api/repositories/${encodeURIComponent(fullName)}/latest-event`));
                
                if (!response.ok) return;
                
                const data = await response.json();
                
                // Check if there's a NEW processed event (different ID than what we have)
                if (data.has_update && data.processed && data.event_id && data.event_id !== lastEventId) {
                    console.log('New update detected! Old ID:', lastEventId, 'New ID:', data.event_id);
                    lastEventId = data.event_id;
                    
                    // Show notification
                    showUpdateNotification(data.commit_sha);
                    
                    // Reload the analysis data
                    await loadRepositoryAnalysis(fullName);
                    
                    // Also reload repositories list to update commit hash display
                    await loadRepositories();
                }
            } catch (error) {
                console.error('Polling error:', error);
            }
        }, 5000); // Check every 5 seconds
    }
    
    function stopPolling() {
        if (pollInterval) {
            clearInterval(pollInterval);
            pollInterval = null;
        }
    }
    
    function showUpdateNotification(commitSha) {
        // Create a subtle notification
        const notification = document.createElement('div');
        notification.className = 'update-notification';
        notification.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                <polyline points="22 4 12 14.01 9 11.01"></polyline>
            </svg>
            <span>New commit ${commitSha ? `(${commitSha})` : ''} processed</span>
        `;
        document.body.appendChild(notification);
        
        // Animate in
        setTimeout(() => notification.classList.add('show'), 10);
        
        // Remove after 3 seconds
        setTimeout(() => {
            notification.classList.remove('show');
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }

    // ==================== RENDERING ====================
    function renderSummary(data) {
        // Update stats
        document.getElementById('files-changed').textContent = data.summary?.files_changed || 0;
        document.getElementById('lines-added').textContent = data.summary?.lines_added || 0;
        document.getElementById('lines-removed').textContent = data.summary?.lines_removed || 0;
        document.getElementById('commit-count').textContent = data.summary?.commits || 0;

        // Update webhook time
        const webhookTime = document.getElementById('webhook-time');
        if (data.webhook_timestamp) {
            webhookTime.textContent = `Last update: ${formatRelativeTime(data.webhook_timestamp)}`;
        } else {
            webhookTime.textContent = '';
        }

        // Render change types
        const changeTypes = document.getElementById('change-types');
        const types = data.summary?.change_types || [];
        changeTypes.innerHTML = types.map(type => `
            <span class="change-type-badge ${type.toLowerCase()}">
                ${getChangeTypeIcon(type)}
                ${type}
            </span>
        `).join('');
    }

    function renderFileTree(files) {
        if (!files || files.length === 0) {
            showEmptyState(fileTree, 'No changed files');
            return;
        }

        fileTree.innerHTML = files.map((file, index) => `
            <div class="file-item" data-index="${index}" data-path="${file.path}">
                <div class="file-icon ${file.change_type}">
                    ${getFileChangeIcon(file.change_type)}
                </div>
                <span class="file-path">${file.path}</span>
                <div class="file-stats">
                    ${file.additions > 0 ? `<span class="file-additions">+${file.additions}</span>` : ''}
                    ${file.deletions > 0 ? `<span class="file-deletions">-${file.deletions}</span>` : ''}
                </div>
            </div>
        `).join('');

        // Add click listeners
        fileTree.querySelectorAll('.file-item').forEach(item => {
            item.addEventListener('click', () => selectFile(item));
        });
    }

    function selectFile(element) {
        fileTree.querySelectorAll('.file-item').forEach(i => i.classList.remove('selected'));
        element.classList.add('selected');

        const index = parseInt(element.dataset.index);
        const file = currentAnalysis?.files?.[index];
        
        if (file) {
            selectedFile = file;
            renderDiff(file);
        }
    }

    function renderDiff(file) {
        if (!file.diff) {
            diffContent.innerHTML = `
                <div class="empty-state">
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                        <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                        <polyline points="13 2 13 9 20 9"></polyline>
                    </svg>
                    <p>No diff available for this file</p>
                </div>
            `;
            return;
        }

        const hunks = parseDiff(file.diff);
        diffContent.innerHTML = hunks.map(hunk => `
            <div class="diff-hunk">
                <div class="diff-hunk-header">${escapeHtml(hunk.header)}</div>
                ${hunk.lines.map(line => `
                    <div class="diff-line ${line.type}">
                        <span class="diff-line-number">${line.lineNum || ''}</span>
                        <span class="diff-line-content">${escapeHtml(line.content)}</span>
                    </div>
                `).join('')}
            </div>
        `).join('');
    }

    function renderLogicalChanges(data) {
        const logical = data.logical_changes || {};

        // Functions
        renderLogicalSection('functions', logical.functions || []);

        // Classes
        renderLogicalSection('classes', logical.classes || []);

        // API Routes
        renderLogicalSection('routes', logical.routes || []);

        // Imports
        renderLogicalSection('imports', logical.imports || []);
    }

    function renderLogicalSection(sectionId, items) {
        const countEl = document.getElementById(`${sectionId}-count`);
        const listEl = document.getElementById(`${sectionId}-list`);

        countEl.textContent = items.length;

        if (items.length === 0) {
            listEl.innerHTML = `
                <div class="logical-item" style="justify-content: center; color: #9ca3af;">
                    No changes detected
                </div>
            `;
            return;
        }

        listEl.innerHTML = items.map(item => `
            <div class="logical-item">
                <span class="item-change-type ${item.change_type}">${item.change_type}</span>
                <div class="item-details">
                    <div class="item-name">${escapeHtml(item.name)}</div>
                    <div class="item-meta">
                        <span class="item-file">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                                <polyline points="13 2 13 9 20 9"></polyline>
                            </svg>
                            ${item.file || 'Unknown file'}
                        </span>
                        ${item.line_start ? `
                            <span class="item-lines">L${item.line_start}${item.line_end ? `-${item.line_end}` : ''}</span>
                        ` : ''}
                    </div>
                </div>
            </div>
        `).join('');
    }

    // ==================== FILE FILTERING ====================
    function filterFiles() {
        const filter = fileFilterInput.value.toLowerCase();
        fileTree.querySelectorAll('.file-item').forEach(item => {
            const path = item.dataset.path.toLowerCase();
            item.style.display = path.includes(filter) ? 'flex' : 'none';
        });
    }

    // ==================== REFRESH ====================
    async function refreshData() {
        refreshBtn.classList.add('loading');

        try {
            await loadRepositories();

            if (selectedRepo) {
                await loadRepositoryAnalysis(selectedRepo.full_name);
            }
        } finally {
            refreshBtn.classList.remove('loading');
        }
    }

    // ==================== UTILITIES ====================
    function showLoading(container) {
        container.innerHTML = `
            <div class="loading-state">
                <div class="spinner"></div>
                <span>Loading...</span>
            </div>
        `;
    }

    function showEmptyState(container, message) {
        container.innerHTML = `
            <div class="loading-state">
                <span>${message}</span>
            </div>
        `;
    }

    function clearDiffContent() {
        diffContent.innerHTML = `
            <div class="empty-state">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                    <polyline points="13 2 13 9 20 9"></polyline>
                </svg>
                <p>Select a file to view changes</p>
            </div>
        `;
    }

    function formatRelativeTime(timestamp) {
        if (!timestamp) return '';
        
        const date = new Date(timestamp);
        const now = new Date();
        const diff = Math.floor((now - date) / 1000);

        if (diff < 60) return 'just now';
        if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
        if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
        
        return date.toLocaleDateString();
    }

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function parseDiff(diffText) {
        if (!diffText) return [];

        const lines = diffText.split('\n');
        const hunks = [];
        let currentHunk = null;
        let lineNum = 0;

        for (const line of lines) {
            if (line.startsWith('@@')) {
                if (currentHunk) hunks.push(currentHunk);
                currentHunk = { header: line, lines: [] };
                
                // Parse line numbers from hunk header
                const match = line.match(/@@ -\d+(?:,\d+)? \+(\d+)/);
                lineNum = match ? parseInt(match[1]) - 1 : 0;
            } else if (currentHunk) {
                let type = 'context';
                let content = line;
                let num = null;

                if (line.startsWith('+')) {
                    type = 'addition';
                    content = line.substring(1);
                    lineNum++;
                    num = lineNum;
                } else if (line.startsWith('-')) {
                    type = 'deletion';
                    content = line.substring(1);
                } else {
                    lineNum++;
                    num = lineNum;
                }

                currentHunk.lines.push({ type, content, lineNum: num });
            }
        }

        if (currentHunk) hunks.push(currentHunk);
        return hunks;
    }

    function getFileChangeIcon(changeType) {
        switch (changeType) {
            case 'added':
                return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="12" y1="5" x2="12" y2="19"></line>
                    <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>`;
            case 'deleted':
                return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>`;
            case 'renamed':
                return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                    <polyline points="15 3 21 3 21 9"></polyline>
                    <line x1="10" y1="14" x2="21" y2="3"></line>
                </svg>`;
            default: // modified
                return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                </svg>`;
        }
    }

    function getChangeTypeIcon(type) {
        switch (type.toLowerCase()) {
            case 'api':
                return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="2" y1="12" x2="22" y2="12"></line>
                </svg>`;
            case 'service':
                return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
                    <line x1="8" y1="21" x2="16" y2="21"></line>
                    <line x1="12" y1="17" x2="12" y2="21"></line>
                </svg>`;
            case 'ui':
                return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                    <line x1="3" y1="9" x2="21" y2="9"></line>
                </svg>`;
            case 'config':
                return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="3"></circle>
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
                </svg>`;
            case 'test':
                return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="9 11 12 14 22 4"></polyline>
                    <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path>
                </svg>`;
            default:
                return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                </svg>`;
        }
    }
});


