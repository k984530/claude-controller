/* ═══════════════════════════════════════════════
   Send Task — 작업 전송 및 자동화 토글
   ═══════════════════════════════════════════════ */

let _sendLock = false;

/* ═══════════════════════════════════════════════
   Prompt Lanes — 세션 고정 멀티 입력 (최대 3개)
   ═══════════════════════════════════════════════ */

const _lanes = [];  // { id, sessionId, sessionPrompt, cwd }
const MAX_LANES = 3;
const _laneAttachments = {};  // laneId → [{ serverPath, filename, isImage }]

function _saveLanes() {
  try {
    localStorage.setItem('promptLanes', JSON.stringify(_lanes));
  } catch {}
}

function _restoreLanes() {
  try {
    const saved = localStorage.getItem('promptLanes');
    if (!saved) return;
    const arr = JSON.parse(saved);
    if (!Array.isArray(arr)) return;
    _lanes.length = 0;
    for (const l of arr) {
      if (l && l.id) _lanes.push({ id: l.id, sessionId: l.sessionId || null, sessionPrompt: l.sessionPrompt || '', cwd: l.cwd || '' });
    }
    if (_lanes.length > 0) {
      _renderLanes();
      _updateAddLaneBtn();
    }
  } catch {}
}

function _updateAddLaneBtn() {
  const btn = document.getElementById('btnAddLane');
  if (!btn) return;
  btn.style.display = _lanes.length < MAX_LANES ? '' : 'none';
}

function addPromptLane(sessionId, sessionPrompt, cwd) {
  if (_lanes.length >= MAX_LANES) return;
  const id = Date.now();
  const lane = { id, sessionId: sessionId || null, sessionPrompt: sessionPrompt || '', cwd: cwd || '' };
  _lanes.push(lane);
  _renderLanes();
  _updateAddLaneBtn();
  _saveLanes();
  // 첫 레인 추가 시 "레인 추가" 버튼 노출
  if (_lanes.length === 1) {
    const btn = document.getElementById('btnAddLane');
    if (btn) btn.style.display = '';
  }
}

function removePromptLane(id) {
  const idx = _lanes.findIndex(l => l.id === id);
  if (idx === -1) return;
  delete _laneAttachments[id];
  _lanes.splice(idx, 1);
  _renderLanes();
  _updateAddLaneBtn();
  _saveLanes();
}

function _renderLanes() {
  const container = document.getElementById('promptLanes');
  if (!container) return;
  if (_lanes.length === 0) {
    container.innerHTML = '';
    return;
  }
  const dirs = typeof getRecentDirs === 'function' ? getRecentDirs() : [];
  container.innerHTML = _lanes.map(lane => {
    const sid = lane.sessionId ? lane.sessionId.slice(0, 8) : '';
    const cwdShort = lane.cwd ? lane.cwd.split('/').pop() : '';
    const sessionLabel = sid
      ? `${sid}… ${lane.sessionPrompt ? escapeHtml(lane.sessionPrompt.slice(0, 20)) : ''}`
      : 'new';
    // CWD 드롭다운 옵션
    const dirOptions = dirs.map(d => {
      const short = d.split('/').pop();
      const sel = d === lane.cwd ? ' selected' : '';
      return `<option value="${escapeHtml(d)}"${sel}>${escapeHtml(short)}</option>`;
    }).join('');

    return `
      <div class="prompt-lane" data-lane-id="${lane.id}">
        <div class="lane-header">
          <select class="lane-cwd-select" onchange="setLaneCwd(${lane.id}, this.value)" title="${t('lane_select_project')}">
            <option value="">${t('lane_select_project')}</option>
            ${dirOptions}
          </select>
          <span class="lane-session-badge ${sid ? 'has-session' : ''}" onclick="toggleLaneSessionPicker(${lane.id})" title="${sid ? t('lane_session_prefix') + ': ' + lane.sessionId : t('lane_session_pick')}">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            <span class="lane-session-text">${sessionLabel}</span>
          </span>
          <button class="lane-close" onclick="removePromptLane(${lane.id})" title="${t('lane_remove')}">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="lane-session-dropdown" id="laneSessionDropdown-${lane.id}"></div>
        <div class="lane-attachments" id="laneAttachments-${lane.id}"></div>
        <div class="lane-body">
          <textarea class="lane-input" id="laneInput-${lane.id}" placeholder="${cwdShort ? cwdShort + ' — ' : ''}${t('lane_input_ph')}" rows="1" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendAll(event);}"></textarea>
          <input type="file" id="laneFileInput-${lane.id}" multiple hidden onchange="handleLaneFileInput(${lane.id}, this)">
        </div>
      </div>`;
  }).join('');

  // 이벤트 바인딩: paste, drag-drop + 기존 첨부 복원
  _lanes.forEach(lane => {
    const input = document.getElementById('laneInput-' + lane.id);
    if (!input) return;
    input.addEventListener('paste', function(e) {
      const files = e.clipboardData?.files;
      if (files && files.length > 0) {
        e.preventDefault();
        handleLaneFiles(lane.id, files);
      }
    });
    input.addEventListener('input', function() { _syncLaneAttachmentsFromText(lane.id); });
    input.addEventListener('dragover', function(e) { e.preventDefault(); });
    input.addEventListener('drop', function(e) {
      if (e.dataTransfer.files.length > 0) {
        e.preventDefault();
        e.stopPropagation();
        // 상위 sendTask의 drag-over 상태 정리
        const wrapper = document.getElementById('promptWrapper');
        if (wrapper) wrapper.classList.remove('drag-over');
        handleLaneFiles(lane.id, e.dataTransfer.files);
      }
    });
    // 기존 첨부 칩 복원
    _renderLaneAttachmentChips(lane.id);
  });
}

/* ── 레인 파일 첨부 ── */

function openLaneFilePicker(laneId) {
  const input = document.getElementById('laneFileInput-' + laneId);
  if (input) input.click();
}

function handleLaneFileInput(laneId, inputEl) {
  if (inputEl.files.length > 0) {
    handleLaneFiles(laneId, inputEl.files);
    inputEl.value = '';
  }
}

async function handleLaneFiles(laneId, files) {
  if (!_laneAttachments[laneId]) _laneAttachments[laneId] = [];
  for (const file of files) {
    const isImage = file.type.startsWith('image/');
    const localUrl = isImage ? URL.createObjectURL(file) : null;
    try {
      const data = await uploadFile(file);
      const idx = _laneAttachments[laneId].length;
      _laneAttachments[laneId].push({ serverPath: data.path, filename: data.filename || file.name, isImage, localUrl });
      const input = document.getElementById('laneInput-' + laneId);
      if (input) {
        const ref = isImage ? `@image${idx}` : `@${data.path}`;
        const space = input.value.length > 0 && !input.value.endsWith(' ') ? ' ' : '';
        input.value += space + ref + ' ';
        input.focus();
      }
      _renderLaneAttachmentChips(laneId);
    } catch (err) {
      if (localUrl) URL.revokeObjectURL(localUrl);
      showToast(`${t('msg_upload_failed')}: ${file.name} — ${err.message}`, 'error');
    }
  }
}

function removeLaneAttachment(laneId, idx) {
  const atts = _laneAttachments[laneId];
  if (!atts || !atts[idx]) return;
  const att = atts[idx];
  const input = document.getElementById('laneInput-' + laneId);
  if (input) {
    // @image0 또는 @path 형식 제거
    const ref = att.isImage ? `@image${idx}` : '@' + att.serverPath;
    input.value = input.value.replace(new RegExp('\\s*' + ref.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*', 'g'), ' ').trim();
  }
  atts[idx] = null;
  _renderLaneAttachmentChips(laneId);
}

function _renderLaneAttachmentChips(laneId) {
  const container = document.getElementById('laneAttachments-' + laneId);
  if (!container) return;
  const atts = _laneAttachments[laneId] || [];
  const active = atts.filter(a => a !== null);
  if (active.length === 0) { container.innerHTML = ''; return; }
  container.innerHTML = atts.map((att, idx) => {
    if (!att) return '';
    if (att.isImage) {
      const src = att.localUrl || att.serverPath;
      return `<span class="lane-file-chip lane-img-chip" title="${escapeHtml(att.serverPath)}">
        <img src="${escapeHtml(src)}" alt="${escapeHtml(att.filename)}">
        <button onclick="removeLaneAttachment(${laneId},${idx})">&times;</button>
      </span>`;
    }
    return `<span class="lane-file-chip" title="${escapeHtml(att.serverPath)}">
      ${escapeHtml(att.filename)}
      <button onclick="removeLaneAttachment(${laneId},${idx})">&times;</button>
    </span>`;
  }).join('');
}

function _syncLaneAttachmentsFromText(laneId) {
  const atts = _laneAttachments[laneId];
  if (!atts) return;
  const input = document.getElementById('laneInput-' + laneId);
  if (!input) return;
  const text = input.value;
  let changed = false;
  atts.forEach((att, idx) => {
    if (!att) return;
    const ref = att.isImage ? `@image${idx}` : `@${att.serverPath}`;
    if (!text.includes(ref)) {
      if (att.localUrl) URL.revokeObjectURL(att.localUrl);
      atts[idx] = null;
      changed = true;
    }
  });
  if (changed) _renderLaneAttachmentChips(laneId);
}

function setLaneCwd(laneId, cwd) {
  const lane = _lanes.find(l => l.id === laneId);
  if (!lane) return;
  lane.cwd = cwd;
  // CWD 변경 시 세션 초기화 (다른 프로젝트니까)
  lane.sessionId = null;
  lane.sessionPrompt = '';
  _renderLanes();
  _saveLanes();
}

async function sendFromLane(laneId) {
  const lane = _lanes.find(l => l.id === laneId);
  if (!lane) return;
  const input = document.getElementById('laneInput-' + laneId);
  if (!input) return;
  const prompt = input.value.trim();
  if (!prompt) { showToast(t('lane_prompt_req'), 'error'); return; }

  const btn = input.closest('.lane-body').querySelector('.lane-send');
  btn.disabled = true;
  input.disabled = true;

  try {
    // @image0 → 실제 경로 치환
    let finalPrompt = prompt;
    const laneAtts = _laneAttachments[laneId] || [];
    const filePaths = [];
    laneAtts.forEach((att, idx) => {
      if (att && att.serverPath) {
        if (att.isImage) {
          finalPrompt = finalPrompt.replace(new RegExp(`@image${idx}\\b`, 'g'), `@${att.serverPath}`);
        }
        filePaths.push(att.serverPath);
      }
    });

    const body = { prompt: finalPrompt };
    if (lane.cwd) body.cwd = lane.cwd;
    if (lane.sessionId) body.session = 'resume:' + lane.sessionId;
    if (filePaths.length > 0) body.images = filePaths;

    const result = await apiFetch('/api/send', { method: 'POST', body: JSON.stringify(body) });
    const jobId = result && result.job_id;
    showToast(t('lane_sent') + (lane.sessionId ? ` (resume:${lane.sessionId.slice(0,8)})` : '') + (jobId ? ` #${jobId}` : ''));
    input.value = '';
    // 전송 후 첨부 초기화
    delete _laneAttachments[laneId];
    _renderLaneAttachmentChips(laneId);

    // 세션 ID 캡처: 응답에 session_id가 있으면 즉시, 없으면 job meta에서 추적
    if (!lane.sessionId && result) {
      if (result.session_id) {
        lane.sessionId = result.session_id;
        lane.sessionPrompt = prompt.slice(0, 40);
        _saveLanes();
      } else if (jobId) {
        // 잠시 후 job meta에서 세션 ID 추출 시도
        setTimeout(async () => {
          try {
            const jobs = await apiFetch('/api/jobs?limit=5');
            const job = (jobs.jobs || []).find(j => j.job_id === String(jobId));
            if (job && job.session_id && !lane.sessionId) {
              lane.sessionId = job.session_id;
              lane.sessionPrompt = prompt.slice(0, 40);
              _saveLanes();
              _renderLanes();
            }
          } catch {}
        }, 3000);
      }
    }
    _renderLanes();
    fetchJobs();
  } catch (err) {
    showToast(t('lane_send_fail') + ': ' + err.message, 'error');
  } finally {
    btn.disabled = false;
    input.disabled = false;
    input.focus();
  }
}

/* ── 레인 전용 인라인 세션 피커 (메인 입력창과 완전 독립) ── */

function toggleLaneSessionPicker(laneId) {
  const dropdown = document.getElementById('laneSessionDropdown-' + laneId);
  if (!dropdown) return;

  // 다른 열린 드롭다운 닫기
  document.querySelectorAll('.lane-session-dropdown.open').forEach(d => {
    if (d !== dropdown) d.classList.remove('open');
  });

  if (dropdown.classList.contains('open')) {
    dropdown.classList.remove('open');
    return;
  }

  dropdown.classList.add('open');
  dropdown.innerHTML = '<div style="padding:8px;text-align:center;"><span class="spinner"></span></div>';

  const lane = _lanes.find(l => l.id === laneId);
  const laneCwd = lane?.cwd || '';
  let url = '/api/sessions';
  if (laneCwd) url += `?cwd=${encodeURIComponent(laneCwd)}`;

  apiFetch(url).then(data => {
    const sessions = Array.isArray(data) ? data : (data.sessions || []);

    let html = `<div class="lane-picker-item lane-picker-new" onclick="selectLaneSession(${laneId},null,'','')">${t('lane_new_session')}</div>`;

    if (sessions.length === 0) {
      html += `<div class="lane-picker-empty">${t('lane_no_sessions')}</div>`;
    } else {
      html += sessions.map(s => {
        const id = s.session_id || s.id || '';
        const prompt = (s.prompt || s.last_prompt || '').replace(/'/g, "\\'").replace(/\n/g, ' ');
        const cwd = (s.cwd || '').replace(/'/g, "\\'");
        const hint = escapeHtml(truncate(s.prompt || s.last_prompt || id, 50));
        const cwdShort = (s.cwd || '').split('/').pop() || '';
        return `<div class="lane-picker-item" onclick="selectLaneSession(${laneId},'${escapeHtml(id)}','${escapeHtml(prompt)}','${escapeHtml(cwd)}')">
          <div class="lane-picker-prompt">${hint}</div>
          <div class="lane-picker-meta">${cwdShort ? `<span class="session-cwd-badge">${escapeHtml(cwdShort)}</span>` : ''}<span class="lane-picker-id">${escapeHtml(id.slice(0, 12))}</span></div>
        </div>`;
      }).join('');
    }

    dropdown.innerHTML = html;
  }).catch(() => {
    dropdown.innerHTML = `<div class="lane-picker-empty" style="color:var(--red);">${t('lane_load_fail')}</div>`;
  });
}

function selectLaneSession(laneId, sid, prompt, cwd) {
  const lane = _lanes.find(l => l.id === laneId);
  if (!lane) return;
  lane.sessionId = sid;
  lane.sessionPrompt = prompt || '';
  if (cwd) lane.cwd = cwd;
  _saveLanes();
  _renderLanes();
  showToast(sid ? t('lane_session_set') + ': ' + sid.slice(0, 8) + '...' : t('lane_session_new'));
}

// 레인 드롭다운 외부 클릭 시 닫기
document.addEventListener('click', function(e) {
  if (!e.target.closest('.lane-session-badge') && !e.target.closest('.lane-session-dropdown')) {
    document.querySelectorAll('.lane-session-dropdown.open').forEach(d => d.classList.remove('open'));
  }
});
let _automationMode = false;
let _depsMode = false;

function toggleAutomation() {
  _automationMode = !_automationMode;
  const row = document.getElementById('automationRow');
  const btn = document.getElementById('btnAutoToggle');
  const sendBtn = document.getElementById('btnSend');
  if (_automationMode) {
    row.style.display = 'flex';
    btn.style.cssText = 'border-color:var(--accent);color:var(--accent);background:rgba(99,102,241,0.1);';
    sendBtn.querySelector('span').textContent = t('auto_register');
  } else {
    row.style.display = 'none';
    btn.style.cssText = '';
    sendBtn.querySelector('span').textContent = t('send');
    document.getElementById('automationInterval').value = '';
  }
}

function toggleDeps() {
  // DAG UI는 숨김 처리됨 — AI가 API depends_on으로 직접 사용
  _depsMode = !_depsMode;
  const row = document.getElementById('depsRow');
  if (row) row.style.display = _depsMode ? 'flex' : 'none';
  if (!_depsMode) {
    const inp = document.getElementById('depsInput');
    if (inp) inp.value = '';
  }
}

function clearPromptForm() {
  document.getElementById('promptInput').value = '';
  clearAttachments();
  updatePromptMirror();
  clearDirSelection();
  if (_automationMode) toggleAutomation();
  if (_depsMode) toggleDeps();
}

async function sendTask(e) {
  e.preventDefault();
  if (_sendLock) return false;

  const prompt = document.getElementById('promptInput').value.trim();
  if (!prompt) {
    showToast(t('msg_prompt_required'), 'error');
    return false;
  }

  // ── 자동화 모드: 파이프라인 생성 ──
  if (_automationMode) {
    const cwd = document.getElementById('cwdInput').value.trim();
    if (!cwd) { showToast(t('select_dir_req'), 'error'); return false; }
    const interval = document.getElementById('automationInterval').value.trim();
    _sendLock = true;
    const btn = document.getElementById('btnSend');
    btn.disabled = true;
    try {
      const pipeBody = { project_path: cwd, command: prompt, interval };
      const pipe = await apiFetch('/api/pipelines', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pipeBody),
      });
      showToast(t('auto_register_done').replace('{name}', pipe.name || pipe.id));
      clearPromptForm();
      fetchPipelines();
      runPipeline(pipe.id);
    } catch (err) {
      showToast(t('register_fail') + ': ' + err.message, 'error');
    } finally {
      _sendLock = false;
      btn.disabled = false;
      btn.querySelector('span').textContent = t('send');
    }
    return false;
  }

  // ── 일반 전송 모드 ──
  _sendLock = true;
  const cwd = document.getElementById('cwdInput').value.trim();
  const btn = document.getElementById('btnSend');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> ' + t('sending_text');

  try {
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
    if (_contextSessionId && (_contextMode === 'resume' || _contextMode === 'fork')) {
      body.session = _contextMode + ':' + _contextSessionId;
    }

    if (filePaths.length > 0) body.images = filePaths;

    // 의존성 모드: depends_on 추가
    if (_depsMode) {
      const depsVal = document.getElementById('depsInput').value.trim();
      if (depsVal) {
        body.depends_on = depsVal.split(/[,\s]+/).filter(Boolean);
      }
    }

    const result = await apiFetch('/api/send', { method: 'POST', body: JSON.stringify(body) });
    const modeMsg = _contextMode === 'resume' ? ' (resume)' : _contextMode === 'fork' ? ' (fork)' : '';
    const depMsg = result && result.status === 'pending' ? ' ' + t('dep_pending') : '';
    showToast(t('msg_task_sent') + modeMsg + depMsg);
    if (cwd) addRecentDir(cwd);
    document.getElementById('promptInput').value = '';
    clearAttachments();
    // resume 모드: 세션 컨텍스트를 유지하여 이어서 보낼 수 있게 함
    // fork/new 모드: 컨텍스트 초기화
    if (_contextMode !== 'resume') clearContext();
    if (_depsMode) toggleDeps();
    fetchJobs();
  } catch (err) {
    showToast(`${t('msg_send_failed')}: ${err.message}`, 'error');
  } finally {
    _sendLock = false;
    btn.disabled = false;
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> <span data-i18n="send">' + t('send') + '</span>';
  }
  return false;
}

/* ═══════════════════════════════════════════════
   sendAll — 메인 프롬프트 + 모든 레인 일괄 전송
   ═══════════════════════════════════════════════ */

async function sendAll(e) {
  if (e) e.preventDefault();
  if (_sendLock) return false;

  const mainPrompt = document.getElementById('promptInput').value.trim();
  const activeLanes = _lanes.filter(l => {
    const inp = document.getElementById('laneInput-' + l.id);
    return inp && inp.value.trim();
  });

  if (!mainPrompt && activeLanes.length === 0) {
    showToast(t('msg_prompt_required'), 'error');
    return false;
  }

  // 자동화 모드: 메인 프롬프트만 sendTask로 처리
  if (_automationMode && mainPrompt) {
    return sendTask(e || new Event('submit'));
  }

  _sendLock = true;
  const btn = document.getElementById('btnSend');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> ' + t('sending_text');

  let sent = 0;

  // 1) 메인 프롬프트 전송
  if (mainPrompt) {
    try {
      let finalPrompt = mainPrompt;
      const cwd = document.getElementById('cwdInput').value.trim();
      const body = { prompt: finalPrompt };
      if (cwd) body.cwd = cwd;
      if (_contextSessionId && (_contextMode === 'resume' || _contextMode === 'fork')) {
        body.session = _contextMode + ':' + _contextSessionId;
      }
      const filePaths = [];
      attachments.forEach((att, idx) => {
        if (att && att.serverPath) {
          body.prompt = body.prompt.replace(new RegExp(`@image${idx}\\b`, 'g'), `@${att.serverPath}`);
          filePaths.push(att.serverPath);
        }
      });
      if (filePaths.length > 0) body.images = filePaths;
      if (_depsMode) {
        const depsVal = document.getElementById('depsInput').value.trim();
        if (depsVal) body.depends_on = depsVal.split(/[,\s]+/).filter(Boolean);
      }
      await apiFetch('/api/send', { method: 'POST', body: JSON.stringify(body) });
      if (cwd) addRecentDir(cwd);
      document.getElementById('promptInput').value = '';
      clearAttachments();
      updatePromptMirror();
      if (_contextMode !== 'resume') clearContext();
      if (_depsMode) toggleDeps();
      sent++;
    } catch (err) {
      showToast(t('msg_send_failed') + ': ' + err.message, 'error');
    }
  }

  // 2) 레인 일괄 전송
  for (const lane of activeLanes) {
    const input = document.getElementById('laneInput-' + lane.id);
    const prompt = input.value.trim();
    try {
      const body = { prompt };
      if (lane.cwd) body.cwd = lane.cwd;
      if (lane.sessionId) body.session = 'resume:' + lane.sessionId;
      // 레인 첨부 파일 처리
      const atts = _laneAttachments[lane.id] || [];
      const laneFiles = atts.filter(a => a && a.serverPath).map(a => a.serverPath);
      if (laneFiles.length > 0) body.images = laneFiles;

      const result = await apiFetch('/api/send', { method: 'POST', body: JSON.stringify(body) });
      input.value = '';
      // 세션 ID 캡처
      if (!lane.sessionId && result && result.session_id) {
        lane.sessionId = result.session_id;
        lane.sessionPrompt = prompt.slice(0, 40);
      }
      sent++;
    } catch (err) {
      showToast(t('lane_send_fail') + ': ' + err.message, 'error');
    }
  }

  if (sent > 0) {
    showToast(t('msg_task_sent') + (sent > 1 ? ` (${sent})` : ''));
    _renderLanes();
    _saveLanes();
    fetchJobs();
  }

  _sendLock = false;
  btn.disabled = false;
  btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> <span data-i18n="send">' + t('send') + '</span>';
  return false;
}

