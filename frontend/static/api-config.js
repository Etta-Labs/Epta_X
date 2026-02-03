/**
 * ETTA-X API Configuration
 * This module provides the API base URL for all frontend requests.
 * The frontend runs locally in Electron, but API calls go to the remote server.
 * 
 * Authentication: Uses localStorage token with Authorization header
 * (cookies don't work across file:// to https:// origins)
 */

// API Base URL - Configure this to point to your backend server
const API_BASE_URL = 'https://etta.gowshik.online';

// Token storage key
const TOKEN_KEY = 'ettax_auth_token';

/**
 * Get stored auth token
 */
function getAuthToken() {
    return localStorage.getItem(TOKEN_KEY);
}

/**
 * Set auth token
 */
function setAuthToken(token) {
    if (token) {
        localStorage.setItem(TOKEN_KEY, token);
    } else {
        localStorage.removeItem(TOKEN_KEY);
    }
}

/**
 * Clear auth token (logout)
 */
function clearAuthToken() {
    localStorage.removeItem(TOKEN_KEY);
}

/**
 * Make an API request to the backend server
 * @param {string} endpoint - The API endpoint (e.g., '/api/setup/status')
 * @param {object} options - Fetch options (method, headers, body, etc.)
 * @returns {Promise<Response>} - The fetch response
 */
async function apiRequest(endpoint, options = {}) {
    const url = `${API_BASE_URL}${endpoint}`;
    
    // Build headers with auth token if available
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };
    
    const token = getAuthToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    
    const mergedOptions = { 
        ...options,
        headers,
        credentials: 'include'  // Still include for cookie fallback
    };
    
    try {
        const response = await fetch(url, mergedOptions);
        return response;
    } catch (error) {
        console.error(`API request failed: ${endpoint}`, error);
        throw error;
    }
}

/**
 * GET request helper
 */
async function apiGet(endpoint, options = {}) {
    return apiRequest(endpoint, { ...options, method: 'GET' });
}

/**
 * POST request helper
 */
async function apiPost(endpoint, body, options = {}) {
    return apiRequest(endpoint, {
        ...options,
        method: 'POST',
        body: JSON.stringify(body)
    });
}

/**
 * Get the full URL for an API endpoint
 */
function getApiUrl(endpoint) {
    return `${API_BASE_URL}${endpoint}`;
}

// Export for use in other scripts
window.ETTA_API = {
    baseUrl: API_BASE_URL,
    request: apiRequest,
    get: apiGet,
    post: apiPost,
    getUrl: getApiUrl,
    getToken: getAuthToken,
    setToken: setAuthToken,
    clearToken: clearAuthToken
};

console.log('ETTA-X API configured:', API_BASE_URL);

