/**
 * CustomerReg — Shared Customer Registration Module
 *
 * Used by both the BM Dashboard and the Attendant portal.
 * Extracted from dashboard.js — zero new logic.
 *
 * Usage:
 *   CustomerReg.open(onSuccess)
 *
 * onSuccess(customerData) is called after a successful registration.
 * The caller decides what to do next (open profile, show flash, etc.)
 *
 * Depends on: Auth, State (branchId)
 */

'use strict';

const CustomerReg = (() => {

  // ── State ──────────────────────────────────────────────────
  let _addCustType  = 'INDIVIDUAL';
  let _onSuccess    = null;

  // ── Helpers ────────────────────────────────────────────────
  function _esc(str) {
    return String(str ?? '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _toast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el     = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  // ── Public entry point ─────────────────────────────────────
  function open(onSuccess) {
    _onSuccess   = onSuccess || null;
    _addCustType = 'INDIVIDUAL';

    document.getElementById('add-customer-overlay')?.remove();

    const overlay = document.createElement('div');
    overlay.id = 'add-customer-overlay';
    overlay.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,0.55);
      z-index:2000;display:flex;align-items:center;justify-content:center;padding:24px;`;
    overlay.onclick = e => { e.stopPropagation(); };

    overlay.innerHTML = `
      <div style="background:var(--bg);border-radius:var(--radius);
        width:100%;max-width:560px;max-height:90vh;display:flex;flex-direction:column;
        border:1px solid var(--border);box-shadow:0 24px 64px rgba(0,0,0,0.2);
        overflow:hidden;">

        <!-- Header -->
        <div style="padding:18px 24px;border-bottom:1px solid var(--border);
          display:flex;align-items:center;justify-content:space-between;flex-shrink:0;
          background:var(--panel);">
          <div>
            <div style="font-family:'Syne',sans-serif;font-size:17px;font-weight:800;
              color:var(--text);letter-spacing:-0.2px;">Register Customer</div>
            <div style="font-size:12px;color:var(--text-3);margin-top:2px;">
              All fields marked * are required
            </div>
          </div>
          <button onclick="CustomerReg._close()"
            style="background:none;border:none;font-size:20px;cursor:pointer;
              color:var(--text-3);padding:4px 8px;">×</button>
        </div>

        <!-- Type selector -->
        <div style="padding:16px 24px;border-bottom:1px solid var(--border);
          background:var(--panel);flex-shrink:0;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.6px;margin-bottom:10px;">
            Customer Type
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
            ${[
              ['INDIVIDUAL',  'Individual',  `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`],
              ['BUSINESS',    'Business',    `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/></svg>`],
              ['INSTITUTION', 'Institution', `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>`],
            ].map(([type, label, icon]) => `
              <button id="cust-type-${type}" onclick="CustomerReg._setType('${type}')"
                style="display:flex;flex-direction:column;align-items:center;gap:6px;
                  padding:12px 8px;border-radius:var(--radius-sm);font-size:12px;
                  font-weight:700;cursor:pointer;transition:all 0.15s;
                  font-family:'DM Sans',sans-serif;
                  ${type === 'INDIVIDUAL'
                    ? 'background:#f0f4fd;color:#2e4a8a;border:2px solid #2e4a8a;'
                    : 'background:var(--bg);color:var(--text-3);border:2px solid var(--border);'}">
                ${icon}
                ${label}
              </button>`).join('')}
          </div>
        </div>

        <!-- Scrollable form body -->
        <div style="flex:1;overflow-y:auto;padding:20px 24px;" id="add-cust-form-body">
          ${_buildForm('INDIVIDUAL')}
        </div>

        <!-- Footer -->
        <div style="padding:16px 24px;border-top:1px solid var(--border);
          background:var(--panel);flex-shrink:0;">
          <div id="add-cust-error" style="display:none;font-size:12px;
            color:var(--red-text);margin-bottom:10px;padding:8px 12px;
            background:var(--red-bg);border:1px solid var(--red-border);
            border-radius:var(--radius-sm);"></div>
          <div style="display:flex;gap:8px;">
            <button onclick="CustomerReg._close()"
              style="flex:1;padding:10px;background:none;border:1px solid var(--border);
                border-radius:var(--radius-sm);font-size:13px;font-weight:600;
                cursor:pointer;color:var(--text-2);font-family:'DM Sans',sans-serif;">
              Cancel
            </button>
            <button id="add-cust-submit-btn" onclick="CustomerReg._submit()"
              style="flex:2;padding:10px;background:var(--text);color:#fff;border:none;
                border-radius:var(--radius-sm);font-size:13px;font-weight:700;
                cursor:pointer;font-family:'DM Sans',sans-serif;">
              Register Customer
            </button>
          </div>
        </div>

      </div>`;

    document.body.appendChild(overlay);
    setTimeout(() => document.getElementById('cust-first-name')?.focus(), 100);
  }

  // ── Form builder ───────────────────────────────────────────
  function _buildForm(type) {
    const isIndividual  = type === 'INDIVIDUAL';
    const isBusiness    = type === 'BUSINESS';
    const isInstitution = type === 'INSTITUTION';

    return `
      <div style="display:flex;flex-direction:column;gap:14px;">

        ${isInstitution ? `
        <div>
          <label style="font-size:11px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
            Institution Type *
          </label>
          <select id="cust-subtype" style="width:100%;padding:9px 12px;
            border:1.5px solid var(--border);border-radius:var(--radius-sm);
            background:var(--bg);color:var(--text);font-size:13px;
            font-family:'DM Sans',sans-serif;outline:none;">
            <option value="">Select type…</option>
            <option value="SCHOOL">School</option>
            <option value="CHURCH">Church / Religious</option>
            <option value="NGO">NGO / Non-profit</option>
            <option value="GOVT">Government / Public</option>
            <option value="OTHER">Other Institution</option>
          </select>
        </div>` : ''}

        ${!isIndividual ? `
        <div>
          <label style="font-size:11px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
            ${isBusiness ? 'Company Name' : 'Institution Name'} *
          </label>
          <input type="text" id="cust-company"
            placeholder="${isBusiness ? 'e.g. Suma Court Hotel' : 'e.g. Accra High School'}"
            style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
              border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
              font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
              box-sizing:border-box;">
        </div>` : ''}

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
          <div>
            <label style="font-size:11px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
              ${isIndividual ? 'First Name *' : 'Rep First Name *'}
            </label>
            <input type="text" id="cust-first-name"
              placeholder="${isIndividual ? 'e.g. Kwame' : 'e.g. Ama'}"
              style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
                border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
                box-sizing:border-box;">
          </div>
          <div>
            <label style="font-size:11px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
              ${isIndividual ? 'Last Name *' : 'Rep Last Name *'}
            </label>
            <input type="text" id="cust-last-name"
              placeholder="${isIndividual ? 'e.g. Mensah' : 'e.g. Owusu'}"
              style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
                border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
                box-sizing:border-box;">
          </div>
        </div>

        <div>
          <label style="font-size:11px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
            Phone Number *
          </label>
          <input type="tel" id="cust-phone" placeholder="e.g. 0244123456"
            onblur="CustomerReg._checkPhoneDuplicate()"
            style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
              border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
              font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
              box-sizing:border-box;">
          <div id="cust-phone-feedback" style="font-size:11px;margin-top:4px;"></div>
        </div>

        <div>
          <label style="font-size:11px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
            Email <span style="font-weight:400;color:var(--text-3);">(optional)</span>
          </label>
          <input type="email" id="cust-email" placeholder="e.g. info@example.com"
            style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
              border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
              font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
              box-sizing:border-box;">
        </div>

        <div>
          <label style="font-size:11px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
            Address ${!isIndividual
              ? '*'
              : '<span style="font-weight:400;color:var(--text-3);">(optional)</span>'}
          </label>
          <textarea id="cust-address" rows="2"
            placeholder="Physical address…"
            style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
              border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
              font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
              resize:none;box-sizing:border-box;"></textarea>
        </div>

        <div>
          <label style="font-size:11px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
            Notes <span style="font-weight:400;color:var(--text-3);">(optional)</span>
          </label>
          <textarea id="cust-notes" rows="2"
            placeholder="Any notes about this customer…"
            style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
              border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
              font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
              resize:none;box-sizing:border-box;"></textarea>
        </div>

      </div>`;
  }

  // ── Type switcher ──────────────────────────────────────────
  function _setType(type) {
    _addCustType = type;

    const typeColors = {
      INDIVIDUAL : { bg: '#f0f4fd', color: '#2e4a8a', border: '#2e4a8a' },
      BUSINESS   : { bg: '#f0fdf4', color: '#1a6b3a', border: '#1a6b3a' },
      INSTITUTION: { bg: '#f5f0fd', color: '#5a2e8a', border: '#5a2e8a' },
    };

    ['INDIVIDUAL','BUSINESS','INSTITUTION'].forEach(t => {
      const btn = document.getElementById(`cust-type-${t}`);
      if (!btn) return;
      if (t === type) {
        const c = typeColors[t];
        btn.style.background = c.bg;
        btn.style.color      = c.color;
        btn.style.border     = `2px solid ${c.border}`;
      } else {
        btn.style.background = 'var(--bg)';
        btn.style.color      = 'var(--text-3)';
        btn.style.border     = '2px solid var(--border)';
      }
    });

    const body = document.getElementById('add-cust-form-body');
    if (body) {
      body.innerHTML = _buildForm(type);
      setTimeout(() => document.getElementById('cust-first-name')?.focus(), 50);
    }
  }

  // ── Phone normalisation ────────────────────────────────────
  function _normalisePhone(raw) {
    let p = String(raw || '').replace(/[\s\-().]/g, '');
    if (p.startsWith('+233')) p = '0' + p.slice(4);
    if (p.startsWith('233') && p.length >= 12) p = '0' + p.slice(3);
    return p;
  }

  // ── Phone duplicate check ──────────────────────────────────
  async function _checkPhoneDuplicate() {
    const raw      = document.getElementById('cust-phone')?.value.trim();
    const phone    = _normalisePhone(raw);
    const feedback = document.getElementById('cust-phone-feedback');
    const input    = document.getElementById('cust-phone');

    if (raw !== phone && input) input.value = phone;
    if (!feedback || !phone) return;

    feedback.textContent = '';
    feedback.style.color = '';

    // Employee roster check
    try {
      const branchId = State?.branchId;
      if (branchId) {
        const empRes = await Auth.fetch(`/api/v1/accounts/users/?branch=${branchId}`);
        if (empRes.ok) {
          const empData = await empRes.json();
          const empList = Array.isArray(empData) ? empData : (empData.results || []);
          const match   = empList.find(u => u.phone && u.phone === phone);
          if (match) {
            feedback.textContent    = `⚠ This number belongs to a branch employee (${match.full_name}). Cannot register.`;
            feedback.style.color    = 'var(--red-text)';
            if (input) input.style.borderColor = 'var(--red-border)';
            return;
          }
        }
      }
    } catch { /* silent */ }

    // Customer duplicate check
    try {
      const res = await Auth.fetch(`/api/v1/customers/lookup/?phone=${encodeURIComponent(phone)}`);
      if (res.status === 200) {
        const existing = await res.json();
        const name     = existing.display_name || existing.full_name || 'Unknown';
        feedback.innerHTML  = `⚠ A customer with this number already exists: <strong>${_esc(name)}</strong>. Cannot register a duplicate.`;
        feedback.style.color = 'var(--red-text)';
        if (input) input.style.borderColor = 'var(--red-border)';
        return;
      }
    } catch { /* silent */ }

    feedback.textContent    = '✓ Phone number is available';
    feedback.style.color    = 'var(--green-text)';
    if (input) input.style.borderColor = 'var(--green-border, #16a34a)';
  }

  // ── Submit ─────────────────────────────────────────────────
  async function _submit() {
    const btn   = document.getElementById('add-cust-submit-btn');
    const errEl = document.getElementById('add-cust-error');
    errEl.style.display = 'none';

    const type      = _addCustType;
    const firstName = document.getElementById('cust-first-name')?.value.trim();
    const lastName  = document.getElementById('cust-last-name')?.value.trim();
    const phone     = _normalisePhone(document.getElementById('cust-phone')?.value.trim());
    const email     = document.getElementById('cust-email')?.value.trim();
    const address   = document.getElementById('cust-address')?.value.trim();
    const notes     = document.getElementById('cust-notes')?.value.trim();
    const company   = document.getElementById('cust-company')?.value.trim() || '';
    const subtype   = document.getElementById('cust-subtype')?.value || '';

    const showErr = msg => {
      errEl.textContent   = msg;
      errEl.style.display = 'block';
      errEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };

    if (!firstName) return showErr('First name is required.');
    if (!lastName)  return showErr('Last name is required.');
    if (!phone)     return showErr('Phone number is required.');

    if (type !== 'INDIVIDUAL' && !company) {
      return showErr(`${type === 'BUSINESS' ? 'Company' : 'Institution'} name is required.`);
    }
    if (type === 'INSTITUTION' && !subtype) {
      return showErr('Please select the institution type.');
    }
    if (type !== 'INDIVIDUAL' && !address) {
      return showErr('Address is required for businesses and institutions.');
    }

    btn.disabled    = true;
    btn.textContent = 'Checking…';

    // Employee phone check
    try {
      const branchId = State?.branchId;
      if (branchId) {
        const empRes = await Auth.fetch(`/api/v1/accounts/users/?branch=${branchId}`);
        if (empRes.ok) {
          const empData = await empRes.json();
          const empList = Array.isArray(empData) ? empData : (empData.results || []);
          const match   = empList.find(u => u.phone && u.phone === phone);
          if (match) {
            btn.disabled    = false;
            btn.textContent = 'Register Customer';
            return showErr(`This phone number belongs to a branch employee (${match.full_name}). Registration blocked.`);
          }
        }
      }
    } catch { /* silent */ }

    // Customer phone duplicate
    try {
      const res = await Auth.fetch(`/api/v1/customers/lookup/?phone=${encodeURIComponent(phone)}`);
      if (res.status === 200) {
        const existing = await res.json();
        const name     = existing.display_name || existing.full_name || 'this number';
        btn.disabled    = false;
        btn.textContent = 'Register Customer';
        return showErr(`A customer with this number already exists: ${name}. Cannot create a duplicate.`);
      }
    } catch { /* silent */ }

    // Company name duplicate
    if (company) {
      try {
        const res  = await Auth.fetch(`/api/v1/customers/?company_name=${encodeURIComponent(company)}`);
        if (res.ok) {
          const data = await res.json();
          const list = Array.isArray(data) ? data : (data.results || []);
          if (list.length > 0) {
            btn.disabled    = false;
            btn.textContent = 'Register Customer';
            return showErr(`A customer named "${company}" already exists. Cannot create a duplicate.`);
          }
        }
      } catch { /* silent */ }
    }

    btn.textContent = 'Registering…';

    try {
      const res  = await Auth.fetch('/api/v1/customers/create/', {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({
          customer_type       : type,
          first_name          : firstName,
          last_name           : lastName,
          phone,
          email               : email  || '',
          address             : address || '',
          company_name        : company || '',
          institution_subtype : subtype || '',
          notes               : notes  || '',
        }),
      });
      const data = await res.json();

      if (!res.ok) {
        const msg = Object.values(data).flat().join(' ');
        btn.disabled    = false;
        btn.textContent = 'Register Customer';
        return showErr(msg || 'Registration failed. Please try again.');
      }

      // Success — close modal, fire callback
      _close();
      if (typeof _onSuccess === 'function') _onSuccess(data);

    } catch {
      btn.disabled    = false;
      btn.textContent = 'Register Customer';
      showErr('Network error. Please try again.');
    }
  }

  // ── Close ──────────────────────────────────────────────────
  function _close() {
    document.getElementById('add-customer-overlay')?.remove();
  }

  // ── Public API ─────────────────────────────────────────────
  return {
    open,
    _close,
    _setType,
    _checkPhoneDuplicate,
    _submit,
    _normalisePhone,
  };

})();