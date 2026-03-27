/* ═══════════════════════════════════════════════
   Controller Service Dashboard — Vanilla JS
   ═══════════════════════════════════════════════ */

// ── 자동 연결 설정 ──
const LOCAL_BACKEND = 'http://localhost:8420';
let API = '';          // same-origin이면 '', 원격이면 LOCAL_BACKEND
let AUTH_TOKEN = '';   // 토큰 (선택적)
let _backendConnected = false;
let expandedJobId = null;
let jobPollTimer = null;
let serviceRunning = null;

// ── Context Management ──
let _contextMode = 'new';       // 'new' | 'resume' | 'fork'
let _contextSessionId = null;
let _contextSessionPrompt = null;

// ── Stream State ──
// Per-job stream state: { offset, timer, done, jobData }
const streamState = {};

// ── Toast Notifications ──
function showToast(message, type = 'success') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  const icon = type === 'success'
    ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>'
    : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>';
  toast.innerHTML = `${icon} ${escapeHtml(message)}`;
  container.appendChild(toast);
  setTimeout(() => { if (toast.parentNode) toast.remove(); }, 3000);
}

// ── Utility ──
function escapeHtml(str) {
  if (!str) return '';
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

function truncate(str, len = 60) {
  if (!str) return '-';
  return str.length > len ? str.slice(0, len) + '...' : str;
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

// ── Context Management ──
function setContextMode(mode) {
  _contextMode = mode;
  _contextSessionId = null;
  _contextSessionPrompt = null;
  _updateContextUI();
  _closeSessionPicker();
}

function clearContext() { setContextMode('new'); }

function _updateContextUI() {
  document.getElementById('ctxNew').classList.toggle('active', _contextMode === 'new');
  document.getElementById('ctxResume').classList.toggle('active', _contextMode === 'resume');
  document.getElementById('ctxFork').classList.toggle('active', _contextMode === 'fork');
  const label = document.getElementById('ctxSessionLabel');
  if (_contextSessionId) {
    const tag = _contextMode === 'resume' ? 'resume' : 'fork';
    const shortId = _contextSessionId.slice(0, 8);
    const p = _contextSessionPrompt ? ' \u00b7 ' + _contextSessionPrompt.slice(0, 30) : '';
    label.textContent = tag + ' \u00b7 ' + shortId + p;
    label.style.display = 'inline-flex';
  } else {
    label.style.display = 'none';
  }
}

// 세션 데이터 캐시 (검색 필터링용)
let _sessionCache = [];
let _sessionAllCache = [];     // 프로젝트 필터 해제 시 전체 캐시
let _sessionProjectFilter = true; // true: 선택된 프로젝트만, false: 전체

function _formatCwdShort(cwd) {
  if (!cwd) return '';
  const parts = cwd.replace(/\/$/, '').split('/');
  return parts[parts.length - 1] || cwd;
}

function _renderSessionItem(s) {
  const statusClass = s.status || 'unknown';
  const jobLabel = s.job_id ? '#' + s.job_id : '';
  const cwdShort = _formatCwdShort(s.cwd);
  const costLabel = s.cost_usd != null ? '$' + Number(s.cost_usd).toFixed(4) : '';
  const timeLabel = s.timestamp ? s.timestamp.replace(/^\d{4}-/, '') : '';
  return '<div class="session-item" data-sid="' + escapeHtml(s.session_id)
    + '" data-prompt="' + escapeHtml(s.prompt || '') + '">'
    + '<div class="session-item-row">'
    + '<span class="session-item-status ' + escapeHtml(statusClass) + '"></span>'
    + '<span class="session-item-id">' + escapeHtml(s.session_id.slice(0, 8)) + '</span>'
    + (s.slug ? '<span class="session-item-slug">' + escapeHtml(s.slug) + '</span>' : '')
    + (jobLabel ? '<span class="session-item-job">' + escapeHtml(jobLabel) + '</span>' : '')
    + '<span class="session-item-prompt">' + escapeHtml(s.prompt || '(프롬프트 없음)') + '</span>'
    + '</div>'
    + '<div class="session-item-meta">'
    + '<span class="session-item-time">' + escapeHtml(timeLabel) + '</span>'
    + (cwdShort ? '<span class="session-item-cwd">' + escapeHtml(cwdShort) + '</span>' : '')
    + (costLabel ? '<span class="session-item-cost">' + escapeHtml(costLabel) + '</span>' : '')
    + '</div>'
    + '</div>';
}

function _renderSessionList(sessions, grouped) {
  const list = document.getElementById('sessionPickerList');
  if (!sessions || sessions.length === 0) {
    list.innerHTML = '<div class="session-empty"><div class="session-empty-icon">&#x1f4ad;</div>저장된 세션이 없습니다.</div>';
    return;
  }

  // 프로젝트 필터가 꺼져 있고 그룹핑 요청인 경우 → CWD 기준 그룹핑
  if (grouped) {
    const groups = {};
    const noProject = [];
    sessions.forEach(function(s) {
      if (s.cwd) {
        const key = s.cwd;
        if (!groups[key]) groups[key] = [];
        groups[key].push(s);
      } else {
        noProject.push(s);
      }
    });

    // 그룹을 최신 세션 기준으로 정렬
    const sortedKeys = Object.keys(groups).sort(function(a, b) {
      const aTs = groups[a][0] ? groups[a][0].timestamp || '' : '';
      const bTs = groups[b][0] ? groups[b][0].timestamp || '' : '';
      return bTs.localeCompare(aTs);
    });

    let html = '';
    sortedKeys.forEach(function(cwd) {
      const items = groups[cwd];
      const name = _formatCwdShort(cwd);
      html += '<div class="session-group-header">'
        + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>'
        + escapeHtml(name)
        + '<span class="session-group-count">' + items.length + '</span>'
        + '</div>';
      html += items.map(_renderSessionItem).join('');
    });

    if (noProject.length > 0) {
      html += '<div class="session-group-header">'
        + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
        + '프로젝트 미지정'
        + '<span class="session-group-count">' + noProject.length + '</span>'
        + '</div>';
      html += noProject.map(_renderSessionItem).join('');
    }

    list.innerHTML = html;
    return;
  }

  list.innerHTML = sessions.map(_renderSessionItem).join('');
}

function _filterSessions(query) {
  const useGrouped = !_sessionProjectFilter; // 전체 보기일 때만 그룹핑
  if (!query || !query.trim()) {
    _renderSessionList(_sessionCache, useGrouped);
    return;
  }
  const q = query.toLowerCase();
  const filtered = _sessionCache.filter(function(s) {
    return (s.prompt && s.prompt.toLowerCase().includes(q))
      || (s.session_id && s.session_id.toLowerCase().includes(q))
      || (s.job_id && String(s.job_id).includes(q))
      || (s.cwd && s.cwd.toLowerCase().includes(q));
  });
  _renderSessionList(filtered, useGrouped);
}

async function openSessionPicker(mode) {
  const picker = document.getElementById('sessionPicker');
  const wasOpen = picker.classList.contains('open');
  if (wasOpen && _contextMode === mode && !_contextSessionId) {
    _closeSessionPicker();
    setContextMode('new');
    return;
  }
  _contextMode = mode;
  _contextSessionId = null;
  _contextSessionPrompt = null;
  _updateContextUI();
  document.getElementById('sessionPickerTitle').textContent =
    mode === 'resume' ? '이어갈 세션 선택' : '분기할 세션 선택';
  const list = document.getElementById('sessionPickerList');
  list.innerHTML = '<div class="session-empty"><span class="spinner" style="display:block;margin:0 auto 8px;"></span>로드 중...</div>';
  // 검색 초기화
  const searchInput = document.getElementById('sessionSearchInput');
  if (searchInput) searchInput.value = '';
  picker.classList.add('open');

  // 선택된 cwd 확인 → 프로젝트 필터 적용
  const selectedCwd = document.getElementById('cwdInput').value || '';
  const filterBar = document.getElementById('sessionFilterBar');
  const filterBtn = document.getElementById('sessionFilterBtn');
  const filterProject = document.getElementById('sessionFilterProject');

  if (selectedCwd) {
    filterBar.style.display = 'flex';
    const projectName = _formatCwdShort(selectedCwd);
    filterProject.textContent = selectedCwd;
    _sessionProjectFilter = true;
    filterBtn.classList.add('active');
  } else {
    filterBar.style.display = 'none';
    _sessionProjectFilter = false;
  }

  try {
    // 프로젝트 필터가 활성화되면 cwd 기준으로 세션 로드
    if (selectedCwd && _sessionProjectFilter) {
      const [filtered, all] = await Promise.all([
        apiFetch('/api/sessions?cwd=' + encodeURIComponent(selectedCwd)),
        apiFetch('/api/sessions'),
      ]);
      _sessionCache = Array.isArray(filtered) ? filtered : [];
      _sessionAllCache = Array.isArray(all) ? all : [];
    } else {
      const sessions = await apiFetch('/api/sessions');
      _sessionCache = Array.isArray(sessions) ? sessions : [];
      _sessionAllCache = _sessionCache;
    }
    const useGrouped = !_sessionProjectFilter;
    _renderSessionList(_sessionCache, useGrouped);
  } catch (err) {
    const msg = err.message || '알 수 없는 오류';
    let displayMsg = msg;
    try {
      const parsed = JSON.parse(msg);
      if (parsed.error) displayMsg = parsed.error;
    } catch(_) {}
    list.innerHTML = '<div class="session-empty"><div class="session-empty-icon">&#x26a0;&#xfe0f;</div>세션 로드 실패<br><span style="font-size:0.7rem;color:var(--text-muted)">' + escapeHtml(displayMsg) + '</span></div>';
  }
}

function _toggleProjectFilter() {
  _sessionProjectFilter = !_sessionProjectFilter;
  const filterBtn = document.getElementById('sessionFilterBtn');
  filterBtn.classList.toggle('active', _sessionProjectFilter);
  // 캐시 전환
  if (_sessionProjectFilter) {
    // 필터된 결과로 전환
    const selectedCwd = document.getElementById('cwdInput').value || '';
    if (selectedCwd) {
      _sessionCache = _sessionAllCache.filter(function(s) {
        return s.cwd && s.cwd.replace(/\/$/, '') === selectedCwd.replace(/\/$/, '');
      });
    }
  } else {
    _sessionCache = _sessionAllCache;
  }
  // 검색어가 있으면 재필터
  const searchInput = document.getElementById('sessionSearchInput');
  _filterSessions(searchInput ? searchInput.value : '');
}

function _selectSession(sid, prompt) {
  _contextSessionId = sid;
  _contextSessionPrompt = prompt;
  _updateContextUI();
  _closeSessionPicker();
  showToast('\uc138\uc158 \uc120\ud0dd: ' + sid.slice(0, 8) + '...');
}

function _closeSessionPicker() {
  document.getElementById('sessionPicker').classList.remove('open');
}

document.addEventListener('click', function(e) {
  var item = e.target.closest('.session-item');
  if (item && item.dataset.sid) {
    _selectSession(item.dataset.sid, item.dataset.prompt || '');
    return;
  }
  var picker = document.getElementById('sessionPicker');
  if (picker && picker.classList.contains('open')
      && !e.target.closest('.ctx-toolbar') && !e.target.closest('.session-picker')) {
    _closeSessionPicker();
  }
});

// ── API Helpers ──
async function apiFetch(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  if (AUTH_TOKEN) {
    headers['Authorization'] = `Bearer ${AUTH_TOKEN}`;
  }
  try {
    const resp = await fetch(`${API}${path}`, { ...options, headers });
    if (!resp.ok) {
      const text = await resp.text().catch(() => '');
      throw new Error(text || `HTTP ${resp.status}`);
    }
    const ct = resp.headers.get('content-type') || '';
    if (ct.includes('application/json')) return resp.json();
    return resp.text();
  } catch (err) {
    throw err;
  }
}

// ── Service Status ──
async function checkStatus() {
  try {
    const data = await apiFetch('/api/status');
    const running = data.running !== undefined ? data.running : (data.status === 'running');
    serviceRunning = running;
  } catch {
    serviceRunning = null;
  }
}

// ── Service Actions ──
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
    showToast(`서비스 ${action === 'start' ? '시작' : action === 'stop' ? '중지' : '재시작'} 요청 완료`);
    setTimeout(checkStatus, 1000);
  } catch (err) {
    showToast(`서비스 ${action} 실패: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Attachments State ──
const attachments = [];

function updateAttachBadge() {
  // @imageN 이 textarea에 직접 삽입되므로 배지는 사용하지 않음
  document.getElementById('imgCountBadge').textContent = '';
}

function insertAtCursor(textarea, text) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const before = textarea.value.substring(0, start);
  const after = textarea.value.substring(end);
  // 앞에 공백이 없으면 추가
  const space = (before.length > 0 && !before.endsWith(' ') && !before.endsWith('\n')) ? ' ' : '';
  textarea.value = before + space + text + ' ' + after;
  const newPos = start + space.length + text.length + 1;
  textarea.selectionStart = textarea.selectionEnd = newPos;
  textarea.focus();
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

async function uploadFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const data = await apiFetch('/api/upload', {
          method: 'POST',
          body: JSON.stringify({ filename: file.name, data: reader.result }),
        });
        resolve(data);
      } catch (err) {
        reject(err);
      }
    };
    reader.onerror = () => reject(new Error('파일 읽기 실패'));
    reader.readAsDataURL(file);
  });
}

function removeAttachment(idx) {
  attachments[idx] = null;
  const container = document.getElementById('attachmentPreviews');
  const thumb = container.querySelector(`[data-idx="${idx}"]`);
  if (thumb) thumb.remove();
  // textarea에서 @imageN 참조도 제거
  const ta = document.getElementById('promptInput');
  ta.value = ta.value.replace(new RegExp(`\\s*@image${idx}\\b`, 'g'), '');
  updateAttachBadge();
}

function clearAttachments() {
  attachments.length = 0;
  document.getElementById('attachmentPreviews').innerHTML = '';
  updateAttachBadge();
}

function clearPromptForm() {
  document.getElementById('promptInput').value = '';
  clearAttachments();
  if (typeof clearDirSelection === 'function') clearDirSelection();
}

function openFilePicker() {
  document.getElementById('filePickerInput').click();
}

async function handleFiles(files) {
  const container = document.getElementById('attachmentPreviews');
  for (const file of files) {
    const isImage = file.type.startsWith('image/');
    const localUrl = isImage ? URL.createObjectURL(file) : null;

    const tempIdx = attachments.length;
    attachments.push({ localUrl, serverPath: null, filename: file.name, isImage, size: file.size });

    const thumb = document.createElement('div');
    thumb.dataset.idx = tempIdx;

    if (isImage) {
      thumb.className = 'img-thumb uploading';
      thumb.innerHTML = `<img src="${localUrl}" alt="${escapeHtml(file.name)}">
        <button class="img-remove" onclick="removeAttachment(${tempIdx})" title="제거">&times;</button>`;
    } else {
      thumb.className = 'file-thumb uploading';
      thumb.innerHTML = `
        <div class="file-icon">${escapeHtml(getFileExt(file.name))}</div>
        <div class="file-info">
          <div class="file-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</div>
          <div class="file-size">${formatFileSize(file.size)}</div>
        </div>
        <button class="file-remove" onclick="removeAttachment(${tempIdx})" title="제거">&times;</button>`;
    }
    container.appendChild(thumb);
    updateAttachBadge();

    try {
      const data = await uploadFile(file);
      attachments[tempIdx].serverPath = data.path;
      attachments[tempIdx].filename = data.filename || file.name;
      thumb.classList.remove('uploading');
      // textarea에 @imageN 삽입
      const ta = document.getElementById('promptInput');
      insertAtCursor(ta, `@image${tempIdx}`);
    } catch (err) {
      showToast(`업로드 실패: ${escapeHtml(file.name)} — ${err.message}`, 'error');
      attachments[tempIdx] = null;
      thumb.remove();
      updateAttachBadge();
    }
  }
}

// ── Send Lock (중복 전송 방지) ──
let _sendLock = false;

// ── Send Task ──
async function sendTask(e) {
  e.preventDefault();
  if (_sendLock) return false;

  const prompt = document.getElementById('promptInput').value.trim();
  if (!prompt) {
    showToast('프롬프트를 입력해주세요.', 'error');
    return false;
  }

  _sendLock = true;
  const cwd = document.getElementById('cwdInput').value.trim();
  const btn = document.getElementById('btnSend');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 전송 중...';

  try {
    // @imageN → @/actual/server/path 치환
    let finalPrompt = prompt;
    const filePaths = [];
    attachments.forEach((att, idx) => {
      if (att && att.serverPath) {
        finalPrompt = finalPrompt.replace(new RegExp(`@image${idx}\\b`, 'g'), `@${att.serverPath}`);
        filePaths.push(att.serverPath);
      }
    });

    const body = { prompt: finalPrompt };
    if (cwd) body.cwd = cwd;

    // Context mode: resume or fork adds session info
    if (_contextSessionId && (_contextMode === 'resume' || _contextMode === 'fork')) {
      body.session = _contextMode + ':' + _contextSessionId;
    }

    if (filePaths.length > 0) body.images = filePaths;

    await apiFetch('/api/send', { method: 'POST', body: JSON.stringify(body) });
    const modeMsg = _contextMode === 'resume' ? ' (resume)' : _contextMode === 'fork' ? ' (fork)' : '';
    showToast('\uc791\uc5c5\uc774 \uc804\uc1a1\ub418\uc5c8\uc2b5\ub2c8\ub2e4.' + modeMsg);
    if (cwd) addRecentDir(cwd);
    document.getElementById('promptInput').value = '';
    clearAttachments();
    clearContext();
    fetchJobs();
  } catch (err) {
    showToast(`전송 실패: ${err.message}`, 'error');
  } finally {
    _sendLock = false;
    btn.disabled = false;
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> 전송';
  }
  return false;
}

// ── Job List ──
function statusBadgeHtml(status) {
  const s = (status || 'unknown').toLowerCase();
  const labels = { running: '실행 중', done: '완료', failed: '실패', pending: '대기 중' };
  const cls = { running: 'badge-running', done: 'badge-done', failed: 'badge-failed', pending: 'badge-pending' };
  return `<span class="badge ${cls[s] || 'badge-pending'}">${labels[s] || s}</span>`;
}

function jobActionsHtml(id, status, sessionId) {
  const isRunning = status === 'running';
  let btns = '';
  if (!isRunning) {
    btns += `<button class="btn-retry-job" onclick="event.stopPropagation(); retryJob('${escapeHtml(id)}')" title="같은 프롬프트로 다시 실행"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg></button>`;
  }
  if (sessionId) {
    btns += `<button class="btn-continue-job" onclick="event.stopPropagation(); openFollowUp('${escapeHtml(id)}')" title="세션 이어서 명령 (resume)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="13 17 18 12 13 7"/><polyline points="6 17 11 12 6 7"/></svg></button>`;
    btns += `<button class="btn-fork-job" onclick="event.stopPropagation(); quickForkSession('${escapeHtml(sessionId)}')" title="이 세션에서 분기 (fork)" style="color:var(--yellow);"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><path d="M6 9v3c0 3.3 2.7 6 6 6h3"/></svg></button>`;
  }
  if (!isRunning) {
    btns += `<button class="btn-delete-job" onclick="event.stopPropagation(); deleteJob('${escapeHtml(id)}')" title="작업 제거"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></button>`;
  }
  if (!btns) return '';
  return `<div style="display:flex; align-items:center; gap:4px;">${btns}</div>`;
}

// 작업 목록에서 직접 fork 세션 선택
function quickForkSession(sessionId) {
  _contextMode = 'fork';
  _contextSessionId = sessionId;
  _contextSessionPrompt = null;
  _updateContextUI();
  showToast('Fork 모드로 전환됨 (' + sessionId.slice(0, 8) + '...). 새 프롬프트를 입력하세요.');
  document.getElementById('promptInput').focus();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function openFollowUp(jobId) {
  if (expandedJobId !== jobId) {
    toggleJobExpand(jobId);
    setTimeout(() => focusFollowUpInput(jobId), 200);
  } else {
    focusFollowUpInput(jobId);
  }
}

function focusFollowUpInput(jobId) {
  const input = document.getElementById(`followupInput-${jobId}`);
  if (input) {
    input.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    input.focus();
  }
}

async function sendFollowUp(jobId) {
  if (_sendLock) return;

  const input = document.getElementById(`followupInput-${jobId}`);
  if (!input) return;
  const prompt = input.value.trim();
  if (!prompt) {
    showToast('이어서 실행할 명령을 입력해주세요.', 'error');
    return;
  }

  const panel = document.getElementById(`streamPanel-${jobId}`);
  const sessionId = panel ? panel.dataset.sessionId : '';
  const cwd = panel ? panel.dataset.cwd : '';

  if (!sessionId) {
    showToast('세션 ID가 없어서 이어서 실행할 수 없습니다.', 'error');
    return;
  }

  _sendLock = true;
  const btn = input.nextElementSibling;
  const origHtml = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner" style="width:12px;height:12px;"></span>';

  try {
    const body = { prompt, session: `resume:${sessionId}` };
    if (cwd) body.cwd = cwd;

    await apiFetch('/api/send', { method: 'POST', body: JSON.stringify(body) });
    showToast('세션 이어서 명령이 전송되었습니다.');
    input.value = '';
    fetchJobs();
  } catch (err) {
    showToast(`전송 실패: ${err.message}`, 'error');
  } finally {
    _sendLock = false;
    btn.disabled = false;
    btn.innerHTML = origHtml;
  }
}

async function retryJob(jobId) {
  if (_sendLock) return;
  _sendLock = true;

  try {
    const data = await apiFetch('/api/jobs');
    const jobs = Array.isArray(data) ? data : (data.jobs || []);
    const job = jobs.find(j => String(j.id || j.job_id) === String(jobId));
    if (!job || !job.prompt) {
      showToast('원본 프롬프트를 찾을 수 없습니다.', 'error');
      return;
    }

    const body = { prompt: job.prompt };
    if (job.cwd) body.cwd = job.cwd;

    await apiFetch('/api/send', { method: 'POST', body: JSON.stringify(body) });
    showToast('같은 프롬프트로 다시 실행되었습니다.');
    fetchJobs();
  } catch (err) {
    showToast(`재실행 실패: ${err.message}`, 'error');
  } finally {
    _sendLock = false;
  }
}

async function fetchJobs() {
  try {
    const data = await apiFetch('/api/jobs');
    const jobs = Array.isArray(data) ? data : (data.jobs || []);
    renderJobs(jobs);
  } catch {
    // silent fail for polling
  }
}


function renderJobs(jobs) {
  const tbody = document.getElementById('jobTableBody');
  const countEl = document.getElementById('jobCount');
  countEl.textContent = jobs.length > 0 ? `(${jobs.length}건)` : '';

  if (jobs.length === 0) {
    tbody.innerHTML = `<tr data-job-id="__empty__"><td colspan="7" class="empty-state">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width:40px;height:40px;margin-bottom:12px;opacity:0.3;"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
      <div>작업이 없습니다</div>
    </td></tr>`;
    return;
  }

  jobs.sort((a, b) => {
    const aRunning = a.status === 'running' ? 0 : 1;
    const bRunning = b.status === 'running' ? 0 : 1;
    if (aRunning !== bRunning) return aRunning - bRunning;
    return (parseInt(b.id || b.job_id || 0)) - (parseInt(a.id || a.job_id || 0));
  });

  for (const job of jobs) {
    const id = job.id || job.job_id || '-';
    if (streamState[id]) {
      streamState[id].jobData = job;
    }
  }

  const existingRows = {};
  for (const row of tbody.querySelectorAll('tr[data-job-id]')) {
    existingRows[row.dataset.jobId] = row;
  }

  const newIds = [];
  for (const job of jobs) {
    const id = job.id || job.job_id || '-';
    newIds.push(id);
    if (expandedJobId === id) newIds.push(id + '__expand');
  }

  const emptyRow = tbody.querySelector('tr[data-job-id="__empty__"]');
  if (emptyRow) emptyRow.remove();

  for (const job of jobs) {
    const id = job.id || job.job_id || '-';
    const isExpanded = expandedJobId === id;
    const existing = existingRows[id];

    if (existing && !existing.classList.contains('expand-row')) {
      const cells = existing.querySelectorAll('td');
      if (cells.length >= 7) {
        const newStatus = statusBadgeHtml(job.status);
        if (cells[1].innerHTML !== newStatus) cells[1].innerHTML = newStatus;
        const newCwd = escapeHtml(formatCwd(job.cwd));
        if (cells[3].innerHTML !== newCwd) {
          cells[3].innerHTML = newCwd;
          cells[3].title = job.cwd || '';
        }
        const newSession = job.session_id ? job.session_id.slice(0, 8) : '-';
        if (cells[4].textContent !== newSession) cells[4].textContent = newSession;
        if (job.session_id) cells[4].title = job.session_id;
        const newActions = jobActionsHtml(id, job.status, job.session_id);
        if (cells[6].innerHTML !== newActions) {
          cells[6].innerHTML = newActions;
        }
      }
      existing.className = isExpanded ? 'expanded' : '';
      delete existingRows[id];
    } else if (!existing) {
      const tr = document.createElement('tr');
      tr.dataset.jobId = id;
      tr.className = isExpanded ? 'expanded' : '';
      tr.setAttribute('onclick', `toggleJobExpand('${escapeHtml(id)}')`);
      tr.innerHTML = `
        <td class="job-id">${escapeHtml(String(id).slice(0, 8))}</td>
        <td>${statusBadgeHtml(job.status)}</td>
        <td class="prompt-cell" title="${escapeHtml(job.prompt)}">${escapeHtml(truncate(job.prompt))}</td>
        <td class="job-cwd" title="${escapeHtml(job.cwd || '')}">${escapeHtml(formatCwd(job.cwd))}</td>
        <td class="job-session" title="${escapeHtml(job.session_id || '')}">${job.session_id ? escapeHtml(job.session_id.slice(0, 8)) : '-'}</td>
        <td class="job-time">${formatTime(job.created || job.created_at)}</td>
        <td>${jobActionsHtml(id, job.status, job.session_id)}</td>`;
      tbody.appendChild(tr);
    } else {
      delete existingRows[id];
    }

    const expandKey = id + '__expand';
    const existingExpand = existingRows[expandKey] || tbody.querySelector(`tr[data-job-id="${CSS.escape(expandKey)}"]`);

    if (isExpanded) {
      if (!existingExpand) {
        const expandTr = document.createElement('tr');
        expandTr.className = 'expand-row';
        expandTr.dataset.jobId = expandKey;
        const sessionId = job.session_id || '';
        const jobCwd = job.cwd || '';
        expandTr.innerHTML = `<td colspan="7">
          <div class="stream-panel" id="streamPanel-${escapeHtml(id)}" data-session-id="${escapeHtml(sessionId)}" data-cwd="${escapeHtml(jobCwd)}">
            <div class="stream-content" id="streamContent-${escapeHtml(id)}">
              <div class="stream-empty">
                ${job.status === 'running' ? '<div class="stream-spinner" style="margin:0 auto 8px;"></div>' : ''}
                스트림 데이터를 불러오는 중...
              </div>
            </div>
            ${job.status === 'done' ? '<div class="stream-done-banner">✓ 작업 완료</div>' : ''}
            ${job.status === 'failed' ? '<div class="stream-done-banner failed">✗ 작업 실패</div>' : ''}
            ${job.status !== 'running' ? `<div class="stream-actions"><button class="btn btn-sm" onclick="event.stopPropagation(); retryJob('${escapeHtml(id)}')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg> 다시 실행</button><button class="btn btn-sm" onclick="event.stopPropagation(); copyStreamResult('${escapeHtml(id)}')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> 전체 복사</button><button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); deleteJob('${escapeHtml(id)}')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg> 작업 제거</button></div>` : ''}
            ${(job.status !== 'running' && sessionId) ? `<div class="stream-followup"><span class="stream-followup-label">이어서</span><div class="followup-input-wrap"><input type="text" class="followup-input" id="followupInput-${escapeHtml(id)}" placeholder="이 세션에 이어서 실행할 명령..." onkeydown="if(event.key==='Enter'){event.stopPropagation();sendFollowUp('${escapeHtml(id)}')}" onclick="event.stopPropagation()"><button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); sendFollowUp('${escapeHtml(id)}')" style="white-space:nowrap;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> 전송</button></div></div>` : ''}
          </div>
        </td>`;
        const jobRow = tbody.querySelector(`tr[data-job-id="${CSS.escape(id)}"]`);
        if (jobRow && jobRow.nextSibling) {
          tbody.insertBefore(expandTr, jobRow.nextSibling);
        } else {
          tbody.appendChild(expandTr);
        }
        initStream(id);
      } else {
        delete existingRows[expandKey];
      }
    } else if (existingExpand) {
      existingExpand.remove();
      delete existingRows[expandKey];
    }
  }

  for (const [key, row] of Object.entries(existingRows)) {
    row.remove();
  }

  const currentOrder = [...tbody.querySelectorAll('tr[data-job-id]')].map(r => r.dataset.jobId);
  if (JSON.stringify(currentOrder) !== JSON.stringify(newIds)) {
    for (const nid of newIds) {
      const row = tbody.querySelector(`tr[data-job-id="${CSS.escape(nid)}"]`);
      if (row) tbody.appendChild(row);
    }
  }

  const hasCompleted = jobs.some(j => j.status === 'done' || j.status === 'failed');
  const deleteBtn = document.getElementById('btnDeleteCompleted');
  deleteBtn.style.display = hasCompleted ? 'inline-flex' : 'none';
}

function updateJobRowStatus(jobId, status) {
  const tbody = document.getElementById('jobTableBody');
  const row = tbody.querySelector(`tr[data-job-id="${CSS.escape(jobId)}"]`);
  if (!row || row.classList.contains('expand-row')) return;
  const cells = row.querySelectorAll('td');
  if (cells.length >= 2) {
    const newBadge = statusBadgeHtml(status);
    if (cells[1].innerHTML !== newBadge) cells[1].innerHTML = newBadge;
  }
}

function toggleJobExpand(id) {
  const tbody = document.getElementById('jobTableBody');
  if (expandedJobId === id) {
    stopStream(expandedJobId);
    const expandRow = tbody.querySelector(`tr[data-job-id="${CSS.escape(id + '__expand')}"]`);
    if (expandRow) expandRow.remove();
    const jobRow = tbody.querySelector(`tr[data-job-id="${CSS.escape(id)}"]`);
    if (jobRow) jobRow.className = '';
    expandedJobId = null;
  } else {
    if (expandedJobId) {
      stopStream(expandedJobId);
      const prevExpand = tbody.querySelector(`tr[data-job-id="${CSS.escape(expandedJobId + '__expand')}"]`);
      if (prevExpand) prevExpand.remove();
      const prevRow = tbody.querySelector(`tr[data-job-id="${CSS.escape(expandedJobId)}"]`);
      if (prevRow) prevRow.className = '';
    }
    expandedJobId = id;
    fetchJobs();
  }
}

// ── Stream Polling ──
function initStream(jobId) {
  if (streamState[jobId] && streamState[jobId].timer) return;

  if (!streamState[jobId]) {
    streamState[jobId] = { offset: 0, timer: null, done: false, jobData: null, events: [] };
  }

  const state = streamState[jobId];
  if (state.done && state.events.length > 0) {
    renderStreamEvents(jobId);
    return;
  }

  pollStream(jobId);
  state.timer = setInterval(() => pollStream(jobId), 500);
}

function stopStream(jobId) {
  const state = streamState[jobId];
  if (!state) return;
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
}


async function pollStream(jobId) {
  const state = streamState[jobId];
  if (!state || state.done) {
    stopStream(jobId);
    return;
  }

  try {
    const data = await apiFetch(`/api/jobs/${encodeURIComponent(jobId)}/stream?offset=${state.offset}`);
    const events = data.events || [];
    const newOffset = data.offset !== undefined ? data.offset : state.offset + events.length;
    const done = !!data.done;

    if (events.length > 0) {
      state.events = state.events.concat(events);
      state.offset = newOffset;
      renderStreamEvents(jobId);
    }

    if (done) {
      state.done = true;
      stopStream(jobId);
      renderStreamDone(jobId);
      updateJobRowStatus(jobId, state.jobData ? state.jobData.status : 'done');
    }
  } catch {
    // Network error — keep retrying silently
  }
}

function renderStreamEvents(jobId) {
  const container = document.getElementById(`streamContent-${jobId}`);
  if (!container) return;

  const state = streamState[jobId];
  if (!state || state.events.length === 0) return;

  const wasAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 40;

  let html = '';
  for (const evt of state.events) {
    const type = (evt.type || 'text').toLowerCase();
    switch (type) {
      case 'tool_use':
        html += `<div class="stream-event stream-event-tool">
          <span class="stream-tool-badge">${escapeHtml(evt.tool || 'Tool')}</span>
          <span class="stream-tool-input">${escapeHtml(typeof evt.input === 'string' ? evt.input : JSON.stringify(evt.input || ''))}</span>
        </div>`;
        break;
      case 'result':
        html += `<div class="stream-event stream-event-result">
          <span class="stream-result-icon">✓</span>
          <span class="stream-result-text">${escapeHtml(typeof evt.result === 'string' ? evt.result : JSON.stringify(evt.result || ''))}</span>
        </div>`;
        if (evt.session_id) {
          const panel = document.getElementById(`streamPanel-${jobId}`);
          if (panel) panel.dataset.sessionId = evt.session_id;
        }
        break;
      case 'error':
        html += `<div class="stream-event stream-event-error">
          <span class="stream-error-icon">✗</span>
          <span class="stream-error-text">${escapeHtml(evt.text || evt.error || evt.message || 'Unknown error')}</span>
        </div>`;
        break;
      case 'text':
      default:
        html += `<div class="stream-event stream-event-text">${escapeHtml(evt.text || '')}</div>`;
        break;
    }
  }

  container.innerHTML = html;

  if (wasAtBottom) {
    container.scrollTop = container.scrollHeight;
  }
}

function renderStreamDone(jobId) {
  const panel = document.getElementById(`streamPanel-${jobId}`);
  if (!panel) return;

  const state = streamState[jobId];
  const status = state && state.jobData ? state.jobData.status : 'done';
  const isFailed = status === 'failed';

  let banner = panel.querySelector('.stream-done-banner');
  if (!banner) {
    banner = document.createElement('div');
    banner.className = `stream-done-banner${isFailed ? ' failed' : ''}`;
    banner.textContent = isFailed ? '✗ 작업 실패' : '✓ 작업 완료';
    panel.appendChild(banner);
  }

  let actions = panel.querySelector('.stream-actions');
  if (!actions) {
    actions = document.createElement('div');
    actions.className = 'stream-actions';
    actions.innerHTML = `
      <button class="btn btn-sm" onclick="event.stopPropagation(); copyStreamResult('${escapeHtml(jobId)}')">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
        전체 복사
      </button>
      <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); deleteJob('${escapeHtml(jobId)}')">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
        작업 제거
      </button>`;
    panel.appendChild(actions);
  }

  const sessionId = panel.dataset.sessionId;
  if (sessionId && !panel.querySelector('.stream-followup')) {
    const followup = document.createElement('div');
    followup.className = 'stream-followup';
    followup.innerHTML = `
      <span class="stream-followup-label">이어서</span>
      <div class="followup-input-wrap">
        <input type="text" class="followup-input" id="followupInput-${escapeHtml(jobId)}"
               placeholder="이 세션에 이어서 실행할 명령..."
               onkeydown="if(event.key==='Enter'){event.stopPropagation();sendFollowUp('${escapeHtml(jobId)}')}"
               onclick="event.stopPropagation()">
        <button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); sendFollowUp('${escapeHtml(jobId)}')" style="white-space:nowrap;">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> 전송
        </button>
      </div>`;
    panel.appendChild(followup);
  }
}

// ── Copy Stream Result ──
function copyStreamResult(jobId) {
  const state = streamState[jobId];
  if (!state || state.events.length === 0) {
    showToast('복사할 결과가 없습니다.', 'error');
    return;
  }

  const textParts = [];
  for (const evt of state.events) {
    const type = (evt.type || 'text').toLowerCase();
    switch (type) {
      case 'text':
        if (evt.text) textParts.push(evt.text);
        break;
      case 'result':
        const r = typeof evt.result === 'string' ? evt.result : JSON.stringify(evt.result || '');
        if (r) textParts.push(`[Result] ${r}`);
        break;
      case 'tool_use':
        const toolName = evt.tool || 'Tool';
        const toolInput = typeof evt.input === 'string' ? evt.input : JSON.stringify(evt.input || '');
        textParts.push(`[${toolName}] ${toolInput}`);
        break;
      case 'error':
        const errMsg = evt.text || evt.error || evt.message || 'Unknown error';
        textParts.push(`[Error] ${errMsg}`);
        break;
    }
  }

  const text = textParts.join('\n').trim();
  if (!text) {
    showToast('복사할 텍스트 결과가 없습니다.', 'error');
    return;
  }

  navigator.clipboard.writeText(text).then(() => {
    showToast('결과가 클립보드에 복사되었습니다.');
  }).catch(() => {
    showToast('클립보드 복사에 실패했습니다.', 'error');
  });
}

// ── Delete Individual Job ──
async function deleteJob(jobId) {
  try {
    await apiFetch(`/api/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' });
    if (streamState[jobId]) {
      stopStream(jobId);
      delete streamState[jobId];
    }
    if (expandedJobId === jobId) expandedJobId = null;
    showToast('작업이 제거되었습니다.');
    fetchJobs();
  } catch (err) {
    showToast(`제거 실패: ${err.message}`, 'error');
  }
}

// ── Delete All Completed Jobs ──
async function deleteCompletedJobs() {
  try {
    const data = await apiFetch('/api/jobs', { method: 'DELETE' });
    const count = data.count || 0;
    for (const id of (data.deleted || [])) {
      if (streamState[id]) {
        stopStream(id);
        delete streamState[id];
      }
      if (expandedJobId === id) expandedJobId = null;
    }
    showToast(`${count}개 완료 작업이 제거되었습니다.`);
    fetchJobs();
  } catch (err) {
    showToast(`일괄 제거 실패: ${err.message}`, 'error');
  }
}

// ── CWD badge ──
function updateCwdBadge(path) {
  const badge = document.getElementById('cwdBadge');
  if (!badge) return;
  if (!path) {
    badge.textContent = '';
    return;
  }
  const parts = path.replace(/\/+$/, '').split('/');
  const folderName = parts[parts.length - 1] || path;
  badge.textContent = folderName;
  badge.title = path;
}

// ── Recent Directories ──
const MAX_RECENT_DIRS = 8;
let _recentDirsCache = [];

function getRecentDirs() {
  return _recentDirsCache;
}

async function loadRecentDirs() {
  try {
    const res = await apiFetch('/api/recent-dirs');
    _recentDirsCache = Array.isArray(res) ? res : [];
  } catch { _recentDirsCache = []; }
  renderRecentDirs();
}

function _saveRecentDirs() {
  apiFetch('/api/recent-dirs', {
    method: 'POST',
    body: JSON.stringify({ dirs: _recentDirsCache })
  }).catch(() => {});
}

function addRecentDir(path) {
  if (!path) return;
  _recentDirsCache = _recentDirsCache.filter(d => d !== path);
  _recentDirsCache.unshift(path);
  if (_recentDirsCache.length > MAX_RECENT_DIRS) _recentDirsCache = _recentDirsCache.slice(0, MAX_RECENT_DIRS);
  _saveRecentDirs();
  renderRecentDirs();
}

function removeRecentDir(path) {
  _recentDirsCache = _recentDirsCache.filter(d => d !== path);
  _saveRecentDirs();
  if (document.getElementById('cwdInput').value === path) {
    clearDirSelection();
  }
  renderRecentDirs();
}

function renderRecentDirs() {
  const container = document.getElementById('recentDirs');
  const dirs = _recentDirsCache;
  const currentCwd = document.getElementById('cwdInput').value;

  if (dirs.length === 0) {
    container.innerHTML = '';
    return;
  }

  let html = '<span class="recent-dirs-label">최근</span>';
  html += dirs.map(dir => {
    const parts = dir.replace(/\/+$/, '').split('/');
    const name = parts[parts.length - 1] || dir;
    const isActive = dir === currentCwd ? ' active' : '';
    const escapedDir = dir.replace(/'/g, "\\'");
    return `<span class="recent-chip${isActive}" onclick="selectRecentDir('${escapedDir}')" title="${dir}">
      <span class="recent-chip-name">${name}</span>
      <button class="recent-chip-remove" onclick="event.stopPropagation(); removeRecentDir('${escapedDir}')" title="제거">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </span>`;
  }).join('');

  container.innerHTML = html;
}

function selectRecentDir(path) {
  document.getElementById('cwdInput').value = path;
  updateCwdBadge(path);
  const text = document.getElementById('dirPickerText');
  text.textContent = path;
  document.getElementById('dirPickerDisplay').classList.add('has-value');
  document.getElementById('dirPickerClear').classList.add('visible');
  renderRecentDirs();
  if (dirBrowserOpen) {
    browseTo(path);
  } else {
    dirBrowserCurrentPath = path;
  }
}

// ── Inline Directory Browser ──
let dirBrowserCurrentPath = '';
let dirBrowserOpen = false;

function toggleDirBrowser() {
  if (dirBrowserOpen) {
    closeDirBrowser();
  } else {
    openDirBrowser();
  }
}

function openDirBrowser() {
  const panel = document.getElementById('dirBrowserPanel');
  const chevron = document.getElementById('dirPickerChevron');
  const currentCwd = document.getElementById('cwdInput').value;
  const startPath = currentCwd || '~';

  panel.classList.add('open');
  if (chevron) chevron.style.transform = 'rotate(180deg)';
  dirBrowserOpen = true;
  browseTo(startPath);
}

function closeDirBrowser() {
  const panel = document.getElementById('dirBrowserPanel');
  const chevron = document.getElementById('dirPickerChevron');
  if (panel) panel.classList.remove('open');
  if (chevron) chevron.style.transform = '';
  dirBrowserOpen = false;
}

async function browseTo(path) {
  const list = document.getElementById('dirList');
  const breadcrumb = document.getElementById('dirBreadcrumb');
  const currentDisplay = document.getElementById('dirCurrentPath');

  list.innerHTML = '<div class="dir-modal-loading"><span class="spinner"></span> 불러오는 중...</div>';

  try {
    const data = await apiFetch(`/api/dirs?path=${encodeURIComponent(path)}`);
    dirBrowserCurrentPath = data.current;
    currentDisplay.textContent = data.current;
    currentDisplay.title = data.current;

    document.getElementById('cwdInput').value = data.current;
    document.getElementById('dirPickerText').textContent = data.current;
    document.getElementById('dirPickerDisplay').classList.add('has-value');
    document.getElementById('dirPickerClear').classList.add('visible');

    renderBreadcrumb(data.current, breadcrumb);

    const dirs = data.entries.filter(e => e.type === 'dir');
    if (dirs.length === 0) {
      list.innerHTML = '<div class="dir-modal-loading" style="color:var(--text-muted);">하위 디렉토리가 없습니다</div>';
      return;
    }

    list.innerHTML = dirs.map(entry => {
      const isParent = entry.name === '..';
      const icon = isParent
        ? '<svg class="dir-item-icon is-parent" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>'
        : '<svg class="dir-item-icon is-dir" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>';
      const label = isParent ? '상위 디렉토리' : entry.name;
      return `<div class="dir-item" onclick="browseTo('${entry.path.replace(/'/g, "\\'")}')">
        ${icon}
        <span class="dir-item-name is-dir">${label}</span>
      </div>`;
    }).join('');

  } catch (err) {
    list.innerHTML = `<div class="dir-modal-loading" style="color:var(--red);">불러오기 실패: ${err.message}</div>`;
  }
}

function renderBreadcrumb(fullPath, container) {
  const parts = fullPath.split('/').filter(Boolean);
  let html = `<span class="breadcrumb-seg" onclick="browseTo('/')">/</span>`;
  let accumulated = '';
  for (const part of parts) {
    accumulated += '/' + part;
    const p = accumulated;
    html += `<span class="breadcrumb-sep">/</span><span class="breadcrumb-seg" onclick="browseTo('${p.replace(/'/g, "\\'")}')">${part}</span>`;
  }
  container.innerHTML = html;
}

function selectCurrentDir() {
  if (!dirBrowserCurrentPath) return;
  document.getElementById('cwdInput').value = dirBrowserCurrentPath;
  updateCwdBadge(dirBrowserCurrentPath);

  const text = document.getElementById('dirPickerText');
  text.textContent = dirBrowserCurrentPath;
  document.getElementById('dirPickerDisplay').classList.add('has-value');
  document.getElementById('dirPickerClear').classList.add('visible');

  addRecentDir(dirBrowserCurrentPath);
  closeDirBrowser();
}

function clearDirSelection() {
  document.getElementById('cwdInput').value = '';
  updateCwdBadge('');
  const text = document.getElementById('dirPickerText');
  text.textContent = '디렉토리를 선택하세요...';
  document.getElementById('dirPickerDisplay').classList.remove('has-value');
  document.getElementById('dirPickerClear').classList.remove('visible');
  renderRecentDirs();
}

// ESC 키로 패널 닫기
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    closeDirBrowser();
  }
});

// ── Refresh All ──
function refreshAll() {
  checkStatus();
  fetchJobs();
  showToast('전체 새로고침 완료');
}

// ── Initialize ──
async function autoConnect() {
  const connFab = document.getElementById('connFab');
  const isSameOrigin = location.hostname === 'localhost' || location.hostname === '127.0.0.1';

  if (isSameOrigin) {
    // 로컬 서빙 — same-origin 모드
    API = '';
    _backendConnected = true;
  } else {
    // 원격 배포 (claude.won-space.com 등) — localhost 자동 감지
    try {
      const resp = await fetch(`${LOCAL_BACKEND}/api/status`, { signal: AbortSignal.timeout(3000) });
      if (resp.ok) {
        API = LOCAL_BACKEND;
        _backendConnected = true;
      }
    } catch {
      _backendConnected = false;
    }
  }

  if (connFab) {
    if (_backendConnected) {
      connFab.classList.add('connected');
      connFab.title = '로컬 서버 연결됨';
    } else {
      connFab.classList.remove('connected');
      connFab.title = '로컬 서버 연결 안됨 — 서버를 시작하세요';
    }
  }
}

async function init() {
  await autoConnect();
  loadRecentDirs();
  checkStatus();
  fetchJobs();

  jobPollTimer = setInterval(fetchJobs, 3000);
  setInterval(checkStatus, 10000);

  document.getElementById('promptInput').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      document.getElementById('sendForm').dispatchEvent(new Event('submit'));
    }
  });

  // ── File Drag & Drop ──
  const wrapper = document.getElementById('promptWrapper');
  let dragCounter = 0;

  wrapper.addEventListener('dragenter', function(e) {
    e.preventDefault();
    dragCounter++;
    wrapper.classList.add('drag-over');
  });

  wrapper.addEventListener('dragover', function(e) {
    e.preventDefault();
  });

  wrapper.addEventListener('dragleave', function(e) {
    e.preventDefault();
    dragCounter--;
    if (dragCounter <= 0) {
      dragCounter = 0;
      wrapper.classList.remove('drag-over');
    }
  });

  wrapper.addEventListener('drop', function(e) {
    e.preventDefault();
    dragCounter = 0;
    wrapper.classList.remove('drag-over');
    if (e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  });

  // ── Clipboard Paste ──
  document.getElementById('promptInput').addEventListener('paste', function(e) {
    const files = e.clipboardData?.files;
    if (files && files.length > 0) {
      handleFiles(files);
    }
  });

  // ── File Picker ──
  document.getElementById('filePickerInput').addEventListener('change', function(e) {
    if (e.target.files.length > 0) {
      handleFiles(e.target.files);
      e.target.value = '';
    }
  });
}

// ── Settings ──
let _settingsData = {};
let _settingsDirty = false;

function openSettings() {
  loadSettings().then(() => {
    document.getElementById('settingsOverlay').classList.add('open');
  });
}

function closeSettings() {
  document.getElementById('settingsOverlay').classList.remove('open');
  _settingsDirty = false;
  document.getElementById('settingsRestartHint').style.display = 'none';
}

async function loadSettings() {
  try {
    const resp = await fetch(API + '/api/config');
    _settingsData = await resp.json();
  } catch {
    _settingsData = {};
  }
  _populateSettingsUI();
}

function _populateSettingsUI() {
  const d = _settingsData;
  document.getElementById('cfgSkipPerms').checked = d.skip_permissions !== false;
  document.getElementById('cfgAllowedTools').value = d.allowed_tools || '';
  document.getElementById('cfgModel').value = d.model || '';
  document.getElementById('cfgMaxJobs').value = d.max_jobs || 10;
  document.getElementById('cfgSystemPrompt').value = d.append_system_prompt || '';
  document.getElementById('cfgTargetRepo').value = d.target_repo || '';
  document.getElementById('cfgBaseBranch').value = d.base_branch || 'main';
  document.getElementById('cfgCheckpointInterval').value = d.checkpoint_interval || 5;
  _updateAllowedToolsVisibility();
}

function _updateAllowedToolsVisibility() {
  const skip = document.getElementById('cfgSkipPerms').checked;
  document.getElementById('rowAllowedTools').style.display = skip ? 'none' : 'flex';
}

function onSettingChange() {
  _settingsDirty = true;
  document.getElementById('settingsRestartHint').style.display = 'flex';
  _updateAllowedToolsVisibility();
}

async function saveSettings() {
  const payload = {
    skip_permissions: document.getElementById('cfgSkipPerms').checked,
    allowed_tools: document.getElementById('cfgAllowedTools').value.trim(),
    model: document.getElementById('cfgModel').value.trim(),
    max_jobs: parseInt(document.getElementById('cfgMaxJobs').value) || 10,
    append_system_prompt: document.getElementById('cfgSystemPrompt').value,
    target_repo: document.getElementById('cfgTargetRepo').value.trim(),
    base_branch: document.getElementById('cfgBaseBranch').value.trim() || 'main',
    checkpoint_interval: parseInt(document.getElementById('cfgCheckpointInterval').value) || 5,
  };
  try {
    await apiFetch('/api/config', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    showToast('설정이 저장되었습니다');
    _settingsDirty = false;
  } catch (e) {
    showToast('설정 저장 실패: ' + e.message, 'error');
  }
}

// ── 연결 재시도 (FAB 클릭 시) ──
async function retryConnect() {
  showToast('로컬 서버 연결 시도 중...', 'success');
  await autoConnect();
  if (_backendConnected) {
    showToast('로컬 서버에 연결되었습니다');
    checkStatus();
    fetchJobs();
  } else {
    showToast('로컬 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.', 'error');
  }
}

init();
