/**
 * API Configuration
 * Automatically detects and provides the correct backend URL
 * - In Electron: Uses packaged .env configuration
 * - In Web: Uses config from app-config.json
 */

let cachedBackendUrl = null;

/**
 * Get the backend API URL
 * @returns {Promise<string>} The backend URL
 */
export async function getBackendUrl() {
    // Return cached value if available
    if (cachedBackendUrl) {
        return cachedBackendUrl;
    }

    try {
        // Check if running in Electron
        if (window.electronAPI && window.electronAPI.isElectron) {
            cachedBackendUrl = await window.electronAPI.getBackendUrl();
            console.log('Using Electron backend URL:', cachedBackendUrl);
            return cachedBackendUrl;
        }
    } catch (error) {
        console.warn('Failed to get backend URL from Electron:', error);
    }

    try {
        // Fallback to web config
        const response = await fetch('/config/app-config.json');
        const config = await response.json();
        cachedBackendUrl = config.api?.productionUrl || config.api?.backendUrl || 'https://etta.gowshik.in';
        console.log('Using web backend URL:', cachedBackendUrl);
        return cachedBackendUrl;
    } catch (error) {
        console.warn('Failed to load app-config.json:', error);
    }

    // Final fallback
    cachedBackendUrl = 'https://etta.gowshik.in';
    console.log('Using default backend URL:', cachedBackendUrl);
    return cachedBackendUrl;
}

/**
 * Make an API request to the backend
 * @param {string} endpoint - The API endpoint (e.g., '/api/repos')
 * @param {RequestInit} options - Fetch options
 * @returns {Promise<Response>} The fetch response
 */
export async function apiRequest(endpoint, options = {}) {
    const baseUrl = await getBackendUrl();
    const url = `${baseUrl}${endpoint}`;
    
    // Add credentials to support cookies
    const fetchOptions = {
        ...options,
        credentials: 'include',
        headers: {
            'Content-Type': 'application/json',
            ...options.headers,
        },
    };

    return fetch(url, fetchOptions);
}

/**
 * Reset cached backend URL (useful for testing or environment changes)
 */
export function resetBackendUrlCache() {
    cachedBackendUrl = null;
}
