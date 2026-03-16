/* ============================================
   OCTOS AUTH MANAGER
   Handles JWT token storage, refresh, and logout
   ============================================ */

const Auth = {
  TOKEN_KEY: 'octos_access',
  REFRESH_KEY: 'octos_refresh',
  USER_KEY: 'octos_user',

  // Store tokens after login
  setTokens(access, refresh) {
    localStorage.setItem(this.TOKEN_KEY, access);
    localStorage.setItem(this.REFRESH_KEY, refresh);
  },

  // Get access token
  getToken() {
    return localStorage.getItem(this.TOKEN_KEY);
  },

  // Get refresh token
  getRefreshToken() {
    return localStorage.getItem(this.REFRESH_KEY);
  },

  // Store user profile
  setUser(user) {
    localStorage.setItem(this.USER_KEY, JSON.stringify(user));
  },

  // Get stored user
  getUser() {
    const u = localStorage.getItem(this.USER_KEY);
    return u ? JSON.parse(u) : null;
  },

  // Check if logged in
  isAuthenticated() {
    return !!this.getToken();
  },

  // Clear everything and redirect to login
  logout() {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.REFRESH_KEY);
    localStorage.removeItem(this.USER_KEY);
    window.location.href = '/portal/login/';
  },

  // Refresh access token using refresh token
  async refresh() {
    const refreshToken = this.getRefreshToken();
    if (!refreshToken) {
      this.logout();
      return null;
    }
    try {
      const res = await fetch('/api/v1/auth/token/refresh/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh: refreshToken })
      });
      if (!res.ok) {
        this.logout();
        return null;
      }
      const data = await res.json();
      localStorage.setItem(this.TOKEN_KEY, data.access);
      return data.access;
    } catch {
      this.logout();
      return null;
    }
  },

  // Authenticated fetch — auto refreshes on 401
  async fetch(url, options = {}) {
    const token = this.getToken();
    if (!token) {
      this.logout();
      return null;
    }

    const headers = {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
      ...(options.headers || {})
    };

    let res = await fetch(url, { ...options, headers });

    // Try refresh on 401
    if (res.status === 401) {
      const newToken = await this.refresh();
      if (!newToken) return null;
      headers['Authorization'] = `Bearer ${newToken}`;
      res = await fetch(url, { ...options, headers });
    }

    return res;
  },

  // Guard — redirect to login if not authenticated
  guard() {
    if (!this.isAuthenticated()) {
      window.location.href = '/portal/login/';
    }
  },

  // Load and display user info in topbar
  async loadUserInfo() {
    let user = this.getUser();
    if (!user) {
      const res = await this.fetch('/api/v1/accounts/me/');
      if (!res) return;
      user = await res.json();
      this.setUser(user);
    }

    // Populate topbar
    const nameEl = document.getElementById('topbar-user-name');
    const roleEl = document.getElementById('topbar-user-role');
    const avatarEl = document.getElementById('topbar-avatar');
    const branchEl = document.getElementById('topbar-branch');

    if (nameEl) nameEl.textContent = user.full_name || user.email;
    if (roleEl) roleEl.textContent = user.role_detail?.name || '';
    if (avatarEl) avatarEl.textContent = (user.first_name?.[0] || '') + (user.last_name?.[0] || '');
    if (branchEl) branchEl.textContent = user.branch_name || '';
  }
};

// Expose globally
window.Auth = Auth;