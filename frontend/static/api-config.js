/**
 * ETTA-X API Configuration
 * This module provides the API base URL for all frontend requests.
 * The frontend runs locally in Electron, but API calls go to the remote server.
 */

// API Base URL - Configure this to point to your backend server
const API_BASE_URL = 'https://etta.gowshik.online';

/**
 * Make an API request to the backend server
 * @param {string} endpoint - The API endpoint (e.g., '/api/setup/status')
 * @param {object} options - Fetch options (method, headers, body, etc.)
 * @returns {Promise<Response>} - The fetch response
 */
async function apiRequest(endpoint, options = {}) {
    const url = `${API_BASE_URL}${endpoint}`;
    
    // Default options
    const defaultOptions = {
        credentials: 'include',  // Include cookies for auth
        headers: {
            'Content-Type': 'application/json',
            ...options.headers
        }
    };
    
    const mergedOptions = { ...defaultOptions, ...options };
    
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
    getUrl: getApiUrl
};

console.log('ETTA-X API configured:', API_BASE_URL);
