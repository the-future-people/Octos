/**
 * Octos — Branch Manager Inbox
 * Handles: conversation list, channel filtering, search,
 *          message thread, reply, assign, resolve, link-job
 */

'use strict';

// ─────────────────────────────────────────
// State
// ─────────────────────────────────────────
const State = {
  conversations: [],       // full list from API
  filtered: [],            // after channel + search filter
  activeId: null,          // currently open conversation id
  activeConvo: null,       // full conversation object
  messages: [],            // messages for active conversation
  channel: 'all',          // active channel tab
  pollTimer: null,         // message polling interval
  jobSearchTimer: null,    // debounce for job search
};

// ─────────────────────────────────────────
// DOM refs
// ─────────────────────────────────────────
const $ = id => document.getElementById(id);
const convoList      = $('convo-list');
const noConvoMsg     = $('no-convo-msg');
const activeConvoEl  = $('active-convo');
const messagesArea   = $('messages-area');
const replyInput     = $('reply-input');
const linkedJobBar   = $('linked-job-bar');
const linkedJobText  = $('linked-job-text');

// ─────────────────────────────────────────
// Bootstrap
// ─────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  Auth.guard();
  loadConversations();
  bindChannelTabs();
  bindSearch();
  bindReply();
  bindActionButtons();
  bindModalClose();
  startPolling();
});

// ─────────────────────────────────────────
// Load Conversations
// ─────────────────────────────────────────
async function loadConversations() {
  try {
    const res = await Auth.fetch('/api/v1/communications/');
    if (!res.ok) throw new Error('Failed to load');
    const data = await res.json();
    State.conversations = Array.isArray(data) ? data : (data.results || []);
    applyFilters();
  } catch (err) {
    convoList.innerHTML = `
      <div style="padding:40px;text-align:center;color:var(--text-muted);font-size:13px;">
        <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity:.4;display:block;margin:0 auto 10px;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        Could not load conversations
      </div>`;
  }
}

// ─────────────────────────────────────────
// Filter & Render Conversation List
// ─────────────────────────────────────────
function applyFilters() {
  const query = ($('inbox-search')?.value || '').toLowerCase().trim();

  State.filtered = State.conversations.filter(c => {
    const matchChannel = State.channel === 'all' || c.channel === State.channel;
    const matchSearch  = !query ||
      (c.customer_name || '').toLowerCase().includes(query) ||
      (c.last_message  || '').toLowerCase().includes(query);
    return matchChannel && matchSearch;
  });

  renderConvoList();
}

function renderConvoList() {
  if (!State.filtered.length) {
    convoList.innerHTML = `
      <div class="empty-state" style="padding:48px 20px;">
        <div class="empty-icon"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></div>
        <h4>No conversations</h4>
        <p>Nothing matches the current filter.</p>
      </div>`;
    return;
  }

  convoList.innerHTML = State.filtered.map(c => {
    const initials   = getInitials(c.customer_name || 'Unknown');
    const avatarColor = pickColor(c.customer_name || '');
    const isActive   = c.id === State.activeId;
    const isUnread   = c.unread_count > 0;
    const time       = formatTime(c.updated_at || c.created_at);
    const channelIcon = channelSVG(c.channel);
    const preview    = escHtml(truncate(c.last_message || 'No messages yet', 52));

    return `
      <div class="convo-item ${isActive ? 'active' : ''} ${isUnread ? 'unread' : ''}"
           data-id="${c.id}"
           onclick="openConversation(${c.id})">
        <div class="convo-avatar ${avatarColor}">${initials}</div>
        <div class="convo-info">
          <div class="convo-name-row">
            <span class="convo-name">${escHtml(c.customer_name || 'Unknown')}</span>
            <span class="convo-time">${time}</span>
          </div>
          <div class="convo-preview">
            ${channelIcon}
            ${preview}
            ${isUnread ? `<span style="color:var(--yellow);font-weight:600;margin-left:4px;">${c.unread_count}</span>` : ''}
          </div>
        </div>
      </div>`;
  }).join('');
}

// ─────────────────────────────────────────
// Open Conversation
// ─────────────────────────────────────────
async function openConversation(id) {
  State.activeId  = id;
  State.activeConvo = State.conversations.find(c => c.id === id) || null;

  // Update sidebar active state
  renderConvoList();

  // Show pane
  noConvoMsg.style.display    = 'none';
  activeConvoEl.style.display = 'flex';

  // Populate header
  if (State.activeConvo) {
    const c       = State.activeConvo;
    const initials = getInitials(c.customer_name || 'Unknown');
    const color    = pickColor(c.customer_name || '');

    $('active-avatar').textContent = initials;
    $('active-avatar').className   = `avatar ${color}`;
    $('active-name').textContent   = c.customer_name || 'Unknown';
    $('active-meta').textContent   = c.contact_info  || c.channel || '—';

    const badge = $('active-channel-badge');
    badge.textContent = (c.channel || 'unknown').toUpperCase();
    badge.className   = `badge ${channelBadgeClass(c.channel)}`;

    // Linked job
    if (c.job) {
      linkedJobBar.style.display = 'flex';
      linkedJobText.textContent  = `Linked: Job #${c.job}`;
    } else {
      linkedJobBar.style.display = 'none';
    }
  }

  // Load messages
  await loadMessages(id);
  scrollMessages();
}

// ─────────────────────────────────────────
// Load & Render Messages
// ─────────────────────────────────────────
async function loadMessages(convoId) {
  messagesArea.innerHTML = `
    <div style="text-align:center;color:var(--text-muted);padding:40px 0;font-size:13px;">
      <div class="spinner" style="margin:0 auto 10px;"></div>
      Loading messages…
    </div>`;

  try {
    const res = await Auth.fetch(`/api/v1/communications/${convoId}/`);
    if (!res.ok) throw new Error('Failed');
    const data = await res.json();
    State.messages = data.messages || [];
    renderMessages();
  } catch {
    messagesArea.innerHTML = `
      <div style="text-align:center;color:var(--text-muted);padding:40px 0;font-size:13px;">
        Could not load messages.
      </div>`;
  }
}

function renderMessages() {
  if (!State.messages.length) {
    messagesArea.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        </div>
        <h4>No messages yet</h4>
        <p>Be the first to send a message.</p>
      </div>`;
    return;
  }

  messagesArea.innerHTML = State.messages.map(m => {
    const dir  = m.direction === 'outbound' ? 'outbound' : 'inbound';
    const time = formatTime(m.created_at);
    const sender = dir === 'outbound' ? (m.sent_by_name || 'You') : (State.activeConvo?.customer_name || 'Customer');

    return `
      <div class="msg-row ${dir}">
        <div>
          <div class="msg-bubble">${escHtml(m.body || '')}</div>
          <div class="msg-meta">${sender} · ${time}</div>
        </div>
      </div>`;
  }).join('');
}

function scrollMessages() {
  setTimeout(() => {
    messagesArea.scrollTop = messagesArea.scrollHeight;
  }, 50);
}

// ─────────────────────────────────────────
// Reply
// ─────────────────────────────────────────
function bindReply() {
  $('btn-send').addEventListener('click', sendReply);
  replyInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendReply();
    }
  });
}

async function sendReply() {
  const body = replyInput.value.trim();
  if (!body || !State.activeId) return;

  const btn = $('btn-send');
  btn.disabled = true;
  btn.innerHTML = `<div class="spinner spinner-sm"></div>`;

  try {
    const res = await Auth.fetch(`/api/v1/communications/${State.activeId}/reply/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body }),
    });

    if (!res.ok) throw new Error('Send failed');

    replyInput.value = '';
    replyInput.style.height = 'auto';
    await loadMessages(State.activeId);
    scrollMessages();

    // Update preview in sidebar
    const idx = State.conversations.findIndex(c => c.id === State.activeId);
    if (idx !== -1) {
      State.conversations[idx].last_message = body;
      State.conversations[idx].updated_at   = new Date().toISOString();
      applyFilters();
    }

    toast('Message sent', 'success');
  } catch {
    toast('Could not send message', 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = `
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
      Send`;
  }
}

// ─────────────────────────────────────────
// Action Buttons — Resolve / Assign / Link Job
// ─────────────────────────────────────────
function bindActionButtons() {
  $('btn-resolve').addEventListener('click', resolveConversation);
  $('btn-assign').addEventListener('click', openAssignModal);
  $('btn-link-job').addEventListener('click', openLinkJobModal);
  $('btn-unlink-job').addEventListener('click', unlinkJob);
  $('btn-confirm-assign').addEventListener('click', confirmAssign);

  // Job search debounce
  $('job-search-input').addEventListener('input', () => {
    clearTimeout(State.jobSearchTimer);
    State.jobSearchTimer = setTimeout(searchJobs, 400);
  });
}

async function resolveConversation() {
  if (!State.activeId) return;
  const btn = $('btn-resolve');
  btn.disabled = true;

  try {
    const res = await Auth.fetch(`/api/v1/communications/${State.activeId}/resolve/`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error('Failed');
    toast('Conversation resolved', 'success');

    // Remove from list
    State.conversations = State.conversations.filter(c => c.id !== State.activeId);
    State.activeId      = null;
    State.activeConvo   = null;
    noConvoMsg.style.display    = 'flex';
    activeConvoEl.style.display = 'none';
    applyFilters();
  } catch {
    toast('Could not resolve conversation', 'error');
    btn.disabled = false;
  }
}

async function openAssignModal() {
  openModal('assign-modal');
  const select = $('assign-user-select');
  select.innerHTML = '<option value="">Loading…</option>';

  try {
    const res  = await Auth.fetch('/api/v1/accounts/users/');
    if (!res.ok) throw new Error('Failed');
    const data = await res.json();
    const users = Array.isArray(data) ? data : (data.results || []);
    select.innerHTML = '<option value="">Select agent…</option>' +
      users.map(u => `<option value="${u.id}">${u.full_name || u.email}</option>`).join('');
  } catch {
    select.innerHTML = '<option value="">Could not load agents</option>';
  }
}

async function confirmAssign() {
  const userId = $('assign-user-select').value;
  if (!userId || !State.activeId) return;

  try {
    const res = await Auth.fetch(`/api/v1/communications/${State.activeId}/assign/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ assigned_to: userId }),
    });
    if (!res.ok) throw new Error('Failed');
    closeModal('assign-modal');
    toast('Conversation assigned', 'success');
  } catch {
    toast('Could not assign conversation', 'error');
  }
}

function openLinkJobModal() {
  openModal('link-job-modal');
  $('job-search-input').value = '';
  $('job-search-results').innerHTML = '';
}

async function searchJobs() {
  const q = $('job-search-input').value.trim();
  const results = $('job-search-results');
  if (!q) { results.innerHTML = ''; return; }

  results.innerHTML = `<div style="padding:16px;text-align:center;"><div class="spinner" style="margin:auto;"></div></div>`;

  try {
    const res  = await Auth.fetch(`/api/v1/jobs/?search=${encodeURIComponent(q)}`);
    if (!res.ok) throw new Error('Failed');
    const data = await res.json();
    const jobs = Array.isArray(data) ? data : (data.results || []);

    if (!jobs.length) {
      results.innerHTML = `<div style="padding:16px;text-align:center;color:var(--text-muted);font-size:13px;">No jobs found</div>`;
      return;
    }

    results.innerHTML = jobs.slice(0, 10).map(j => `
      <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-radius:var(--radius-sm);border:1px solid var(--border);margin-bottom:6px;cursor:pointer;transition:border-color .15s;"
           onMouseOver="this.style.borderColor='var(--yellow)'"
           onMouseOut="this.style.borderColor='var(--border)'"
           onclick="selectJob(${j.id}, '${escHtml(j.reference || '#' + j.id)}')">
        <div>
          <div style="font-size:13.5px;font-weight:600;color:var(--text-primary);">${escHtml(j.reference || '#' + j.id)}</div>
          <div style="font-size:12px;color:var(--text-muted);">${escHtml(j.customer_name || '—')}</div>
        </div>
        <span class="badge badge-grey">${escHtml(j.status || '—')}</span>
      </div>`).join('');
  } catch {
    results.innerHTML = `<div style="padding:16px;text-align:center;color:var(--red);font-size:13px;">Search failed</div>`;
  }
}

async function selectJob(jobId, jobRef) {
  if (!State.activeId) return;

  try {
    const res = await Auth.fetch(`/api/v1/communications/${State.activeId}/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job: jobId }),
    });
    if (!res.ok) throw new Error('Failed');

    linkedJobBar.style.display = 'flex';
    linkedJobText.textContent  = `Linked: ${jobRef}`;

    const idx = State.conversations.findIndex(c => c.id === State.activeId);
    if (idx !== -1) State.conversations[idx].job = jobId;

    closeModal('link-job-modal');
    toast(`Linked to ${jobRef}`, 'success');
  } catch {
    toast('Could not link job', 'error');
  }
}

async function unlinkJob() {
  if (!State.activeId) return;

  try {
    const res = await Auth.fetch(`/api/v1/communications/${State.activeId}/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job: null }),
    });
    if (!res.ok) throw new Error('Failed');
    linkedJobBar.style.display = 'none';
    const idx = State.conversations.findIndex(c => c.id === State.activeId);
    if (idx !== -1) State.conversations[idx].job = null;
    toast('Job unlinked', 'info');
  } catch {
    toast('Could not unlink job', 'error');
  }
}

// ─────────────────────────────────────────
// Channel Tabs
// ─────────────────────────────────────────
function bindChannelTabs() {
  document.querySelectorAll('.channel-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.channel-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      State.channel = btn.dataset.channel;
      applyFilters();
    });
  });
}

// ─────────────────────────────────────────
// Search
// ─────────────────────────────────────────
function bindSearch() {
  let timer;
  $('inbox-search').addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(applyFilters, 250);
  });
}

// ─────────────────────────────────────────
// Polling — refresh active thread every 15s
// ─────────────────────────────────────────
function startPolling() {
  State.pollTimer = setInterval(async () => {
    if (State.activeId) {
      await loadMessages(State.activeId);
      scrollMessages();
    }
    // Refresh conversation list every minute
  }, 15000);
}

// ─────────────────────────────────────────
// Modal Helpers
// ─────────────────────────────────────────
function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('open');
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('open');
}

function bindModalClose() {
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => {
      if (e.target === overlay) overlay.classList.remove('open');
    });
  });
}

// ─────────────────────────────────────────
// Toast
// ─────────────────────────────────────────
function toast(msg, type = 'info') {
  const container = $('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const icons = {
    success: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
    error:   `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
    info:    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="8"/><line x1="12" y1="12" x2="12" y2="16"/></svg>`,
  };
  el.innerHTML = (icons[type] || icons.info) + `<span>${escHtml(msg)}</span>`;
  container.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ─────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────
function getInitials(name) {
  return name.split(' ').slice(0, 2).map(w => w[0]?.toUpperCase() || '').join('') || '?';
}

const COLORS = ['yellow', 'red', 'green'];
function pickColor(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  return COLORS[Math.abs(hash) % COLORS.length];
}

function truncate(str, len) {
  return str.length > len ? str.slice(0, len) + '…' : str;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatTime(iso) {
  if (!iso) return '—';
  const d    = new Date(iso);
  const now  = new Date();
  const diff = now - d;
  if (diff < 60000)    return 'just now';
  if (diff < 3600000)  return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

function channelSVG(channel) {
  const icons = {
    whatsapp: `<svg class="convo-channel-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>`,
    email:    `<svg class="convo-channel-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>`,
    phone:    `<svg class="convo-channel-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 12 19.79 19.79 0 0 1 1.61 3.45a2 2 0 0 1 1.99-2.18h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L7.91 9.04a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7a2 2 0 0 1 1.72 2.03z"/></svg>`,
  };
  return icons[channel] || '';
}

function channelBadgeClass(channel) {
  const map = { whatsapp: 'badge-green', email: 'badge-yellow', phone: 'badge-grey' };
  return map[channel] || 'badge-grey';
}