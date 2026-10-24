const defaultBaseUrl = process.env.NODE_ENV === 'production'
    ? 'https://bidsagent-bnhkcvdygsbzardc.centralindia-01.azurewebsites.net'
    : 'http://localhost:8000';

const baseUrl = (
    process.env.REACT_APP_API_BASE_URL ||
    (process.env.NODE_ENV !== 'production' && process.env.REACT_APP_API_URL) ||
    defaultBaseUrl
).replace(/\/+$/, '');

export const API = baseUrl.endsWith('/api') ? baseUrl : `${baseUrl}/api`;

export const signalDashboardRefresh = () =>
    window.dispatchEvent(new Event('dashboard:refresh'));

/** Return headers that identify the current user for activity logging. */
export const userHeaders = () => {
    try {
        const stored = localStorage.getItem('deal_user');
        if (stored) {
            const u = JSON.parse(stored);
            return {
                'X-Username':  u.username || u.name || '',
                'X-User-Role': u.role     || '',
            };
        }
    } catch {}
    return {};
};
