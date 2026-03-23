/**
 * Octos Week Greeter
 * Shows a personalised welcome banner on Monday mornings.
 * Appears once per user per week — tracked in localStorage.
 * Slides down from topbar, fades out after 60 seconds.
 */

(function () {
  'use strict';

  const MESSAGES = [
    (name) => `Good to see you back, ${name}. Let's make this week count.`,
    (name) => `Welcome back, ${name}. New week, fresh start — let's go.`,
    (name) => `Hey ${name} — the week is yours. Let's make it count.`,
    (name) => `Morning ${name}. A new week begins. Make it a good one.`,
    (name) => `Great to have you back, ${name}. This week is going to be great.`,
    (name) => `${name}, you showed up. That's already a win. Let's build on it.`,
    (name) => `New week, new jobs, new wins. Welcome back, ${name}.`,
  ];

  function _getISOWeek(date) {
    const d = new Date(date);
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() + 3 - ((d.getDay() + 6) % 7));
    const week1 = new Date(d.getFullYear(), 0, 4);
    return (
      d.getFullYear() +
      '-W' +
      String(
        1 + Math.round(((d - week1) / 86400000 - 3 + ((week1.getDay() + 6) % 7)) / 7)
      ).padStart(2, '0')
    );
  }

  function _shouldShow(userId) {
    const today = new Date();
    // Only on Monday (0=Sun, 1=Mon)
    if (today.getDay() !== 1) return false;

    const weekKey = `octos_monday_greeted_${userId}_${_getISOWeek(today)}`;
    if (localStorage.getItem(weekKey)) return false;

    // Mark as shown for this week
    localStorage.setItem(weekKey, '1');
    return true;
  }

  function _injectStyles() {
    if (document.getElementById('week-greeter-styles')) return;
    const style = document.createElement('style');
    style.id = 'week-greeter-styles';
    style.textContent = `
      #week-greeter {
        position        : fixed;
        top             : 0;
        left            : 0;
        right           : 0;
        z-index         : 9000;
        background      : linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
        color           : #ffffff;
        padding         : 0 28px;
        height          : 0;
        overflow        : hidden;
        display         : flex;
        align-items     : center;
        justify-content : center;
        gap             : 16px;
        transition      : height 0.4s cubic-bezier(0.34, 1.56, 0.64, 1),
                          opacity 0.4s ease;
        opacity         : 0;
        box-shadow      : 0 4px 24px rgba(0,0,0,0.18);
      }

      #week-greeter.open {
        height  : 52px;
        opacity : 1;
      }

      #week-greeter.closing {
        height  : 0;
        opacity : 0;
      }

      .week-greeter-left {
        display         : flex;
        align-items     : center;
        gap             : 12px;
        justify-content : center;
        flex            : 1;
        min-width       : 0;
      }

      .week-greeter-icon {
        font-size   : 20px;
        flex-shrink : 0;
        animation   : wg-wave 1.2s ease-in-out 0.5s 2;
      }

      @keyframes wg-wave {
        0%, 100% { transform: rotate(0deg); }
        25%      { transform: rotate(20deg); }
        75%      { transform: rotate(-10deg); }
      }

      .week-greeter-msg {
        font-family   : 'DM Sans', sans-serif;
        font-size     : 14px;
        font-weight   : 500;
        color         : rgba(255,255,255,0.92);
        white-space   : nowrap;
        overflow      : hidden;
        text-overflow : ellipsis;
      }

      .week-greeter-msg strong {
        color       : #ffffff;
        font-weight : 700;
      }

      .week-greeter-right {
        display     : flex;
        align-items : center;
        gap         : 12px;
        flex-shrink : 0;
      }

      .week-greeter-timer {
        font-family : 'JetBrains Mono', monospace;
        font-size   : 11px;
        color       : rgba(255,255,255,0.4);
        min-width   : 24px;
        text-align  : right;
      }

      .week-greeter-close {
        width           : 24px;
        height          : 24px;
        border-radius   : 50%;
        border          : 1px solid rgba(255,255,255,0.2);
        background      : transparent;
        color           : rgba(255,255,255,0.5);
        display         : flex;
        align-items     : center;
        justify-content : center;
        cursor          : pointer;
        font-size       : 14px;
        transition      : all 0.15s;
        flex-shrink     : 0;
        line-height     : 1;
      }
      .week-greeter-close:hover {
        border-color : rgba(255,255,255,0.5);
        color        : #ffffff;
        background   : rgba(255,255,255,0.1);
      }
    `;
    document.head.appendChild(style);
  }

  function _dismiss(banner, interval) {
    clearInterval(interval);
    banner.classList.remove('open');
    banner.classList.add('closing');
    setTimeout(() => banner.remove(), 450);
  }

  function _show(firstName) {
    _injectStyles();

    const msg      = MESSAGES[Math.floor(Math.random() * MESSAGES.length)](firstName);
    const banner   = document.createElement('div');
    banner.id      = 'week-greeter';

    banner.innerHTML = `
      <div class="week-greeter-left">
        <span class="week-greeter-icon">👋</span>
        <span class="week-greeter-msg">${msg}</span>
      </div>
      <div class="week-greeter-right">
        <span class="week-greeter-timer" id="wg-timer">60</span>
        <button class="week-greeter-close" id="wg-close" title="Dismiss">×</button>
      </div>
    `;

    document.body.appendChild(banner);

    // Trigger open animation
    requestAnimationFrame(() => {
      requestAnimationFrame(() => banner.classList.add('open'));
    });

    // Countdown timer
    let remaining = 60;
    const timerEl = document.getElementById('wg-timer');
    const interval = setInterval(() => {
      remaining--;
      if (timerEl) timerEl.textContent = remaining;
      if (remaining <= 0) _dismiss(banner, interval);
    }, 1000);

    // Manual close
    document.getElementById('wg-close').addEventListener('click', () => {
      _dismiss(banner, interval);
    });
  }

  /**
   * Public init — call after Auth is ready and user is loaded.
   * WeekGreeter.init()
   */
  window.WeekGreeter = {
    init: function () {
      try {
        const user = Auth.getUser();
        if (!user) return;

        const userId    = user.id || user.email || 'anon';
        const firstName = (user.first_name || user.full_name || 'there').split(' ')[0];

        if (!_shouldShow(userId)) return;

        // Small delay so page renders first
        setTimeout(() => _show(firstName), 300);
      } catch (e) {
        // Silent — greeter is non-critical
      }
    },
  };
})();