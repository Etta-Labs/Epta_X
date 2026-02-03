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
        console.log('Token stored successfully');
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
 * Get fetch options with auth header
 */
function getAuthHeaders() {
    const headers = {
        'Content-Type': 'application/json'
    };
    const token = getAuthToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    return headers;
}

/**
 * Make an authenticated fetch request
 * This should be used for ALL API calls
 */
async function authFetch(url, options = {}) {
    const headers = {
        ...getAuthHeaders(),
        ...options.headers
    };
    
    const fetchOptions = {
        ...options,
        headers,
        credentials: 'include'  // Also include cookies as fallback
    };
    
    return fetch(url, fetchOptions);
}

/**
 * Make an API request to the backend server
 * @param {string} endpoint - The API endpoint (e.g., '/api/setup/status')
 * @param {object} options - Fetch options (method, headers, body, etc.)
 * @returns {Promise<Response>} - The fetch response
 */
async function apiRequest(endpoint, options = {}) {
    const url = `${API_BASE_URL}${endpoint}`;
    return authFetch(url, options);
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
    clearToken: clearAuthToken,
    getAuthHeaders: getAuthHeaders,
    authFetch: authFetch
};

console.log('ETTA-X API configured:', API_BASE_URL);
console.log('Auth token present:', !!getAuthToken());

