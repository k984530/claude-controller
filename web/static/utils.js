/* ═══════════════════════════════════════════════
   Utility Functions
   ═══════════════════════════════════════════════ */

function showToast(message, type = 'success') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  const duration = type === 'error' ? 6000 : 3000;
  toast.className = `toast ${type}`;
  toast.style.setProperty('--toast-duration', `${duration}ms`);
  const icon = type === 'success'
    ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>'
    : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>';
  toast.innerHTML = `${icon} <span class="toast-msg">${escapeHtml(message)}</span><span class="toast-close">&times;</span>`;
  toast.addEventListener('click', () => {
    toast.style.animation = 'toastOut 0.2s ease forwards';
    setTimeout(() => { if (toast.parentNode) toast.remove(); }, 200);
  });
  container.appendChild(toast);
  setTimeout(() => { if (toast.parentNode) toast.remove(); }, duration);
}

function escapeHtml(str) {
  if (!str) return '';
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

/** JS 문자열 이스케이프 — onclick 핸들러 내 싱글쿼트 문자열에서 사용 */
function escapeJsStr(str) {
  if (!str) return '';
  return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

function truncate(str, len = 60) {
  if (!str) return '-';
  return str.length > len ? str.slice(0, len) + '...' : str;
}

function renderPromptHtml(prompt) {
  if (!prompt) return '-';
  const text = truncate(prompt, 200);
  const escaped = escapeHtml(text);
  return escaped.replace(/@(\/[^\s,]+|image\d+)/g, (match, ref) => {
    const isImage = ref.startsWith('image');
    const label = isImage ? ref : ref.split('/').pop();
    const icon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>';
    return `<span class="prompt-img-chip" title="${escapeHtml('@' + ref)}">${icon}${escapeHtml(label)}</span>`;
  });
}

function formatTime(ts) {
  if (!ts) return '-';
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return ts;
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  } catch { return ts; }
}

function formatCwd(cwd) {
  if (!cwd) return '-';
  const parts = cwd.replace(/\/$/, '').split('/');
  return parts[parts.length - 1] || cwd;
}

function formatElapsed(startTs) {
  if (!startTs) return '--:--';
  const start = new Date(startTs).getTime();
  if (isNaN(start)) return '--:--';
  const elapsed = Math.max(0, Math.floor((Date.now() - start) / 1000));
  const h = Math.floor(elapsed / 3600);
  const m = Math.floor((elapsed % 3600) / 60);
  const s = elapsed % 60;
  const pad = n => String(n).padStart(2, '0');
  if (h > 0) return `${h}:${pad(m)}:${pad(s)}`;
  return `${pad(m)}:${pad(s)}`;
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function getFileExt(filename) {
  const dot = filename.lastIndexOf('.');
  return dot >= 0 ? filename.slice(dot + 1).toUpperCase() : '?';
}

/* ── Desktop Notification ── */
function requestNotificationPermission() {
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
  }
}

function notifyJobDone(jobId, status, prompt) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  if (document.hasFocus()) return;
  const title = status === 'done' ? t('notify_job_done').replace('{id}', jobId) : t('notify_job_failed').replace('{id}', jobId);
  const body = truncate(prompt || '', 80);
  const icon = status === 'done'
    ? 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y="80" font-size="80">%E2%9C%85</text></svg>'
    : 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y="80" font-size="80">%E2%9D%8C</text></svg>';
  try {
    const n = new Notification(title, { body, icon, tag: `job-${jobId}` });
    n.onclick = () => { window.focus(); toggleJobExpand(String(jobId)); n.close(); };
    setTimeout(() => n.close(), 8000);
  } catch { /* silent */ }
}

/* ── Duration formatting ── */
function formatDuration(durationMs) {
  if (durationMs == null) return '';
  const sec = durationMs / 1000;
  return sec < 60 ? `${sec.toFixed(1)}s` : `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`;
}

/* ── Theme ── */
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('theme', theme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  applyTheme(current === 'dark' ? 'light' : 'dark');
}
