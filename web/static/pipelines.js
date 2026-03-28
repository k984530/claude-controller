/* ═══════════════════════════════════════════════
   Pipeline — on/off 자동화
   상태: active (ON) / stopped (OFF)
   ═══════════════════════════════════════════════ */

let _pipelines = [];
let _pipelinePollTimer = null;
let _pipelineCountdownTimer = null;

async function fetchPipelines() {
  try {
    _pipelines = await apiFetch('/api/pipelines');
    renderPipelines();

    const hasActive = _pipelines.some(p => p.status === 'active');
    if (hasActive && !_pipelinePollTimer) {
      _pipelinePollTimer = setInterval(_pipelinePollTick, 5000);
    } else if (!hasActive && _pipelinePollTimer) {
      clearInterval(_pipelinePollTimer);
      _pipelinePollTimer = null;
    }

    const hasTimer = _pipelines.some(p => p.status === 'active');
    if (hasTimer && !_pipelineCountdownTimer) {
      _pipelineCountdownTimer = setInterval(_updateCountdowns, 1000);
    } else if (!hasTimer && _pipelineCountdownTimer) {
      clearInterval(_pipelineCountdownTimer);
      _pipelineCountdownTimer = null;
    }
  } catch { /* silent */ }
}

async function _pipelinePollTick() {
  const hasRunning = _pipelines.some(p => p.status === 'active' && p.job_id);
  if (hasRunning) {
    try {
      await apiFetch('/api/pipelines/tick-all', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      });
    } catch { /* silent */ }
  }
  fetchPipelines();
}

function _formatTimer(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

function _updateCountdowns() {
  for (const p of _pipelines) {
    if (p.status !== 'active') continue;
    const el = document.querySelector(`[data-pipe-timer="${p.id}"]`);
    if (!el) continue;

    if (!p.next_run) {
      el.textContent = _formatTimer(0);
      continue;
    }

    const remaining = Math.max(0, Math.floor((new Date(p.next_run).getTime() - Date.now()) / 1000));
    el.textContent = _formatTimer(remaining);

    // 타이머 0 → 즉시 dispatch + 로컬에서 next_run 갱신
    if (remaining <= 0 && !p._dispatching) {
      p._dispatching = true;
      // 로컬에서 즉시 next_run 갱신 → 타이머 끊김 방지
      if (p.interval_sec) {
        p.next_run = new Date(Date.now() + p.interval_sec * 1000).toISOString().slice(0, 19);
      }
      apiFetch(`/api/pipelines/${encodeURIComponent(p.id)}/run`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      }).then(() => { fetchPipelines(); fetchJobs(); setTimeout(fetchJobs, 1000); })
        .catch(() => {})
        .finally(() => { p._dispatching = false; });
    }
  }
}

function renderPipelines() {
  const container = document.getElementById('pipelineList');
  const countEl = document.getElementById('pipelineCount');
  if (!container) return;

  if (countEl) countEl.textContent = _pipelines.length > 0 ? `(${_pipelines.length})` : '';

  if (_pipelines.length === 0) {
    container.innerHTML = '<div class="empty-state" style="padding:20px;text-align:center;color:var(--text-muted);font-size:0.8rem;">자동화가 없습니다.</div>';
    return;
  }

  container.innerHTML = _pipelines.map(p => {
    const isOn = p.status === 'active';
    const isRunning = isOn && p.job_id;

    let timerHtml = '';
    if (isOn) {
      let remaining = 0;
      if (p.next_run) {
        remaining = Math.max(0, Math.floor((new Date(p.next_run).getTime() - Date.now()) / 1000));
      }
      timerHtml = `<span data-pipe-timer="${p.id}" style="font-family:var(--font-mono,monospace);font-size:0.72rem;color:var(--text-muted);">${_formatTimer(remaining)}</span>`;
    }

    const cmdPreview = (p.command || '').substring(0, 80) + ((p.command || '').length > 80 ? '...' : '');
    const intervalLabel = p.interval ? `<span style="font-size:0.65rem;padding:1px 5px;background:rgba(59,130,246,0.1);color:var(--primary);border-radius:3px;">${escapeHtml(p.interval)} 반복</span>` : '';
    const runCount = p.run_count ? `<span style="font-size:0.65rem;color:var(--text-muted);">${p.run_count}회</span>` : '';

    const toggleBtn = isOn
      ? `<button class="btn btn-sm" onclick="stopPipeline('${p.id}')">OFF</button>`
      : `<button class="btn btn-sm btn-primary" onclick="runPipeline('${p.id}')">ON</button>`;

    return `<div class="pipeline-card" data-pipe-id="${p.id}">
      <div class="pipeline-card-header">
        <div class="pipeline-card-title">${escapeHtml(p.name || p.id)}</div>
        <div style="display:flex;gap:4px;align-items:center;">${intervalLabel} ${timerHtml}</div>
      </div>
      <div class="pipeline-card-goal" style="font-size:0.75rem;color:var(--text-secondary);margin:4px 0;font-family:var(--font-mono,monospace);">${escapeHtml(cmdPreview)}</div>
      ${p.last_error ? `<div style="font-size:0.7rem;color:var(--danger);margin:4px 0;padding:4px 8px;background:rgba(239,68,68,0.1);border-radius:4px;">${escapeHtml(p.last_error)}</div>` : ''}
      <div style="display:flex;gap:8px;font-size:0.7rem;color:var(--text-muted);align-items:center;">
        ${runCount}
        <span>${p.last_run || ''}</span>
      </div>
      <div class="pipeline-card-actions" style="margin-top:8px;display:flex;gap:6px;">
        ${toggleBtn}
        <button class="btn btn-sm" onclick="editPipeline('${p.id}')">수정</button>
        <button class="btn btn-sm btn-danger" onclick="deletePipeline('${p.id}')">삭제</button>
      </div>
    </div>`;
  }).join('');
}

async function runPipeline(pipeId) {
  try {
    const data = await apiFetch(`/api/pipelines/${encodeURIComponent(pipeId)}/run`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    showToast(`${data.name || ''}: ON`);
    fetchPipelines();
    fetchJobs();
    setTimeout(fetchJobs, 1000);
  } catch (err) {
    showToast(err.message || '실행 실패', 'error');
  }
}

async function stopPipeline(pipeId) {
  try {
    await apiFetch(`/api/pipelines/${encodeURIComponent(pipeId)}/stop`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    showToast('자동화 OFF');
    fetchPipelines();
  } catch (err) {
    showToast(err.message || 'OFF 실패', 'error');
  }
}

async function editPipeline(pipeId) {
  try {
    const data = await apiFetch(`/api/pipelines/${encodeURIComponent(pipeId)}/status`);
    const isOn = data.status === 'active';
    const statusBadge = isOn
      ? '<span class="badge" style="background:var(--primary)20;color:var(--primary);">ON</span>'
      : '<span class="badge" style="background:var(--text-muted)20;color:var(--text-muted);">OFF</span>';

    const editId = 'pipeEdit_' + Date.now();
    const overlay = document.createElement('div');
    overlay.className = 'settings-overlay';
    overlay.style.cssText = 'display:flex;align-items:center;justify-content:center;';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
    overlay.innerHTML = `<div class="settings-panel" style="max-width:520px;margin:0;">
      <div class="settings-header">
        <div class="settings-title" style="display:flex;align-items:center;gap:8px;">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          <span>자동화 수정</span>
          ${statusBadge}
        </div>
        <button class="settings-close" onclick="this.closest('.settings-overlay').remove()">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
      <div class="settings-body">
        <div style="margin-bottom:12px;">
          <label style="font-size:0.72rem;font-weight:600;color:var(--text-secondary);display:block;margin-bottom:4px;">이름</label>
          <input id="${editId}_name" type="text" value="${escapeHtml(data.name || '')}"
            style="width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-secondary);color:var(--text-primary);font-size:0.8rem;box-sizing:border-box;">
        </div>
        <div style="margin-bottom:12px;">
          <label style="font-size:0.72rem;font-weight:600;color:var(--text-secondary);display:block;margin-bottom:4px;">명령어 (프롬프트)</label>
          <textarea id="${editId}_cmd" rows="3"
            style="width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-secondary);color:var(--text-primary);font-size:0.8rem;font-family:var(--font-mono,monospace);resize:vertical;box-sizing:border-box;">${escapeHtml(data.command || '')}</textarea>
        </div>
        <div style="margin-bottom:12px;">
          <label style="font-size:0.72rem;font-weight:600;color:var(--text-secondary);display:block;margin-bottom:4px;">반복 간격 <span style="font-weight:400;color:var(--text-muted);">(예: 30s, 5m, 1h / 비우면 1회)</span></label>
          <input id="${editId}_interval" type="text" value="${escapeHtml(data.interval || '')}" placeholder="예: 1m"
            style="width:120px;padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-secondary);color:var(--text-primary);font-size:0.8rem;">
        </div>
        <div style="font-size:0.7rem;color:var(--text-muted);display:flex;gap:12px;">
          <span>경로: <code>${escapeHtml(data.project_path)}</code></span>
          ${data.run_count ? `<span>${data.run_count}회 실행</span>` : ''}
        </div>
      </div>
      <div class="settings-footer" style="display:flex;gap:6px;">
        <button class="btn btn-sm btn-primary" onclick="_savePipelineEdit('${data.id}','${editId}',this)">저장</button>
        ${isOn
          ? `<button class="btn btn-sm" onclick="stopPipeline('${data.id}');this.closest('.settings-overlay').remove();">OFF</button>`
          : `<button class="btn btn-sm" onclick="runPipeline('${data.id}');this.closest('.settings-overlay').remove();">ON</button>`}
        <button class="btn btn-sm" onclick="this.closest('.settings-overlay').remove()">닫기</button>
      </div>
    </div>`;
    document.body.appendChild(overlay);
  } catch (err) {
    showToast(err.message || '조회 실패', 'error');
  }
}

async function _savePipelineEdit(pipeId, editId, btn) {
  const name = document.getElementById(editId + '_name').value.trim();
  const command = document.getElementById(editId + '_cmd').value.trim();
  const interval = document.getElementById(editId + '_interval').value.trim();
  if (!command) { showToast('명령어를 입력하세요', 'error'); return; }

  btn.disabled = true;
  btn.textContent = '저장 중...';
  try {
    await apiFetch(`/api/pipelines/${encodeURIComponent(pipeId)}/update`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, command, interval }),
    });
    showToast('자동화 수정 완료');
    btn.closest('.settings-overlay').remove();
    fetchPipelines();
  } catch (err) {
    showToast(err.message || '수정 실패', 'error');
    btn.disabled = false;
    btn.textContent = '저장';
  }
}

async function deletePipeline(pipeId) {
  if (!confirm('이 자동화를 삭제하시겠습니까?')) return;
  try {
    await apiFetch(`/api/pipelines/${encodeURIComponent(pipeId)}`, { method: 'DELETE' });
    showToast('자동화 삭제됨');
    fetchPipelines();
  } catch (err) {
    showToast(err.message || '삭제 실패', 'error');
  }
}
