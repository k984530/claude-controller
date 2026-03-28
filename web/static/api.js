/* ═══════════════════════════════════════════════
   API & Service — 백엔드 연결, API 호출, 서비스 상태
   ═══════════════════════════════════════════════ */

const LOCAL_BACKEND = 'http://localhost:8420';
let API = '';
let AUTH_TOKEN = '';
let _backendConnected = false;
let serviceRunning = null;

async function apiFetch(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  if (AUTH_TOKEN) {
    headers['Authorization'] = `Bearer ${AUTH_TOKEN}`;
  }
  const resp = await fetch(`${API}${path}`, { ...options, headers });
  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    throw new Error(text || `HTTP ${resp.status}`);
  }
  const ct = resp.headers.get('content-type') || '';
  if (ct.includes('application/json')) return resp.json();
  return resp.text();
}

async function checkStatus() {
  try {
    const data = await apiFetch('/api/status');
    const running = data.running !== undefined ? data.running : (data.status === 'running');
    serviceRunning = running;
  } catch {
    serviceRunning = null;
  }
}

async function serviceAction(action) {
  const btn = document.getElementById(`btn${action.charAt(0).toUpperCase() + action.slice(1)}`);
  if (btn) btn.disabled = true;
  try {
    if (action === 'restart') {
      await apiFetch('/api/service/stop', { method: 'POST' });
      await new Promise(r => setTimeout(r, 500));
      await apiFetch('/api/service/start', { method: 'POST' });
    } else {
      await apiFetch(`/api/service/${action}`, { method: 'POST' });
    }
    showToast(t(action === 'start' ? 'msg_service_start' : action === 'stop' ? 'msg_service_stop' : 'msg_service_restart'));
    setTimeout(checkStatus, 1000);
  } catch (err) {
    showToast(`${t('msg_service_failed')}: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}
