/**
 * ETTA-X Impact Analysis Page
 * JavaScript for ML-powered risk prediction
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

    // ==================== DOM ELEMENTS ====================
    const repoSelector = document.getElementById('repo-selector');
    const refreshBtn = document.getElementById('refresh-btn');
    const searchInput = document.getElementById('search-input');
    const filterSelect = document.getElementById('filter-select');
    const commitList = document.getElementById('commit-list');
    const detailsContent = document.getElementById('details-content');

    // Stats elements
    const statTotal = document.getElementById('stat-total');
    const statHigh = document.getElementById('stat-high');
    const statMedium = document.getElementById('stat-medium');
    const statLow = document.getElementById('stat-low');

    // ==================== INITIALIZATION ====================
    console.log('[Impact Analysis] Initializing...');
    loadRepositories();
    initEventListeners();

    // Check for URL parameter to auto-select repository
    const urlParams = new URLSearchParams(window.location.search);
    const repoParam = urlParams.get('repo');
    if (repoParam) {
        console.log('[Impact Analysis] Found repo in URL:', repoParam);
        selectedRepo = repoParam;
    }

    // ==================== EVENT LISTENERS ====================
    function initEventListeners() {
        repoSelector?.addEventListener('change', () => {
            const fullName = repoSelector.value;
            if (fullName) {
                selectedRepo = fullName;
                loadImpactData(fullName);
            }
        });

        refreshBtn?.addEventListener('click', () => {
            if (selectedRepo) {
                loadImpactData(selectedRepo);
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
                return;
            }

            const data = await response.json();
            repositories = data.repositories || [];
            console.log('[Impact Analysis] Loaded', repositories.length, 'repositories');
            renderRepoSelector();

        } catch (error) {
            console.error('[Impact Analysis] Error loading repositories:', error);
        }
    }

    function renderRepoSelector() {
        if (!repoSelector) return;

        repoSelector.innerHTML = '<option value="">Select Repository...</option>';

        repositories.forEach(repo => {
            const option = document.createElement('option');
            option.value = repo.full_name;
            option.textContent = repo.full_name;
            repoSelector.appendChild(option);
        });

        // Auto-select from URL parameter or first repository
        if (selectedRepo) {
            repoSelector.value = selectedRepo;
            console.log('[Impact Analysis] Auto-selected repo from URL:', selectedRepo);
            loadImpactData(selectedRepo);
        } else if (repositories.length > 0) {
            // Auto-select first repository if none specified
            selectedRepo = repositories[0].full_name;
            repoSelector.value = selectedRepo;
            console.log('[Impact Analysis] Auto-selected first repo:', selectedRepo);
            loadImpactData(selectedRepo);
        }
    }

    // ==================== LOAD IMPACT DATA ====================
    async function loadImpactData(fullName) {
        try {
            // Show loading state
            if (commitList) {
                commitList.innerHTML = `
                    <div class="impact-empty-state">
                        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="loading-spinner">
                            <circle cx="12" cy="12" r="10"></circle>
                        </svg>
                        <p>Loading impact analyses...</p>
                    </div>
                `;
            }

            // Load stats and history in parallel
            const [statsRes, historyRes] = await Promise.all([
                window.ETTA_API.authFetch(getApiUrl(`/api/impact-analysis/stats/${encodeURIComponent(fullName)}`)),
                window.ETTA_API.authFetch(getApiUrl(`/api/impact-analysis/history/${encodeURIComponent(fullName)}`))
            ]);

            if (statsRes.ok) {
                const statsData = await statsRes.json();
                renderStats(statsData.stats);
            }

            if (historyRes.ok) {
                const historyData = await historyRes.json();
                predictions = historyData.predictions || [];
                renderCommitList(predictions);
            }

        } catch (error) {
            console.error('Error loading impact data:', error);
            if (commitList) {
                commitList.innerHTML = `
                    <div class="impact-empty-state">
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
                <div class="impact-empty-state">
                    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                        <line x1="12" y1="9" x2="12" y2="13"></line>
                        <line x1="12" y1="17" x2="12.01" y2="17"></line>
                    </svg>
                    <p>No impact analyses found</p>
                    <span class="hint">Commit changes will trigger automatic analysis</span>
                </div>
            `;
            return;
        }

        commitList.innerHTML = items.map((p, index) => `
            <div class="impact-commit-item" data-index="${index}" data-id="${p.id}">
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
        commitList.querySelectorAll('.impact-commit-item').forEach(item => {
            item.addEventListener('click', () => {
                commitList.querySelectorAll('.impact-commit-item').forEach(i => i.classList.remove('active'));
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
            <div class="impact-details-content">
                <div class="impact-details-header">
                    <div class="impact-details-title">
                        <h3>${prediction.commit_sha.substring(0, 10)}...</h3>
                        <span class="branch">${prediction.branch || 'Unknown branch'}</span>
                    </div>
                    <div class="impact-risk-display">
                        <div class="impact-risk-circle ${riskClass}">
                            ${Math.round(pred.risk_score || 0)}
                        </div>
                        <span class="risk-level-tag ${riskClass}">${pred.risk_level || 'NONE'}</span>
                    </div>
                </div>
                
                <div class="impact-features">
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
                
                <div class="impact-prediction">
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
                
                <div class="impact-meta" style="margin-top: 16px; font-size: 12px; color: #6b7280;">
                    <span>Analyzed: ${formatRelativeTime(prediction.created_at)}</span>
                </div>
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
});
