import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'https://kover.laravas.com';

export const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add response interceptor to handle 401 errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const requestUrl = error.config?.url || '';
    const isAuthEndpoint = requestUrl.includes('/api/auth/login') || requestUrl.includes('/api/auth/register');

    // Only trigger forced logout on 401 for non-auth endpoints (i.e. expired/invalid token)
    if (error.response?.status === 401 && !isAuthEndpoint) {
      // Token expired or invalid - trigger logout
      localStorage.removeItem('token');
      delete api.defaults.headers.common['Authorization'];
      
      // Dispatch custom event to notify AuthContext
      window.dispatchEvent(new CustomEvent('auth:logout'));
      
      // Redirect to login if not already there
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default api;
