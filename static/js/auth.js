/* ============================================
   OCTOS AUTH MANAGER v2
   Handles JWT storage, refresh, role routing,
   page guards, and session expiry UX
   ============================================ */

const Auth = {
  TOKEN_KEY  : 'octos_access',
  REFRESH_KEY: 'octos_refresh',
  USER_KEY   : 'octos_user',
  USER_TS_KEY: 'octos_user_ts',
  USER_TTL_MS: 15 * 60 * 1000, // 15 minutes
  _guardRan  : false,

  // ── Token management ────────────────────────────────────
  setTokens(access, refresh) {
    localStorage.setItem(this.TOKEN_KEY,   access);
    localStorage.setItem(this.REFRESH_KEY, refresh);
  },

  getToken()        { return localStorage.getItem(this.TOKEN_KEY);   },
  getRefreshToken() { return localStorage.getItem(this.REFRESH_KEY); },

  // ── User cache ───────────────────────────────────────────
  setUser(user) {
    localStorage.setItem(this.USER_KEY,    JSON.stringify(user));
    localStorage.setItem(this.USER_TS_KEY, Date.now().toString());
  },

  getUser() {
    const u = localStorage.getItem(this.USER_KEY);
    return u ? JSON.parse(u) : null;
  },

  isUserStale() {
    const ts = parseInt(localStorage.getItem(this.USER_TS_KEY) || '0');
    return Date.now() - ts > this.USER_TTL_MS;
  },

  // ── Role helpers ─────────────────────────────────────────
  getRole() {
    const user = this.getUser();
    return user?.role_name
      || user?.role_detail?.name
      || user?.role?.name
      || null;
  },

  // Map role → portal URL
  ROLE_PORTALS: {
    BRANCH_MANAGER           : '/portal/dashboard/',
    CASHIER                  : '/portal/cashier/',
    ATTENDANT                : '/portal/attendant/',
    REGIONAL_MANAGER         : '/portal/dashboard/',
    REGIONAL_HR_COORDINATOR  : '/portal/dashboard/',
    BELT_MANAGER             : '/portal/dashboard/',
    HQ_FACTORY_MANAGER       : '/portal/dashboard/',
    HQ_HR_MANAGER            : '/portal/dashboard/',
    SUPER_ADMIN              : '/portal/dashboard/',
    DESIGNER                 : '/portal/attendant/',
  },

  redirectToPortal() {
    const role = this.getRole();
    const url  = this.ROLE_PORTALS[role] || '/portal/dashboard/';
    window.location.href = url;
  },

  // ── Auth state ───────────────────────────────────────────
  isAuthenticated() { return !!this.getToken(); },

  logout(reason = '') {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.REFRESH_KEY);
    localStorage.removeItem(this.USER_KEY);
    localStorage.removeItem(this.USER_TS_KEY);
    this._guardRan = false;
    const url = reason
      ? `/portal/login/?reason=${encodeURIComponent(reason)}`
      : '/portal/login/';
    window.location.href = url;
  },

  // ── Token refresh ────────────────────────────────────────
  async refresh() {
    const refreshToken = this.getRefreshToken();
    if (!refreshToken) { this.logout('expired'); return null; }

    try {
      const res = await fetch('/api/v1/auth/token/refresh/', {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({ refresh: refreshToken }),
      });
      if (!res.ok) { this.logout('expired'); return null; }
      const data = await res.json();
      localStorage.setItem(this.TOKEN_KEY, data.access);
      return data.access;
    } catch {
      this.logout('expired');
      return null;
    }
  },

  // ── Authenticated fetch ──────────────────────────────────
  async fetch(url, options = {}) {
    const token = this.getToken();
    if (!token) { this.logout('expired'); return null; }

    const headers = {
        'Authorization': `Bearer ${token}`,
        ...(options.headers || {}),
      };
      // Only set Content-Type for JSON — let browser set it for FormData
      if (!(options.body instanceof FormData) && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
      }

    let res = await fetch(url, { ...options, headers });

    if (res.status === 401) {
      const newToken = await this.refresh();
      if (!newToken) return null;
      headers['Authorization'] = `Bearer ${newToken}`;
      res = await fetch(url, { ...options, headers });
    }

    return res;
  },

  // ── Page guard ───────────────────────────────────────────
async guard(allowedRoles = []) {
    // Not logged in → login page
    if (!this.isAuthenticated()) {
      this.logout();
      return;
    }

    // Always fetch fresh user on first guard run per page load
    if (!this._guardRan) {
      this._guardRan = true;
      try {
        const res = await this.fetch('/api/v1/accounts/me/');
        if (res?.ok) {
          const user = await res.json();
          this.setUser(user);
          // Log the user object so we can see the role field name
          console.log('User object from API:', JSON.stringify(user));
        }
      } catch { /* silent */ }
    }

    // Role check — only after user is fetched
    if (allowedRoles.length > 0) {
      const role = this.getRole();
      console.log('Detected role:', role);

      if (!role) {
        document.body.innerHTML = `
          <div style="
            display:flex;flex-direction:column;align-items:center;justify-content:center;
            min-height:100vh;background:#f9f9f7;font-family:'DM Sans',sans-serif;gap:16px;
            padding:24px;text-align:center;">
            <div style="font-size:48px;">🔍</div>
            <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:#111;">
              Oops, you got lost in translation.
            </div>
            <div style="font-size:14px;color:#888;max-width:380px;line-height:1.6;">
              No role was found for your account. Please contact your administrator to get a role assigned.
            </div>
            <button onclick="Auth.logout()"
              style="margin-top:8px;padding:10px 24px;background:#111;color:#fff;border:none;
                     border-radius:8px;font-size:14px;font-weight:700;cursor:pointer;
                     font-family:'DM Sans',sans-serif;">
              Back to Login
            </button>
          </div>`;
        return;
      }

      if (!allowedRoles.includes(role)) {
        this.redirectToPortal();
        return;
      }
    }
  },

  // ── Topbar helper ────────────────────────────────────────
  async loadUserInfo() {
    let user = this.getUser();
    if (!user) {
      const res = await this.fetch('/api/v1/accounts/me/');
      if (!res) return;
      user = await res.json();
      this.setUser(user);
    }

    const nameEl   = document.getElementById('topbar-user-name');
    const roleEl   = document.getElementById('topbar-user-role');
    const avatarEl = document.getElementById('topbar-avatar');
    const branchEl = document.getElementById('topbar-branch');

    if (nameEl)   nameEl.textContent   = user.full_name || user.email;
    if (roleEl)   roleEl.textContent   = user.role_detail?.name || '';
    if (avatarEl) avatarEl.textContent =
      (user.first_name?.[0] || '') + (user.last_name?.[0] || '');
    if (branchEl) branchEl.textContent = user.branch_name || '';
  },
};

window.Auth = Auth;