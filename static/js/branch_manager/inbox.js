/**
 * Octos — Branch Manager Inbox
 * inbox.js
 *
 * API endpoints consumed:
 *   GET  /api/v1/accounts/me/                            — user info for topbar
 *   GET  /api/v1/communications/                         — conversation list
 *   GET  /api/v1/communications/<id>/                    — conversation detail + messages
 *   POST /api/v1/communications/<id>/reply/              — send message { body }
 *   POST /api/v1/communications/<id>/resolve/            — mark resolved
 *   POST /api/v1/communications/<id>/assign/             — assign { user_id }
 *   POST /api/v1/communications/<id>/link-job/           — link job { job_id }
 *   GET  /api/v1/jobs/?search=<q>                        — job search for link-job modal
 *   GET  /api/v1/accounts/users/                         — agent list for assign modal
 *
 * Serializer field mapping (actual API response fields):
 *   Conversation list  : { id, display_name, channel, status, unread_count,
 *                          last_message_at, last_message_preview, ... }
 *   Conversation detail: { ...list fields, contact_name, contact_phone,
 *                          contact_email, jobs: [...], messages: [...] }
 *   Message            : { id, direction, body, sent_by_name, created_at }
 */

'use strict';

const Inbox = (() => {

  // ─────────────────────────────────────────
  // State
  // ─────────────────────────────────────────
  const State = {
    conversations : [],     // raw list from GET /communications/
    filtered      : [],     // after channel + search filter
    activeId      : null,   // currently open conversation id
    activeConvo   : null,   // full detail object (from GET /communications/<id>/)
    messages      : [],     // messages for active conversation
    channel       : 'all',  // active channel filter
    pollTimer     : null,   // setInterval handle for message polling
    jobTimer      : null,   // debounce for job search input
  };

  // ─────────────────────────────────────────
  // DOM refs
  // ─────────────────────────────────────────
  let $convoList, $paneEmpty, $activeConvo,
      $messagesArea, $replyInput, $linkedJobBar, $linkedJobText;

  const $ = id => document.getElementById(id);

  // ─────────────────────────────────────────
  // Boot
  // ─────────────────────────────────────────
  function init() {
    Auth.guard();

    $convoList     = $('convo-list');
    $paneEmpty     = $('pane-empty');
    $activeConvo   = $('active-convo');
    $messagesArea  = $('messages-area');
    $replyInput    = $('reply-input');
    $linkedJobBar  = $('linked-job-bar');
    $linkedJobText = $('linked-job-text');

    loadUser();
    loadConversations();
    bindChannelTabs();
    bindSearch();
    bindReply();
    bindActions();
    bindModalBackdrop();
    startPolling();
  }

  // ─────────────────────────────────────────
  // User (topbar)
  // ─────────────────────────────────────────
  async function loadUser() {
    try {
      const res  = await Auth.fetch('/api/v1/accounts/me/');
      if (!res.ok) return;
      const data = await res.json();
      const name = data.full_name || data.email || '—';
      $('ib-name').textContent     = name;
      $('ib-initials').textContent = initials(name);
    } catch { /* silent */ }
  }

  // ─────────────────────────────────────────
  // Conversations list
  // ─────────────────────────────────────────
  async function loadConversations() {
    $convoList.innerHTML = `<div class="loading-row"><span class="spin"></span> Loading…</div>`;
    try {
      const res  = await Auth.fetch('/api/v1/communications/');
      if (!res.ok) throw new Error();
      const data = await res.json();
      State.conversations = Array.isArray(data) ? data : (data.results || []);
      applyFilters();
    } catch {
      $convoList.innerHTML = `
        <div class="empty-list">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          <h4>Could not load conversations</h4>
          <p>Check your connection and refresh.</p>
        </div>`;
    }
  }

  // ─────────────────────────────────────────
  // Filter & render
  // ─────────────────────────────────────────
  function applyFilters() {
    const q = ($('inbox-search')?.value || '').toLowerCase().trim();
    State.filtered = State.conversations.filter(c => {
      const matchCh = State.channel === 'all' || c.channel === State.channel;
      const matchQ  = !q ||
        (c.display_name         || '').toLowerCase().includes(q) ||
        (c.last_message_preview || '').toLowerCase().includes(q);
      return matchCh && matchQ;
    });
    $('convo-count').textContent = State.filtered.length;
    renderConvoList();
  }

  function renderConvoList() {
    if (!State.filtered.length) {
      $convoList.innerHTML = `
        <div class="empty-list">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          <h4>No conversations</h4>
          <p>Nothing matches the current filter.</p>
        </div>`;
      return;
    }

    $convoList.innerHTML = State.filtered.map(c => {
      const ini      = initials(c.display_name || 'Unknown');
      const avClass  = pickAvColor(c.display_name || '');
      const isActive = c.id === State.activeId;
      const isUnread = (c.unread_count || 0) > 0;
      const time     = formatTime(c.last_message_at || c.created_at);
      const chIcon   = channelIcon(c.channel);
      const preview  = esc(truncate(c.last_message_preview || 'No messages yet', 54));

      return `
        <div class="convo-item ${isActive ? 'active' : ''} ${isUnread ? 'unread' : ''}"
             data-id="${c.id}" onclick="Inbox.openConvo(${c.id})">
          <div class="convo-av ${avClass}">${ini}</div>
          <div class="convo-info">
            <div class="convo-top">
              <span class="convo-name">${esc(c.display_name || 'Unknown')}</span>
              <span class="convo-time">${time}</span>
            </div>
            <div class="convo-bottom">
              ${chIcon}
              <span class="convo-preview">${preview}</span>
              ${isUnread ? '<span class="unread-pip"></span>' : ''}
            </div>
          </div>
        </div>`;
    }).join('');
  }

  // ─────────────────────────────────────────
  // Open conversation
  // ─────────────────────────────────────────
  async function openConvo(id) {
    State.activeId    = id;
    State.activeConvo = State.conversations.find(c => c.id === id) || null;

    renderConvoList();

    $paneEmpty.style.display   = 'none';
    $activeConvo.style.display = 'flex';

    // Populate header immediately from list data (fast)
    const c = State.activeConvo;
    if (c) {
      const ini     = initials(c.display_name || 'Unknown');
      const avClass = pickAvColor(c.display_name || '');

      const av = $('pane-av');
      av.textContent = ini;
      av.className   = `pane-av ${avClass}`;

      $('pane-name').textContent = c.display_name || 'Unknown';
      $('pane-meta').textContent = c.channel || '—';

      const badge = $('pane-channel-badge');
      badge.textContent = (c.channel || '').replace('_', ' ');
      badge.className   = `ch-badge ch-${c.channel || 'PHONE'}`;

      $linkedJobBar.classList.remove('visible');
    }

    // Load full detail (enriches contact info + messages)
    await loadMessages(id);
    scrollMessages();
  }

  // ─────────────────────────────────────────
  // Messages
  // ─────────────────────────────────────────
  async function loadMessages(convoId) {
    $messagesArea.innerHTML = `<div class="loading-row"><span class="spin"></span> Loading messages…</div>`;

    try {
      const res  = await Auth.fetch(`/api/v1/communications/${convoId}/`);
      if (!res.ok) throw new Error();
      const data = await res.json();

      // Enrich activeConvo with full detail fields
      State.activeConvo = { ...State.activeConvo, ...data };
      State.messages    = data.messages || [];

      // Update pane meta with richer contact info
      $('pane-meta').textContent =
        data.contact_email || data.contact_phone || data.channel || '—';

      // Linked job
      if (data.jobs && data.jobs.length) {
        $linkedJobText.textContent = `Linked: Job #${data.jobs[0]}`;
        $linkedJobBar.classList.add('visible');
      }

      renderMessages();
    } catch {
      $messagesArea.innerHTML = `<div class="loading-row" style="color:#e8294a;">Could not load messages.</div>`;
    }
  }

  function renderMessages() {
    if (!State.messages.length) {
      $messagesArea.innerHTML = `
        <div class="empty-list" style="margin:auto;">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          <h4>No messages yet</h4>
          <p>Send the first message below.</p>
        </div>`;
      return;
    }

    let lastDate = null;
    const html   = [];

    State.messages.forEach(m => {
      const msgDate = new Date(m.created_at).toDateString();
      if (msgDate !== lastDate) {
        html.push(`<div class="msg-date-divider">${formatDate(m.created_at)}</div>`);
        lastDate = msgDate;
      }

      const dir    = m.direction === 'outbound' ? 'outbound' : 'inbound';
      const sender = dir === 'outbound'
        ? (m.sent_by_name || 'You')
        : (State.activeConvo?.display_name || 'Customer');
      const time   = formatTime(m.created_at);

      html.push(`
        <div class="msg-row ${dir}">
          <div class="msg-wrap">
            <div class="msg-bubble">${esc(m.body || '')}</div>
            <div class="msg-meta">${esc(sender)} · ${time}</div>
          </div>
        </div>`);
    });

    $messagesArea.innerHTML = html.join('');
  }

  function scrollMessages() {
    setTimeout(() => { $messagesArea.scrollTop = $messagesArea.scrollHeight; }, 50);
  }

  // ─────────────────────────────────────────
  // Reply
  // ─────────────────────────────────────────
  function bindReply() {
    $('btn-send').addEventListener('click', sendReply);
    $replyInput.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendReply(); }
    });
    $replyInput.addEventListener('input', () => {
      $replyInput.style.height = 'auto';
      $replyInput.style.height = Math.min($replyInput.scrollHeight, 120) + 'px';
    });
  }

  async function sendReply() {
    const body = $replyInput.value.trim();
    if (!body || !State.activeId) return;

    const btn = $('btn-send');
    btn.disabled = true;
    btn.innerHTML = `<span class="spin"></span>`;

    try {
      const res = await Auth.fetch(`/api/v1/communications/${State.activeId}/reply/`, {
        method  : 'POST',
        headers : { 'Content-Type': 'application/json' },
        body    : JSON.stringify({ body }),
      });
      if (!res.ok) throw new Error();

      $replyInput.value        = '';
      $replyInput.style.height = 'auto';

      // Optimistic render
      State.messages.push({
        id           : Date.now(),
        body,
        direction    : 'outbound',
        created_at   : new Date().toISOString(),
        sent_by_name : null,
      });
      renderMessages();
      scrollMessages();

      // Update sidebar preview
      const idx = State.conversations.findIndex(c => c.id === State.activeId);
      if (idx !== -1) {
        State.conversations[idx].last_message_preview = body;
        State.conversations[idx].last_message_at      = new Date().toISOString();
        applyFilters();
      }

      toast('Message sent', 'success');
    } catch {
      toast('Could not send message', 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
        Send`;
    }
  }

  // ─────────────────────────────────────────
  // Actions: Resolve / Assign / Link Job
  // ─────────────────────────────────────────
  function bindActions() {
    $('btn-resolve').addEventListener('click', resolveConvo);
    $('btn-assign').addEventListener('click', openAssignModal);
    $('btn-link-job').addEventListener('click', openLinkJobModal);
    $('btn-unlink-job').addEventListener('click', unlinkJob);
    $('btn-confirm-assign').addEventListener('click', confirmAssign);
    $('job-search-input').addEventListener('input', () => {
      clearTimeout(State.jobTimer);
      State.jobTimer = setTimeout(searchJobs, 380);
    });
  }

  async function resolveConvo() {
    if (!State.activeId) return;
    const btn = $('btn-resolve');
    btn.disabled = true;
    try {
      const res = await Auth.fetch(`/api/v1/communications/${State.activeId}/resolve/`, { method: 'POST' });
      if (!res.ok) throw new Error();
      State.conversations = State.conversations.filter(c => c.id !== State.activeId);
      State.activeId      = null;
      State.activeConvo   = null;
      $paneEmpty.style.display   = 'flex';
      $activeConvo.style.display = 'none';
      applyFilters();
      toast('Conversation resolved', 'success');
    } catch {
      toast('Could not resolve', 'error');
      btn.disabled = false;
    }
  }

  async function openAssignModal() {
    openModal('modal-assign');
    const sel = $('assign-select');
    sel.innerHTML = '<option value="">Loading…</option>';
    try {
      const res   = await Auth.fetch('/api/v1/accounts/users/');
      if (!res.ok) throw new Error();
      const data  = await res.json();
      const users = Array.isArray(data) ? data : (data.results || []);
      sel.innerHTML = '<option value="">Select agent…</option>' +
        users.map(u => `<option value="${u.id}">${esc(u.full_name || u.email)}</option>`).join('');
    } catch {
      sel.innerHTML = '<option value="">Could not load agents</option>';
    }
  }

  async function confirmAssign() {
    const userId = $('assign-select').value;
    if (!userId || !State.activeId) return;
    try {
      const res = await Auth.fetch(`/api/v1/communications/${State.activeId}/assign/`, {
        method  : 'POST',
        headers : { 'Content-Type': 'application/json' },
        body    : JSON.stringify({ user_id: parseInt(userId) }),
      });
      if (!res.ok) throw new Error();
      closeModal('modal-assign');
      toast('Conversation assigned', 'success');
    } catch {
      toast('Could not assign', 'error');
    }
  }

  function openLinkJobModal() {
    openModal('modal-link-job');
    $('job-search-input').value       = '';
    $('job-search-results').innerHTML = '';
  }

  async function searchJobs() {
    const q       = $('job-search-input').value.trim();
    const results = $('job-search-results');
    if (!q) { results.innerHTML = ''; return; }

    results.innerHTML = `<div class="loading-row"><span class="spin"></span></div>`;
    try {
      const res  = await Auth.fetch(`/api/v1/jobs/?search=${encodeURIComponent(q)}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      const jobs = Array.isArray(data) ? data : (data.results || []);

      if (!jobs.length) {
        results.innerHTML = `<div class="loading-row">No jobs found</div>`;
        return;
      }

      results.innerHTML = jobs.slice(0, 10).map(j => `
        <div class="job-result" onclick="Inbox.selectJob(${j.id}, '${esc(j.reference || '#' + j.id)}')">
          <div>
            <div class="job-result-ref">${esc(j.reference || '#' + j.id)}</div>
            <div class="job-result-meta">${esc(j.customer_name || '—')}</div>
          </div>
          <span class="s-badge s-${j.status || 'PENDING'}">${j.status || '—'}</span>
        </div>`).join('');
    } catch {
      results.innerHTML = `<div class="loading-row" style="color:#e8294a;">Search failed</div>`;
    }
  }

  async function selectJob(jobId, jobRef) {
    if (!State.activeId) return;
    try {
      const res = await Auth.fetch(`/api/v1/communications/${State.activeId}/link-job/`, {
        method  : 'POST',
        headers : { 'Content-Type': 'application/json' },
        body    : JSON.stringify({ job_id: jobId }),
      });
      if (!res.ok) throw new Error();
      $linkedJobText.textContent = `Linked: ${jobRef}`;
      $linkedJobBar.classList.add('visible');
      closeModal('modal-link-job');
      toast(`Linked to ${jobRef}`, 'success');
    } catch {
      toast('Could not link job', 'error');
    }
  }

  async function unlinkJob() {
    if (!State.activeId) return;
    try {
      const res = await Auth.fetch(`/api/v1/communications/${State.activeId}/link-job/`, {
        method  : 'POST',
        headers : { 'Content-Type': 'application/json' },
        body    : JSON.stringify({ job_id: null }),
      });
      if (!res.ok) throw new Error();
      $linkedJobBar.classList.remove('visible');
      toast('Job unlinked', 'info');
    } catch {
      toast('Could not unlink job', 'error');
    }
  }

  // ─────────────────────────────────────────
  // Channel tabs
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
      if (!State.activeId) return;
      try {
        const res  = await Auth.fetch(`/api/v1/communications/${State.activeId}/`);
        if (!res.ok) return;
        const data = await res.json();
        State.messages = data.messages || [];
        renderMessages();
        scrollMessages();
      } catch { /* silent */ }
    }, 15000);
  }

  // ─────────────────────────────────────────
  // Modal helpers
  // ─────────────────────────────────────────
  function openModal(id)  { document.getElementById(id)?.classList.add('open'); }
  function closeModal(id) { document.getElementById(id)?.classList.remove('open'); }

  function bindModalBackdrop() {
    document.querySelectorAll('.modal-overlay').forEach(el => {
      el.addEventListener('click', e => { if (e.target === el) el.classList.remove('open'); });
    });
  }

  // ─────────────────────────────────────────
  // Toast
  // ─────────────────────────────────────────
  function toast(msg, type = 'info') {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.innerHTML = `<span>${esc(msg)}</span>`;
    $('toast-container').appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  // ─────────────────────────────────────────
  // Helpers
  // ─────────────────────────────────────────
  function initials(name) {
    return (name || '?').split(' ').slice(0, 2).map(w => w[0]?.toUpperCase() || '').join('') || '?';
  }

  const AV_COLORS = ['av-yellow', 'av-red', 'av-green', 'av-blue', 'av-purple'];
  function pickAvColor(name) {
    let h = 0;
    for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h);
    return AV_COLORS[Math.abs(h) % AV_COLORS.length];
  }

  function truncate(str, len) {
    return str.length > len ? str.slice(0, len) + '…' : str;
  }

  function esc(str) {
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function formatTime(iso) {
    if (!iso) return '—';
    const d    = new Date(iso);
    const diff = Date.now() - d;
    if (diff < 60000)    return 'just now';
    if (diff < 3600000)  return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  }

  function formatDate(iso) {
    if (!iso) return '—';
    const d         = new Date(iso);
    const now       = new Date();
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    if (d.toDateString() === now.toDateString())       return 'Today';
    if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
  }

  function channelIcon(channel) {
    const icons = {
      WHATSAPP : `<svg class="convo-channel-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>`,
      EMAIL    : `<svg class="convo-channel-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>`,
      PHONE    : `<svg class="convo-channel-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 12 19.79 19.79 0 0 1 1.61 3.45a2 2 0 0 1 1.99-2.18h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L7.91 9.04a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7a2 2 0 0 1 1.72 2.03z"/></svg>`,
      WALK_IN  : `<svg class="convo-channel-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
    };
    return icons[channel] || '';
  }

  // ─────────────────────────────────────────
  // Public API
  // ─────────────────────────────────────────
  return { init, openConvo, selectJob, openModal, closeModal };

})();

document.addEventListener('DOMContentLoaded', Inbox.init);