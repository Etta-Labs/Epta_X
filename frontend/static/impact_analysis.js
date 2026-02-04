/**
 * ETTA-X Impact Analysis Page
 * JavaScript for ML-powered risk prediction
 * New 3-column grid layout
 */

// Get API base URL from config
function getApiUrl(endpoint) {
    return window.ETTA_API ? `${window.ETTA_API.baseUrl}${endpoint}` : endpoint;
}

document.addEventListener('DOMContentLoaded', function () {
    // ==================== STATE ====================
    let repositories = [];
    let predictions = [];
    let selectedRepo = null;
    let selectedPrediction = null;
    let autoStartAnalysis = false;

    // ==================== DOM ELEMENTS ====================
    const repoList = document.getElementById('repo-list');
    const repoCount = document.getElementById('repo-count');
    const refreshBtn = document.getElementById('refresh-btn');
    const searchInput = document.getElementById('search-input');
    const filterSelect = document.getElementById('filter-select');
    const commitList = document.getElementById('commit-list');
    const detailsContent = document.getElementById('details-content');
    const statsPanel = document.getElementById('stats-panel');
    const commitPanel = document.getElementById('commit-panel');
    const detailsPanel = document.getElementById('details-panel');
    const emptyStatePanel = document.getElementById('empty-state-panel');

    // Stats elements
    const statTotal = document.getElementById('stat-total');
    const statHigh = document.getElementById('stat-high');
    const statMedium = document.getElementById('stat-medium');
    const statLow = document.getElementById('stat-low');

    // ==================== INITIALIZATION ====================
    console.log('[Impact Analysis] Initializing...');
    
    // Check for URL parameters
    const urlParams = new URLSearchParams(window.location.search);
    const repoParam = urlParams.get('repo');
    const branchParam = urlParams.get('branch');
    autoStartAnalysis = urlParams.get('autostart') === 'true';
    
    if (repoParam) {
        console.log('[Impact Analysis] Found repo in URL:', repoParam);
        selectedRepo = repoParam;
    }

    loadRepositories();
    initEventListeners();
    initSelfHealingPanel();

    // ==================== SELF-HEALING PANEL ====================
    function initSelfHealingPanel() {
        const toggle = document.getElementById('self-healing-toggle');
        const panel = document.getElementById('self-healing-panel');
        
        if (toggle && panel) {
            toggle.addEventListener('click', function(e) {
                e.stopPropagation();
                panel.classList.toggle('open');
                toggle.classList.toggle('active');
            });
            
            // Close when clicking outside
            document.addEventListener('click', function(e) {
                if (!panel.contains(e.target) && !toggle.contains(e.target)) {
                    panel.classList.remove('open');
                    toggle.classList.remove('active');
                }
            });
        }
    }

    // ==================== EVENT LISTENERS ====================
    function initEventListeners() {
        refreshBtn?.addEventListener('click', () => {
            if (selectedRepo) {
                refreshBtn.classList.add('loading');
                loadImpactData(selectedRepo).finally(() => {
                    refreshBtn.classList.remove('loading');
                });
            }
        });

        searchInput?.addEventListener('input', filterCommitList);
        filterSelect?.addEventListener('change', filterCommitList);
    }

    // ==================== LOAD REPOSITORIES ====================
    async function loadRepositories() {
        console.log('[Impact Analysis] Loading repositories...');
        try {
            const response = await window.ETTA_API.authFetch(getApiUrl('/api/repositories/connected'));

            if (!response.ok) {
                console.error('[Impact Analysis] Failed to load repositories:', response.status);
                renderRepoList([]);
                return;
            }

            const data = await response.json();
            repositories = data.repositories || [];
            console.log('[Impact Analysis] Loaded', repositories.length, 'repositories');
            renderRepoList(repositories);

            // Auto-select from URL parameter
            if (selectedRepo) {
                const repo = repositories.find(r => r.full_name === selectedRepo);
                if (repo) {
                    selectRepository(repo);
                }
            }

        } catch (error) {
            console.error('[Impact Analysis] Error loading repositories:', error);
            renderRepoList([]);
        }
    }

    // ==================== RENDER REPO LIST ====================
    function renderRepoList(repos) {
        if (!repoList) return;

        if (repoCount) {
            repoCount.textContent = `${repos.length} repos`;
        }

        if (repos.length === 0) {
            repoList.innerHTML = `
                <div class="empty-state">
                    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                    </svg>
                    <p>No repositories connected</p>
                    <span class="hint">Connect a repository from the Dashboard</span>
                </div>
            `;
            return;
        }

        repoList.innerHTML = repos.map(repo => `
            <div class="repo-item ${repo.full_name === selectedRepo ? 'selected' : ''}" data-repo="${repo.full_name}">
                <div class="repo-item-header">
                    <div class="repo-icon">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                        </svg>
                    </div>
                    <span class="repo-name">${repo.full_name}</span>
                </div>
                <div class="repo-meta">
                    <span>${repo.branch || 'main'}</span>
                </div>
            </div>
        `).join('');

        // Add click listeners
        repoList.querySelectorAll('.repo-item').forEach(item => {
            item.addEventListener('click', () => {
                const repoName = item.dataset.repo;
                const repo = repositories.find(r => r.full_name === repoName);
                if (repo) {
                    selectRepository(repo);
                }
            });
        });
    }

    // ==================== SELECT REPOSITORY ====================
    function selectRepository(repo) {
        selectedRepo = repo.full_name;
        
        // Update URL without reload
        const newUrl = `${window.location.pathname}?repo=${encodeURIComponent(repo.full_name)}`;
        window.history.replaceState({}, '', newUrl);
        
        // Update UI selection
        repoList.querySelectorAll('.repo-item').forEach(item => {
            item.classList.toggle('selected', item.dataset.repo === repo.full_name);
        });

        // Show panels, hide empty state
        if (statsPanel) statsPanel.style.display = '';
        if (commitPanel) commitPanel.style.display = '';
        if (detailsPanel) detailsPanel.style.display = '';
        if (emptyStatePanel) emptyStatePanel.classList.add('hidden');

        // Load data
        loadImpactData(repo.full_name);
    }

    // ==================== LOAD IMPACT DATA ====================
    async function loadImpactData(fullName) {
        try {
            // Show loading state
            if (commitList) {
                commitList.innerHTML = `
                    <div class="loading-state">
                        <div class="spinner"></div>
                        <span>Loading impact analyses...</span>
                    </div>
                `;
            }

            // Load stats and history in parallel
            const [statsRes, historyRes] = await Promise.all([
                window.ETTA_API.authFetch(getApiUrl(`/api/impact-analysis/stats/${encodeURIComponent(fullName)}`)),
                window.ETTA_API.authFetch(getApiUrl(`/api/impact-analysis/history/${encodeURIComponent(fullName)}`))
            ]);

            let historyData = { predictions: [] };

            if (statsRes.ok) {
                const statsData = await statsRes.json();
                renderStats(statsData.stats);
            }

            if (historyRes.ok) {
                historyData = await historyRes.json();
                predictions = historyData.predictions || [];
            }

            // If no predictions exist or autostart is true, fetch recent commits and analyze them
            if (predictions.length === 0 || autoStartAnalysis) {
                console.log('[Impact Analysis] Analyzing commits...');
                autoStartAnalysis = false; // Reset flag
                await analyzeRecentCommits(fullName);
            } else {
                renderCommitList(predictions);
            }

        } catch (error) {
            console.error('Error loading impact data:', error);
            if (commitList) {
                commitList.innerHTML = `
                    <div class="empty-state">
                        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                            <circle cx="12" cy="12" r="10"></circle>
                            <line x1="12" y1="8" x2="12" y2="12"></line>
                            <line x1="12" y1="16" x2="12.01" y2="16"></line>
                        </svg>
                        <p>Error loading data</p>
                        <span class="hint">Please try again</span>
                    </div>
                `;
            }
        }
    }

    // ==================== ANALYZE RECENT COMMITS ====================
    async function analyzeRecentCommits(fullName) {
        try {
            // Show analyzing state
            if (commitList) {
                commitList.innerHTML = `
                    <div class="loading-state">
                        <div class="spinner"></div>
                        <span>Analyzing recent commits...</span>
                    </div>
                `;
            }

            // Fetch recent commits from the repository
            const commitsRes = await window.ETTA_API.authFetch(
                getApiUrl(`/api/repositories/${encodeURIComponent(fullName)}/commits?limit=10`)
            );

            if (!commitsRes.ok) {
                console.error('[Impact Analysis] Failed to fetch commits');
                renderCommitList([]);
                return;
            }

            const commitsData = await commitsRes.json();
            const commits = commitsData.commits || [];

            if (commits.length === 0) {
                console.log('[Impact Analysis] No commits found');
                renderCommitList([]);
                return;
            }

            console.log(`[Impact Analysis] Analyzing ${commits.length} commits...`);

            // Analyze each commit (run up to 5 to avoid overwhelming)
            const analyzePromises = commits.slice(0, 5).map(commit =>
                analyzeCommit(fullName, commit.sha)
            );

            await Promise.all(analyzePromises);

            // Reload history after analysis
            const historyRes = await window.ETTA_API.authFetch(
                getApiUrl(`/api/impact-analysis/history/${encodeURIComponent(fullName)}`)
            );

            if (historyRes.ok) {
                const historyData = await historyRes.json();
                predictions = historyData.predictions || [];
                renderCommitList(predictions);

                // Refresh stats
                const statsRes = await window.ETTA_API.authFetch(
                    getApiUrl(`/api/impact-analysis/stats/${encodeURIComponent(fullName)}`)
                );
                if (statsRes.ok) {
                    const statsData = await statsRes.json();
                    renderStats(statsData.stats);
                }
            }

        } catch (error) {
            console.error('[Impact Analysis] Error analyzing commits:', error);
            renderCommitList([]);
        }
    }

    // ==================== ANALYZE SINGLE COMMIT ====================
    async function analyzeCommit(fullName, commitSha) {
        try {
            const response = await window.ETTA_API.authFetch(
                getApiUrl(`/api/impact-analysis/analyze/${encodeURIComponent(fullName)}/commit/${commitSha}`)
            );

            if (response.ok) {
                const result = await response.json();
                console.log(`[Impact Analysis] Analyzed ${commitSha.substring(0, 7)}:`, result.prediction);
                return result;
            }
        } catch (error) {
            console.error(`[Impact Analysis] Error analyzing commit ${commitSha}:`, error);
        }
        return null;
    }

    // ==================== RENDER STATS ====================
    function renderStats(stats) {
        if (!stats) return;

        if (statTotal) statTotal.textContent = stats.total || 0;
        if (statHigh) statHigh.textContent = stats.high_risk || 0;
        if (statMedium) statMedium.textContent = stats.medium_risk || 0;
        if (statLow) statLow.textContent = (stats.low_risk || 0) + (stats.no_risk || 0);
    }

    // ==================== RENDER COMMIT LIST ====================
    function renderCommitList(items) {
        if (!commitList) return;

        if (!items || items.length === 0) {
            commitList.innerHTML = `
                <div class="empty-state">
                    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                        <circle cx="12" cy="12" r="4"></circle>
                        <line x1="1.05" y1="12" x2="7" y2="12"></line>
                        <line x1="17.01" y1="12" x2="22.96" y2="12"></line>
                    </svg>
                    <p>No impact analyses found</p>
                    <span class="hint">Commit changes will trigger automatic analysis</span>
                </div>
            `;
            return;
        }

        commitList.innerHTML = items.map((p, index) => `
            <div class="commit-item" data-index="${index}" data-id="${p.id}">
                <div class="risk-badge ${getRiskClass(p.risk_level)}">
                    ${Math.round(p.risk_score || 0)}
                </div>
                <div class="commit-info">
                    <div class="commit-sha">${p.commit_sha.substring(0, 7)}</div>
                    <div class="commit-meta">
                        <span>${p.files_changed || 0} files</span>
                        <span>${p.lines_changed || 0} lines</span>
                        <span>${formatRelativeTime(p.created_at)}</span>
                    </div>
                </div>
                <span class="risk-level-tag ${getRiskClass(p.risk_level)}">${p.risk_level || 'NONE'}</span>
            </div>
        `).join('');

        // Add click listeners
        commitList.querySelectorAll('.commit-item').forEach(item => {
            item.addEventListener('click', () => {
                commitList.querySelectorAll('.commit-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');

                const id = parseInt(item.dataset.id);
                loadPredictionDetails(id);
            });
        });
    }

    // ==================== FILTER ====================
    function filterCommitList() {
        const searchTerm = searchInput?.value.toLowerCase() || '';
        const filterValue = filterSelect?.value || 'all';

        const filtered = predictions.filter(p => {
            const matchesSearch = p.commit_sha.toLowerCase().includes(searchTerm) ||
                (p.module_name && p.module_name.toLowerCase().includes(searchTerm)) ||
                (p.change_type && p.change_type.toLowerCase().includes(searchTerm));
            const matchesFilter = filterValue === 'all' || p.risk_level === filterValue;
            return matchesSearch && matchesFilter;
        });

        renderCommitList(filtered);
    }

    // ==================== LOAD PREDICTION DETAILS ====================
    async function loadPredictionDetails(predictionId) {
        try {
            const response = await window.ETTA_API.authFetch(getApiUrl(`/api/impact-analysis/prediction/${predictionId}`));

            if (!response.ok) {
                throw new Error('Failed to load prediction details');
            }

            const data = await response.json();
            selectedPrediction = data;
            renderDetails(data);

        } catch (error) {
            console.error('Error loading prediction details:', error);
        }
    }

    // ==================== RENDER DETAILS ====================
    function renderDetails(prediction) {
        if (!detailsContent || !prediction) return;

        const riskClass = getRiskClass(prediction.prediction?.risk_level);
        const inputFeatures = prediction.input_features || {};
        const pred = prediction.prediction || {};

        detailsContent.innerHTML = `
            <div class="details-header">
                <div class="details-title">
                    <h3>${prediction.commit_sha.substring(0, 10)}...</h3>
                    <span class="branch">${prediction.branch || 'Unknown branch'}</span>
                </div>
                <div class="risk-display">
                    <div class="risk-circle ${riskClass}">
                        ${Math.round(pred.risk_score || 0)}
                    </div>
                    <span class="risk-level-tag ${riskClass}">${pred.risk_level || 'NONE'}</span>
                </div>
            </div>
            
            <div class="features-grid">
                <div class="feature-item">
                    <span class="feature-label">Lines Changed</span>
                    <span class="feature-value">${inputFeatures.lines_changed || 0}</span>
                </div>
                <div class="feature-item">
                    <span class="feature-label">Files Changed</span>
                    <span class="feature-value">${inputFeatures.files_changed || 0}</span>
                </div>
                <div class="feature-item">
                    <span class="feature-label">Change Type</span>
                    <span class="feature-value">${inputFeatures.change_type || 'N/A'}</span>
                </div>
                <div class="feature-item">
                    <span class="feature-label">Component Type</span>
                    <span class="feature-value">${inputFeatures.component_type || 'N/A'}</span>
                </div>
                <div class="feature-item">
                    <span class="feature-label">Module</span>
                    <span class="feature-value">${inputFeatures.module_name || 'N/A'}</span>
                </div>
                <div class="feature-item">
                    <span class="feature-label">Function Category</span>
                    <span class="feature-value">${inputFeatures.function_category || 'N/A'}</span>
                </div>
                <div class="feature-item">
                    <span class="feature-label">Test Coverage</span>
                    <span class="feature-value">${inputFeatures.test_coverage_level || 'N/A'}</span>
                </div>
                <div class="feature-item">
                    <span class="feature-label">Shared Component</span>
                    <span class="feature-value">${inputFeatures.shared_component ? 'Yes' : 'No'}</span>
                </div>
            </div>
            
            <div class="prediction-section">
                <h4>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
                        <polyline points="2 17 12 22 22 17"></polyline>
                        <polyline points="2 12 12 17 22 12"></polyline>
                    </svg>
                    ML Prediction
                </h4>
                <div class="prediction-grid">
                    <div class="prediction-item">
                        <span class="label">Failure Predicted</span>
                        <span class="value">${pred.failure_occurred ? 'Yes' : 'No'}</span>
                    </div>
                    <div class="prediction-item">
                        <span class="label">Failure Severity</span>
                        <span class="value">${pred.failure_severity || 'none'}</span>
                    </div>
                    <div class="prediction-item">
                        <span class="label">Risk Score</span>
                        <span class="value">${Math.round(pred.risk_score || 0)}%</span>
                    </div>
                    <div class="prediction-item">
                        <span class="label">Risk Level</span>
                        <span class="value">${pred.risk_level || 'NONE'}</span>
                    </div>
                </div>
            </div>
            
            <div class="details-meta">
                <span>Analyzed: ${formatRelativeTime(prediction.created_at)}</span>
            </div>
        `;
    }

    // ==================== UTILITIES ====================
    function getRiskClass(riskLevel) {
        if (!riskLevel) return 'none';
        return riskLevel.toLowerCase();
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

    // ==================== INITIAL UI STATE ====================
    // Hide main panels, show empty state if no repo selected
    if (!selectedRepo) {
        if (statsPanel) statsPanel.style.display = 'none';
        if (commitPanel) commitPanel.style.display = 'none';
        if (emptyStatePanel) emptyStatePanel.classList.remove('hidden');
    } else {
        if (emptyStatePanel) emptyStatePanel.classList.add('hidden');
    }
});
