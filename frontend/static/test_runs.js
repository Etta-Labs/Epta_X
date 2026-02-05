/**
 * ETTA-X Test Runs Page JavaScript
 * Handles test generation, prioritization, and execution display
 */

// Global state
let generatedTests = [];
let selectedTest = null;
let testRuns = [];
let llmStatus = { loaded: false, using_gpu: false };

// DOM Elements
const testsList = document.getElementById('tests-list');
const loadingState = document.getElementById('loading-state');
const emptyState = document.getElementById('empty-state');
const detailPlaceholder = document.getElementById('detail-placeholder');
const detailContent = document.getElementById('test-detail-content');
const generateModal = document.getElementById('generate-modal');
const llmStatusEl = document.getElementById('llm-status');

// Stats elements
const statTotal = document.getElementById('stat-total');
const statPassed = document.getElementById('stat-passed');
const statFailed = document.getElementById('stat-failed');
const statCoverage = document.getElementById('stat-coverage');

// ==================== INITIALIZATION ====================

document.addEventListener('DOMContentLoaded', () => {
    initializePage();
    setupEventListeners();
    loadTestRuns();
    checkLLMStatus();
});

function initializePage() {
    // Check authentication
    checkAuth();
    
    // Setup risk score slider
    const riskSlider = document.getElementById('risk-score');
    const riskValue = document.getElementById('risk-score-value');
    if (riskSlider && riskValue) {
        riskSlider.addEventListener('input', () => {
            riskValue.textContent = `${riskSlider.value}%`;
        });
    }
}

function setupEventListeners() {
    // Generate button
    document.getElementById('generate-btn')?.addEventListener('click', openGenerateModal);
    
    // Refresh button
    document.getElementById('refresh-btn')?.addEventListener('click', loadTestRuns);
    
    // Filter changes
    document.getElementById('filter-priority')?.addEventListener('change', filterTests);
    document.getElementById('filter-status')?.addEventListener('change', filterTests);
    
    // Profile dropdown
    setupProfileDropdown();
    
    // Settings dropdown
    setupSettingsDropdown();
    
    // Theme toggle
    document.getElementById('theme-toggle')?.addEventListener('click', toggleTheme);
}

// ==================== AUTHENTICATION ====================

async function checkAuth() {
    try {
        const response = await fetch('/auth/github/user');
        if (response.ok) {
            const user = await response.json();
            updateProfileUI(user);
        } else {
            showLoggedOutState();
        }
    } catch (error) {
        console.error('Auth check failed:', error);
        showLoggedOutState();
    }
}

function updateProfileUI(user) {
    const loggedInView = document.getElementById('logged-in-view');
    const loggedOutView = document.getElementById('logged-out-view');
    const profileAvatar = document.getElementById('profile-avatar');
    const profileName = document.getElementById('profile-name');
    const profileUsername = document.getElementById('profile-username');
    const profileToggle = document.getElementById('profile-toggle');
    
    if (loggedInView) loggedInView.style.display = 'block';
    if (loggedOutView) loggedOutView.style.display = 'none';
    
    if (user.avatar_url) {
        if (profileAvatar) profileAvatar.src = user.avatar_url;
        if (profileToggle) profileToggle.src = user.avatar_url;
    }
    if (profileName) profileName.textContent = user.name || user.login;
    if (profileUsername) profileUsername.textContent = `@${user.login}`;
}

function showLoggedOutState() {
    const loggedInView = document.getElementById('logged-in-view');
    const loggedOutView = document.getElementById('logged-out-view');
    
    if (loggedInView) loggedInView.style.display = 'none';
    if (loggedOutView) loggedOutView.style.display = 'block';
}

function setupProfileDropdown() {
    const profileToggle = document.getElementById('profile-toggle');
    const profileDropdown = document.getElementById('profile-dropdown');
    
    if (profileToggle && profileDropdown) {
        profileToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            profileDropdown.style.display = 
                profileDropdown.style.display === 'none' ? 'block' : 'none';
        });
        
        document.addEventListener('click', () => {
            profileDropdown.style.display = 'none';
        });
    }
    
    // Login button in dropdown
    document.getElementById('dropdown-login-btn')?.addEventListener('click', (e) => {
        e.preventDefault();
        window.location.href = '/auth/github/login';
    });
}

function setupSettingsDropdown() {
    const settingsToggle = document.getElementById('settings-toggle');
    const settingsDropdown = document.getElementById('settings-dropdown');
    
    if (settingsToggle && settingsDropdown) {
        settingsToggle.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            settingsDropdown.classList.toggle('show');
        });
    }
}

// ==================== THEME ====================

function toggleTheme() {
    document.body.classList.toggle('dark-theme');
    const isDark = document.body.classList.contains('dark-theme');
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
    
    // Update logo
    const logoImg = document.getElementById('logo-img');
    if (logoImg) {
        logoImg.src = isDark ? '/static/assets/logo_bg_wh.png' : '/static/assets/logo_bg_bl.png';
    }
}

// ==================== LLM STATUS ====================

async function checkLLMStatus() {
    try {
        const response = await fetch('/api/tests/status');
        if (response.ok) {
            const data = await response.json();
            llmStatus = data.llm_status || {};
            updateLLMStatusUI(data);
        }
    } catch (error) {
        console.error('LLM status check failed:', error);
        updateLLMStatusUI({ pipeline_status: 'error' });
    }
}

function updateLLMStatusUI(data) {
    if (!llmStatusEl) return;
    
    const statusDot = llmStatusEl.querySelector('.status-dot');
    const statusText = llmStatusEl.querySelector('.status-text');
    
    llmStatusEl.className = 'llm-status';
    
    if (data.pipeline_status === 'ready') {
        if (data.llm_status?.is_loaded) {
            llmStatusEl.classList.add('ready');
            statusText.textContent = data.llm_status.using_gpu ? 'GPU Ready' : 'CPU Ready';
        } else {
            statusText.textContent = 'Model Available';
        }
    } else if (data.pipeline_status === 'error' || data.llm_status?.error) {
        llmStatusEl.classList.add('error');
        statusText.textContent = 'Model Error';
    } else {
        statusText.textContent = 'Checking...';
    }
}

// ==================== TEST RUNS ====================

async function loadTestRuns() {
    showLoading(true);
    
    try {
        // Load test execution runs
        const runsResponse = await fetch('/api/tests/runs');
        if (runsResponse.ok) {
            const data = await runsResponse.json();
            testRuns = data.runs || [];
        }
        
        // Load generated tests from webhook events
        await loadGeneratedTests();
        
        updateStats();
    } catch (error) {
        console.error('Failed to load test runs:', error);
    }
    
    showLoading(false);
    renderTestsList();
}

async function loadGeneratedTests() {
    try {
        const response = await fetch('/api/tests/generated');
        if (response.ok) {
            const data = await response.json();
            generatedTests = data.tests || [];
            console.log(`Loaded ${generatedTests.length} generated tests from pipeline`);
        }
    } catch (error) {
        console.error('Failed to load generated tests:', error);
    }
}

async function loadCachedTests() {
    try {
        const response = await fetch('/api/tests/cache');
        if (response.ok) {
            const data = await response.json();
            
            // Get the latest cached tests
            if (data.entries && data.entries.length > 0) {
                const latestKey = data.entries[data.entries.length - 1].key;
                const cacheResponse = await fetch(`/api/tests/cache/${latestKey}`);
                if (cacheResponse.ok) {
                    const cacheData = await cacheResponse.json();
                    const cachedTests = cacheData.prioritized?.all_tests || [];
                    // Merge with existing if any
                    if (cachedTests.length > 0 && generatedTests.length === 0) {
                        generatedTests = cachedTests;
                    }
                }
            }
        }
    } catch (error) {
        console.error('Failed to load cached tests:', error);
    }
}

function updateStats() {
    let total = 0, passed = 0, failed = 0;
    let coverageSum = 0, coverageCount = 0;
    
    testRuns.forEach(run => {
        total += run.total_tests || 0;
        passed += run.passed || 0;
        failed += run.failed || 0;
        if (run.coverage !== null && run.coverage !== undefined) {
            coverageSum += run.coverage;
            coverageCount++;
        }
    });
    
    // Also count generated tests if no runs
    if (total === 0) {
        total = generatedTests.length;
    }
    
    statTotal.textContent = total;
    statPassed.textContent = passed;
    statFailed.textContent = failed;
    statCoverage.textContent = coverageCount > 0 
        ? `${Math.round(coverageSum / coverageCount)}%` 
        : '--%';
}

function showLoading(show) {
    if (loadingState) loadingState.style.display = show ? 'flex' : 'none';
    if (emptyState) emptyState.style.display = 'none';
}

// ==================== TEST LIST RENDERING ====================

function renderTestsList() {
    if (!testsList) return;
    
    // Clear existing items (keep loading/empty states)
    const items = testsList.querySelectorAll('.test-item');
    items.forEach(item => item.remove());
    
    if (generatedTests.length === 0) {
        emptyState.style.display = 'flex';
        return;
    }
    
    emptyState.style.display = 'none';
    
    // Apply filters
    const filteredTests = getFilteredTests();
    
    filteredTests.forEach((test, index) => {
        const item = createTestItem(test, index);
        testsList.appendChild(item);
    });
}

function getFilteredTests() {
    const priorityFilter = document.getElementById('filter-priority')?.value || 'all';
    const statusFilter = document.getElementById('filter-status')?.value || 'all';
    
    return generatedTests.filter(test => {
        // Priority filter
        if (priorityFilter !== 'all') {
            const score = test.priority_score || 0;
            if (priorityFilter === 'high' && score < 0.7) return false;
            if (priorityFilter === 'medium' && (score < 0.4 || score >= 0.7)) return false;
            if (priorityFilter === 'low' && score >= 0.4) return false;
        }
        
        // Status filter
        if (statusFilter !== 'all') {
            const status = test.status || 'pending';
            if (status !== statusFilter) return false;
        }
        
        return true;
    });
}

function filterTests() {
    renderTestsList();
}

function createTestItem(test, index) {
    const item = document.createElement('div');
    item.className = `test-item ${test.status || 'pending'}`;
    item.onclick = () => selectTest(test, index);
    
    const priorityScore = test.priority_score || 0;
    const priorityLevel = priorityScore >= 0.7 ? 'high' : priorityScore >= 0.4 ? 'medium' : 'low';
    
    item.innerHTML = `
        <div class="test-status-icon ${test.status || 'pending'}">
            ${getStatusIcon(test.status || 'pending')}
        </div>
        <div class="test-item-info">
            <div class="test-item-name">${escapeHtml(test.name)}</div>
            <div class="test-item-meta">
                <span class="test-item-method ${test.method}">${test.method}</span>
                <span>${test.endpoint}</span>
                <div class="test-item-priority">
                    <div class="priority-bar-mini">
                        <div class="priority-bar-mini-fill ${priorityLevel}" 
                             style="width: ${priorityScore * 100}%"></div>
                    </div>
                    <span>${Math.round(priorityScore * 100)}%</span>
                </div>
            </div>
        </div>
    `;
    
    return item;
}

function getStatusIcon(status) {
    switch (status) {
        case 'passed':
            return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>';
        case 'failed':
            return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
        default:
            return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>';
    }
}

// ==================== TEST DETAIL ====================

function selectTest(test, index) {
    selectedTest = test;
    
    // Update selection in list
    document.querySelectorAll('.test-item').forEach((item, i) => {
        item.classList.toggle('selected', i === index);
    });
    
    // Show detail content
    detailPlaceholder.style.display = 'none';
    detailContent.style.display = 'block';
    
    // Populate details
    updateTestDetail(test);
}

function updateTestDetail(test) {
    // Status badge
    const statusBadge = document.getElementById('detail-status-badge');
    statusBadge.className = `test-status-badge ${test.status || 'pending'}`;
    statusBadge.querySelector('.status-text').textContent = 
        (test.status || 'pending').charAt(0).toUpperCase() + (test.status || 'pending').slice(1);
    
    // Basic info
    document.getElementById('detail-test-name').textContent = test.name;
    document.getElementById('detail-description').textContent = test.description || 'No description';
    
    // Priority
    const priorityScore = test.priority_score || 0;
    document.getElementById('detail-priority-fill').style.width = `${priorityScore * 100}%`;
    document.getElementById('detail-priority-value').textContent = `${Math.round(priorityScore * 100)}%`;
    
    // Priority factors
    const factorsEl = document.getElementById('detail-priority-factors');
    factorsEl.innerHTML = '';
    
    const factors = [];
    if (test.category === 'authentication') factors.push('Auth Test');
    if (test.category === 'security') factors.push('Security');
    if (test.expected_status >= 400) factors.push('Error Case');
    if (test.method === 'POST' || test.method === 'PUT') factors.push('Write Op');
    if (test.is_important) factors.push('High Priority');
    
    factors.forEach(factor => {
        const span = document.createElement('span');
        span.className = 'priority-factor';
        span.textContent = factor;
        factorsEl.appendChild(span);
    });
    
    // Test config
    document.getElementById('detail-endpoint').textContent = test.endpoint;
    
    const methodEl = document.getElementById('detail-method');
    methodEl.textContent = test.method;
    methodEl.className = `info-value method-badge ${test.method}`;
    
    document.getElementById('detail-expected-status').textContent = test.expected_status;
    document.getElementById('detail-category').textContent = test.category || 'functional';
    
    // Payload
    document.getElementById('detail-payload').textContent = 
        JSON.stringify(test.payload || {}, null, 2);
    
    // Result section
    const resultSection = document.getElementById('result-section');
    if (test.result) {
        resultSection.style.display = 'block';
        // Populate results...
    } else {
        resultSection.style.display = 'none';
    }
}

// ==================== GENERATE TESTS ====================

function openGenerateModal() {
    generateModal.style.display = 'flex';
}

function closeGenerateModal() {
    generateModal.style.display = 'none';
}

async function generateTests() {
    const description = document.getElementById('code-description').value.trim();
    const riskScore = parseInt(document.getElementById('risk-score').value) / 100;
    const filesChanged = parseInt(document.getElementById('files-changed').value) || 1;
    const criticalModule = document.getElementById('critical-module').checked;
    
    if (!description) {
        alert('Please enter a code/API description');
        return;
    }
    
    // Show loading
    document.getElementById('generate-loading').style.display = 'flex';
    document.getElementById('btn-generate-submit').disabled = true;
    
    try {
        const response = await fetch('/api/tests/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                code_description: description,
                language: 'python',
                change_risk_score: riskScore,
                files_changed: filesChanged,
                critical_module: criticalModule
            })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Generation failed');
        }
        
        const data = await response.json();
        
        if (data.success) {
            generatedTests = data.all_tests || [];
            updateStats();
            renderTestsList();
            closeGenerateModal();
            
            // Show success message
            console.log(`Generated ${data.generation.test_count} tests in ${data.generation.generation_time_ms}ms`);
        } else {
            throw new Error('Generation failed');
        }
        
    } catch (error) {
        console.error('Test generation failed:', error);
        alert(`Failed to generate tests: ${error.message}`);
    } finally {
        document.getElementById('generate-loading').style.display = 'none';
        document.getElementById('btn-generate-submit').disabled = false;
    }
}

// ==================== RUN TESTS ====================

async function runSelectedTest() {
    if (!selectedTest) return;
    
    const btnRun = document.getElementById('btn-run-test');
    btnRun.disabled = true;
    btnRun.innerHTML = '<div class="spinner" style="width:16px;height:16px;border-width:2px;"></div> Running...';
    
    try {
        // First, generate the pytest file
        const cacheResponse = await fetch('/api/tests/cache');
        const cacheData = await cacheResponse.json();
        
        if (!cacheData.entries || cacheData.entries.length === 0) {
            throw new Error('No tests cached. Generate tests first.');
        }
        
        const cacheKey = cacheData.entries[cacheData.entries.length - 1].key;
        
        // Generate file
        const fileResponse = await fetch(`/api/tests/generate-file?cache_key=${cacheKey}`, {
            method: 'POST'
        });
        
        if (!fileResponse.ok) {
            throw new Error('Failed to generate test file');
        }
        
        const fileData = await fileResponse.json();
        
        // Execute tests
        const execResponse = await fetch('/api/tests/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                test_file: fileData.files.test_file,
                coverage: true,
                verbose: true
            })
        });
        
        if (!execResponse.ok) {
            throw new Error('Failed to start test execution');
        }
        
        const execData = await execResponse.json();
        
        // Poll for results
        pollTestRun(execData.run_id);
        
    } catch (error) {
        console.error('Test execution failed:', error);
        alert(`Failed to run test: ${error.message}`);
        btnRun.disabled = false;
        btnRun.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> Run Test';
    }
}

async function pollTestRun(runId) {
    const btnRun = document.getElementById('btn-run-test');
    
    const poll = async () => {
        try {
            const response = await fetch(`/api/tests/runs/${runId}`);
            if (!response.ok) return;
            
            const run = await response.json();
            
            if (run.status === 'completed' || run.status === 'failed') {
                // Update UI with results
                if (selectedTest) {
                    selectedTest.status = run.failed > 0 ? 'failed' : 'passed';
                    selectedTest.result = run;
                    updateTestDetail(selectedTest);
                    renderTestsList();
                }
                
                btnRun.disabled = false;
                btnRun.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> Run Test';
                
                // Reload runs
                loadTestRuns();
            } else {
                // Continue polling
                setTimeout(poll, 1000);
            }
        } catch (error) {
            console.error('Polling failed:', error);
            btnRun.disabled = false;
            btnRun.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> Run Test';
        }
    };
    
    poll();
}

function viewTestCode() {
    // This could open a modal with the generated pytest code
    alert('View Code functionality - would show generated pytest code');
}

// ==================== UTILITIES ====================

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Close modal on outside click
generateModal?.addEventListener('click', (e) => {
    if (e.target === generateModal) {
        closeGenerateModal();
    }
});

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeGenerateModal();
    }
});
