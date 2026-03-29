/* ═══════════════════════════════════════════════
   API & Service — 백엔드 연결, API 호출, 서비스 상태
   ═══════════════════════════════════════════════ */

const LOCAL_BACKEND = 'http://localhost:8420';
let API = '';
let AUTH_TOKEN = '';
let _backendConnected = false;
let serviceRunning = null;

/* ── Connection health tracking ── */
let _connFailCount = 0;
const _CONN_FAIL_THRESHOLD = 3;
let _connBannerVisible = false;

function _updateConnBanner(ok) {
  if (ok) {
    if (_connFailCount > 0) _connFailCount = 0;
    if (_connBannerVisible) {
      _connBannerVisible = false;
      const banner = document.getElementById('connLostBanner');
      if (banner) banner.classList.remove('visible');
    }
  } else {
    _connFailCount++;
    if (_connFailCount >= _CONN_FAIL_THRESHOLD && !_connBannerVisible) {
      _connBannerVisible = true;
      const banner = document.getElementById('connLostBanner');
      if (banner) banner.classList.add('visible');
    }
  }
}

async function apiFetch(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  if (AUTH_TOKEN) {
    headers['Authorization'] = `Bearer ${AUTH_TOKEN}`;
  }
  let resp;
  try {
    resp = await fetch(`${API}${path}`, { ...options, headers });
  } catch (networkErr) {
    _updateConnBanner(false);
    throw networkErr;
  }
  _updateConnBanner(true);
  if (!resp.ok) {
    let msg = '';
    try {
      const ct = resp.headers.get('content-type') || '';
      if (ct.includes('application/json')) {
        const body = await resp.json();
        if (body.error && typeof body.error === 'object') {
          msg = body.error.message || JSON.stringify(body.error);
        } else {
          msg = body.error || body.message || JSON.stringify(body);
        }
      } else {
        msg = await resp.text();
      }
    } catch { /* parse fail — fall through */ }
    throw new Error(msg || `HTTP ${resp.status}`);
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

/* ── Goals API ── */
async function fetchGoals(status) {
  const qs = status ? `?status=${status}` : '';
  return apiFetch(`/api/goals${qs}`);
}
async function createGoal(objective, mode = 'gate', opts = {}) {
  return apiFetch('/api/goals', {
    method: 'POST',
    body: JSON.stringify({ objective, mode, ...opts }),
  });
}
async function getGoal(id) { return apiFetch(`/api/goals/${id}`); }
async function updateGoal(id, fields) {
  return apiFetch(`/api/goals/${id}/update`, {
    method: 'POST', body: JSON.stringify(fields),
  });
}
async function approveGoal(id) {
  return apiFetch(`/api/goals/${id}/approve`, { method: 'POST' });
}
async function cancelGoal(id) {
  return apiFetch(`/api/goals/${id}`, { method: 'DELETE' });
}

/* ── Memory API ── */
async function fetchMemories(params = {}) {
  const qs = new URLSearchParams(params).toString();
  return apiFetch(`/api/memory${qs ? '?' + qs : ''}`);
}
async function createMemory(data) {
  return apiFetch('/api/memory', {
    method: 'POST', body: JSON.stringify(data),
  });
}
async function getMemory(id) { return apiFetch(`/api/memory/${id}`); }
async function updateMemory(id, fields) {
  return apiFetch(`/api/memory/${id}/update`, {
    method: 'POST', body: JSON.stringify(fields),
  });
}
async function deleteMemory(id) {
  return apiFetch(`/api/memory/${id}`, { method: 'DELETE' });
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
