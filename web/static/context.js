/* ═══════════════════════════════════════════════
   Context Management — 세션 컨텍스트 (new/resume/fork)
   ═══════════════════════════════════════════════ */

let _contextMode = 'new';
let _contextSessionId = null;
let _contextSessionPrompt = null;

function setContextMode(mode) {
  _contextMode = mode;
  _contextSessionId = null;
  _contextSessionPrompt = null;
  _updateContextUI();
  _closeSessionPicker();
}

function clearContext() { setContextMode('new'); }

function _updateContextUI() {
  const newBtn = document.getElementById('ctxNew');
  const resumeBtn = document.getElementById('ctxResume');
  const forkBtn = document.getElementById('ctxFork');
  const label = document.getElementById('ctxSessionLabel');
  const promptInfo = document.getElementById('promptSessionInfo');

  [newBtn, resumeBtn, forkBtn].forEach(b => b.classList.remove('active'));
  label.classList.remove('visible');
  label.textContent = '';

  if (_contextMode === 'new') {
    newBtn.classList.add('active');
    if (promptInfo) promptInfo.textContent = '';
  } else if (_contextMode === 'resume') {
    resumeBtn.classList.add('active');
    const sid = _contextSessionId ? _contextSessionId.slice(0, 8) : '';
    if (sid) {
      const promptSnippet = _contextSessionPrompt ? _contextSessionPrompt.slice(0, 24) : '';
      label.textContent = promptSnippet ? `${sid}… ${promptSnippet}` : `${sid}…`;
      label.classList.add('visible');
    }
    if (promptInfo) promptInfo.textContent = sid ? `resume:${sid}` : 'resume';
  } else if (_contextMode === 'fork') {
    forkBtn.classList.add('active');
    const sid = _contextSessionId ? _contextSessionId.slice(0, 8) : '';
    if (sid) {
      const promptSnippet = _contextSessionPrompt ? _contextSessionPrompt.slice(0, 24) : '';
      label.textContent = promptSnippet ? `${sid}… ${promptSnippet}` : `${sid}…`;
      label.classList.add('visible');
    }
    if (promptInfo) promptInfo.textContent = sid ? `fork:${sid}` : 'fork';
  }
}

function _formatCwdShort(cwd) {
  if (!cwd) return '';
  const parts = cwd.replace(/\/$/, '').split('/');
  return parts[parts.length - 1] || cwd;
}

function _renderSessionItem(s) {
  const id = s.session_id || s.id || '';
  const hint = escapeHtml(truncate(s.prompt || s.last_prompt || id, 80));
  const cwdShort = _formatCwdShort(s.cwd || s.project || '');
  const cwdBadge = cwdShort
    ? `<span class="session-cwd-badge" title="${escapeHtml(s.cwd || s.project || '')}">${escapeHtml(cwdShort)}</span>`
    : '';
  const ts = s.updated_at || s.timestamp || '';
  const timeStr = ts ? formatTime(ts) : '';
  return `<div class="session-item" onclick="_selectSession('${escapeHtml(id)}', '${escapeHtml((s.prompt || '').replace(/'/g, "\\'"))}', '${escapeHtml((s.cwd || '').replace(/'/g, "\\'"))}')">
    <div class="session-item-prompt">${hint}</div>
    <div class="session-item-meta">${cwdBadge}<span class="session-item-id">${escapeHtml(id.slice(0, 12))}</span>${timeStr ? `<span class="session-item-time">${timeStr}</span>` : ''}</div>
  </div>`;
}

function _renderSessionList(sessions, grouped) {
  const list = document.getElementById('sessionPickerList');
  if (sessions.length === 0) {
    list.innerHTML = '<div style="padding:12px;text-align:center;color:var(--text-muted);font-size:0.75rem;">세션이 없습니다</div>';
    return;
  }

  if (grouped && Object.keys(grouped).length > 0) {
    let html = '';
    for (const [project, items] of Object.entries(grouped)) {
      const label = project || '(프로젝트 미지정)';
      html += `<div class="session-group-label">${escapeHtml(label)}</div>`;
      html += items.map(s => _renderSessionItem(s)).join('');
    }
    list.innerHTML = html;
  } else {
    list.innerHTML = sessions.map(s => _renderSessionItem(s)).join('');
  }
}

// 세션 검색 필터링용 캐시
let _sessionPickerSessions = [];
let _sessionPickerGrouped = {};

function _filterSessions(query) {
  if (!query) {
    _renderSessionList(_sessionPickerSessions, _sessionPickerGrouped);
    return;
  }
  const q = query.toLowerCase();
  const filtered = _sessionPickerSessions.filter(s => {
    const prompt = (s.prompt || s.last_prompt || '').toLowerCase();
    const id = (s.session_id || s.id || '').toLowerCase();
    const cwd = (s.cwd || s.project || '').toLowerCase();
    return prompt.includes(q) || id.includes(q) || cwd.includes(q);
  });
  _renderSessionList(filtered, null);
}

async function openSessionPicker(mode) {
  _contextMode = mode;
  _updateContextUI();

  const picker = document.getElementById('sessionPicker');
  const list = document.getElementById('sessionPickerList');
  const title = document.getElementById('sessionPickerTitle');
  const filterBar = document.getElementById('sessionFilterBar');
  const filterProject = document.getElementById('sessionFilterProject');
  const searchInput = document.getElementById('sessionSearchInput');

  title.textContent = mode === 'resume' ? 'Resume 세션 선택' : 'Fork 세션 선택';
  picker.classList.add('open');
  list.innerHTML = '<div style="padding:12px;text-align:center;"><span class="spinner"></span></div>';
  searchInput.value = '';

  try {
    const currentCwd = document.getElementById('cwdInput').value.trim();
    let url = '/api/sessions';
    if (currentCwd) url += `?cwd=${encodeURIComponent(currentCwd)}`;
    const data = await apiFetch(url);

    const sessions = Array.isArray(data) ? data : (data.sessions || []);
    const grouped = data.grouped || {};
    _sessionPickerSessions = sessions;
    _sessionPickerGrouped = grouped;

    if (currentCwd && sessions.length > 0) {
      filterBar.style.display = 'flex';
      const cwdShort = _formatCwdShort(currentCwd);
      filterProject.textContent = cwdShort;
      filterProject.title = currentCwd;
    } else {
      filterBar.style.display = 'none';
    }

    _renderSessionList(sessions, grouped);
  } catch (err) {
    list.innerHTML = `<div style="padding:12px;color:var(--red);">세션 목록 로딩 실패: ${err.message}</div>`;
  }
}

function _toggleProjectFilter() {
  const btn = document.getElementById('sessionFilterBtn');
  const isActive = btn.classList.toggle('active');
  const currentCwd = document.getElementById('cwdInput').value.trim();

  if (isActive && currentCwd) {
    openSessionPicker(_contextMode);
  } else {
    const list = document.getElementById('sessionPickerList');
    list.innerHTML = '<div style="padding:12px;text-align:center;"><span class="spinner"></span></div>';
    apiFetch('/api/sessions').then(data => {
      const sessions = Array.isArray(data) ? data : (data.sessions || []);
      const grouped = data.grouped || {};
      _sessionPickerSessions = sessions;
      _sessionPickerGrouped = grouped;
      _renderSessionList(sessions, grouped);
    }).catch(() => {});
  }
}

function _selectSession(sid, prompt, cwd) {
  _contextSessionId = sid;
  _contextSessionPrompt = prompt || null;
  _updateContextUI();
  _closeSessionPicker();

  if (cwd) {
    addRecentDir(cwd);
    selectRecentDir(cwd, true);
  }

  const modeLabel = _contextMode === 'resume' ? 'Resume' : 'Fork';
  showToast(`${modeLabel}: ${sid.slice(0, 8)}...`);
}

function _closeSessionPicker() {
  const picker = document.getElementById('sessionPicker');
  if (picker) picker.classList.remove('open');
}

// 세션 피커 외부 클릭 시 닫기
document.addEventListener('click', function(e) {
  const picker = document.getElementById('sessionPicker');
  if (!picker || !picker.classList.contains('open')) return;
  const toolbar = document.querySelector('.ctx-toolbar-wrap');
  if (toolbar && !toolbar.contains(e.target)) {
    _closeSessionPicker();
  }
});
