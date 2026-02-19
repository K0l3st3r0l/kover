import { createContext, useContext, useState, useEffect, ReactNode, useCallback, useRef } from 'react';
import api from '../services/api';

interface User {
  id: number;
  email: string;
  username: string;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, username: string, password: string) => Promise<void>;
  logout: () => void;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

// Inactivity timeout in milliseconds (30 minutes)
const INACTIVITY_TIMEOUT = 30 * 60 * 1000;

// Decode JWT token
function decodeToken(token: string): any {
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join('')
    );
    return JSON.parse(jsonPayload);
  } catch (error) {
    console.error('Error decoding token:', error);
    return null;
  }
}

// Check if token is expired
function isTokenExpired(token: string): boolean {
  try {
    const decoded = decodeToken(token);
    if (!decoded || !decoded.exp) return true;
    
    // Check if token expires in less than 1 minute
    const expirationTime = decoded.exp * 1000;
    const now = Date.now();
    return expirationTime < now + 60000;
  } catch (error) {
    return true;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const inactivityTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastActivityRef = useRef<number>(Date.now());

  const logout = useCallback(() => {
    setUser(null);
    setToken(null);
    localStorage.removeItem('token');
    delete api.defaults.headers.common['Authorization'];
    
    // Clear inactivity timer
    if (inactivityTimerRef.current) {
      clearTimeout(inactivityTimerRef.current);
      inactivityTimerRef.current = null;
    }
  }, []);

  // Reset inactivity timer
  const resetInactivityTimer = useCallback(() => {
    lastActivityRef.current = Date.now();
    
    if (inactivityTimerRef.current) {
      clearTimeout(inactivityTimerRef.current);
    }
    
    inactivityTimerRef.current = setTimeout(() => {
      console.log('Session expired due to inactivity');
      logout();
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }, INACTIVITY_TIMEOUT);
  }, [logout]);

  // Track user activity
  useEffect(() => {
    if (!token) return;

    const activityEvents = ['mousedown', 'keydown', 'scroll', 'touchstart', 'click'];
    
    const handleActivity = () => {
      resetInactivityTimer();
    };

    activityEvents.forEach(event => {
      document.addEventListener(event, handleActivity);
    });

    // Start the timer
    resetInactivityTimer();

    return () => {
      activityEvents.forEach(event => {
        document.removeEventListener(event, handleActivity);
      });
      if (inactivityTimerRef.current) {
        clearTimeout(inactivityTimerRef.current);
      }
    };
  }, [token, resetInactivityTimer]);

  // Check token expiration periodically
  useEffect(() => {
    if (!token) return;

    const checkTokenExpiration = () => {
      const storedToken = localStorage.getItem('token');
      if (storedToken && isTokenExpired(storedToken)) {
        console.log('Token expired, logging out');
        logout();
        if (window.location.pathname !== '/login') {
          window.location.href = '/login';
        }
      }
    };

    // Check immediately
    checkTokenExpiration();

    // Check every minute
    const intervalId = setInterval(checkTokenExpiration, 60000);

    return () => clearInterval(intervalId);
  }, [token, logout]);

  // Listen for logout events from interceptor
  useEffect(() => {
    const handleLogoutEvent = () => {
      logout();
    };

    window.addEventListener('auth:logout', handleLogoutEvent);
    return () => window.removeEventListener('auth:logout', handleLogoutEvent);
  }, [logout]);

  useEffect(() => {
    // Check for token in localStorage on mount
    const storedToken = localStorage.getItem('token');
    if (storedToken) {
      // Check if token is expired
      if (isTokenExpired(storedToken)) {
        console.log('Stored token is expired');
        logout();
        setIsLoading(false);
        return;
      }
      
      setToken(storedToken);
      api.defaults.headers.common['Authorization'] = `Bearer ${storedToken}`;
      fetchUser(storedToken);
    } else {
      setIsLoading(false);
    }
  }, []);

  const fetchUser = async (authToken: string) => {
    try {
      const response = await api.get('/api/auth/me', {
        headers: { Authorization: `Bearer ${authToken}` }
      });
      setUser(response.data);
    } catch (error) {
      console.error('Failed to fetch user:', error);
      logout();
    } finally {
      setIsLoading(false);
    }
  };

  const login = async (email: string, password: string) => {
    const response = await api.post('/api/auth/login', { email, password });
    const { access_token, user: userData } = response.data;
    
    setToken(access_token);
    setUser(userData);
    localStorage.setItem('token', access_token);
    api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;
  };

  const register = async (email: string, username: string, password: string) => {
    const response = await api.post('/api/auth/register', { email, username, password });
    const { access_token, user: userData } = response.data;
    
    setToken(access_token);
    setUser(userData);
    localStorage.setItem('token', access_token);
    api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;
  };

  return (
    <AuthContext.Provider value={{ user, token, login, register, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
