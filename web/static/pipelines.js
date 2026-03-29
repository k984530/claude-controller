/* ═══════════════════════════════════════════════
   Pipeline — on/off 자동화
   상태: active (ON) / stopped (OFF)
   ═══════════════════════════════════════════════ */

let _pipelines = [];
let _pipelinePollTimer = null;
let _pipelineCountdownTimer = null;
const _POLL_FAST = 2000;   // job 실행 중
const _POLL_NORMAL = 5000; // 대기 중

async function fetchPipelines() {
  try {
    _pipelines = await apiFetch('/api/pipelines');
    renderPipelines();

    const hasActive = _pipelines.some(p => p.status === 'active');
    const hasRunning = _pipelines.some(p => p.status === 'active' && p.job_id);
    const desiredInterval = hasRunning ? _POLL_FAST : _POLL_NORMAL;

    if (hasActive) {
      // 간격이 바뀌었으면 타이머 재설정
      if (_pipelinePollTimer && _pipelinePollTimer._interval !== desiredInterval) {
        clearInterval(_pipelinePollTimer);
        _pipelinePollTimer = null;
      }
      if (!_pipelinePollTimer) {
        _pipelinePollTimer = setInterval(_pipelinePollTick, desiredInterval);
        _pipelinePollTimer._interval = desiredInterval;
      }
    } else if (_pipelinePollTimer) {
      clearInterval(_pipelinePollTimer);
      _pipelinePollTimer = null;
    }

    if (hasActive && !_pipelineCountdownTimer) {
      _pipelineCountdownTimer = setInterval(_updateCountdowns, 1000);
    } else if (!hasActive && _pipelineCountdownTimer) {
      clearInterval(_pipelineCountdownTimer);
      _pipelineCountdownTimer = null;
    }
  } catch { /* silent */ }
}

async function _pipelinePollTick() {
  const hasActive = _pipelines.some(p => p.status === 'active');
  if (hasActive) {
    try {
      const results = await apiFetch('/api/pipelines/tick-all', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      });
      // 완료/에러/디스패치 감지 시 jobs 목록도 즉시 갱신
      if (Array.isArray(results) && results.some(r => r.result && (r.result.action === 'completed' || r.result.action === 'error' || r.result.action === 'dispatched'))) {
        fetchJobs();
      }
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
      // next_run 없고 job도 없으면 즉시 dispatch (프리셋 생성 직후 등)
      if (!p._dispatching && !p.job_id) {
        p._dispatching = true;
        apiFetch(`/api/pipelines/${encodeURIComponent(p.id)}/run`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
        }).then(() => { fetchPipelines(); fetchJobs(); setTimeout(fetchJobs, 1000); })
          .catch(() => {})
          .finally(() => { p._dispatching = false; });
      }
      continue;
    }

    const remaining = Math.max(0, Math.floor((new Date(p.next_run).getTime() - Date.now()) / 1000));
    el.textContent = _formatTimer(remaining);

    // 타이머 0 → 이미 job_id가 있으면 skip (이중 발사 방지)
    if (remaining <= 0 && !p._dispatching && !p.job_id) {
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
    const projectName = p.project_path ? p.project_path.split('/').filter(Boolean).pop() : '';
    const projectPath = p.project_path || '';

    // 적응형 인터벌 표시
    const baseInterval = p.interval_sec;
    const effectiveInterval = p.effective_interval_sec;
    const isAdapted = baseInterval && effectiveInterval && baseInterval !== effectiveInterval;
    let intervalLabel = '';
    if (p.interval) {
      if (isAdapted) {
        const effMin = Math.round(effectiveInterval / 60);
        const pct = Math.round((effectiveInterval - baseInterval) / baseInterval * 100);
        intervalLabel = `<span style="font-size:0.65rem;padding:1px 5px;background:rgba(168,85,247,0.1);color:#a855f7;border-radius:3px;" title="기본: ${escapeHtml(p.interval)}, 적응: ${effMin}분 (${pct > 0 ? '+' : ''}${pct}%)">${effMin}분 적응</span>`;
      } else {
        intervalLabel = `<span style="font-size:0.65rem;padding:1px 5px;background:rgba(59,130,246,0.1);color:var(--primary);border-radius:3px;">${escapeHtml(p.interval)} 반복</span>`;
      }
    }

    // 체이닝 표시
    const chainLabel = p.on_complete ? `<span style="font-size:0.65rem;padding:1px 5px;background:rgba(34,197,94,0.1);color:#22c55e;border-radius:3px;" title="완료 시 트리거">→ chain</span>` : '';

    const runningBadge = isRunning ? `<span class="pipe-running-badge"><span class="pipe-running-dot"></span>실행 중</span>` : '';
    const runCount = p.run_count ? `<span style="font-size:0.65rem;color:var(--text-muted);">${p.run_count}회</span>` : '';

    const toggleBtn = isOn
      ? `<button class="btn btn-sm" onclick="stopPipeline('${p.id}')">OFF</button>`
      : `<button class="btn btn-sm btn-primary" onclick="runPipeline('${p.id}')">ON</button>`;

    return `<div class="pipeline-card${isRunning ? ' is-running' : ''}" data-pipe-id="${p.id}">
      <div class="pipeline-card-header">
        <div class="pipeline-card-title">${escapeHtml(p.name || p.id)}</div>
        <div style="display:flex;gap:4px;align-items:center;">${runningBadge} ${intervalLabel} ${chainLabel} ${timerHtml}</div>
      </div>
      ${projectName ? `<div style="font-size:0.65rem;color:var(--text-muted);margin:2px 0 0 0;display:flex;align-items:center;gap:3px;" title="${escapeHtml(projectPath)}"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>${escapeHtml(projectName)}</div>` : ''}
      <div class="pipeline-card-goal" style="font-size:0.75rem;color:var(--text-secondary);margin:4px 0;font-family:var(--font-mono,monospace);">${escapeHtml(cmdPreview)}</div>
      ${p.last_error ? `<div style="font-size:0.7rem;color:var(--danger);margin:4px 0;padding:4px 8px;background:rgba(239,68,68,0.1);border-radius:4px;">${escapeHtml(p.last_error)}</div>` : ''}
      <div style="display:flex;gap:8px;font-size:0.7rem;color:var(--text-muted);align-items:center;">
        ${runCount}
        <span>${p.last_run || ''}</span>
      </div>
      <div class="pipeline-card-actions" style="margin-top:8px;display:flex;gap:6px;">
        ${toggleBtn}
        <button class="btn btn-sm" onclick="editPipeline('${p.id}')">수정</button>
        ${p.run_count ? `<button class="btn btn-sm" onclick="showPipelineHistory('${p.id}')">이력</button>` : ''}
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
    // 즉시 로컬 상태 반영 → UI 지연 없음
    _pipelines = _pipelines.filter(p => p.id !== pipeId);
    renderPipelines();
    showToast('자동화 삭제됨');
    fetchPipelines();
  } catch (err) {
    showToast(err.message || '삭제 실패', 'error');
  }
}

/* ── 진화 요약 패널 ── */
async function fetchEvolutionSummary() {
  const el = document.getElementById('evolutionSummary');
  if (!el) return;
  try {
    const data = await apiFetch('/api/pipelines/evolution');
    const cls = data.classifications || {};
    const total = (cls.has_change || 0) + (cls.no_change || 0) + (cls.unknown || 0);
    const adaptations = (data.interval_adaptations || []);

    let adaptHtml = '';
    if (adaptations.length > 0) {
      adaptHtml = adaptations.map(a =>
        `<span style="font-size:0.65rem;color:#a855f7;">${escapeHtml(a.name)}: ${a.change_pct > 0 ? '+' : ''}${a.change_pct}%</span>`
      ).join(' ');
    }

    el.innerHTML = `<div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:8px 12px;background:var(--bg-secondary);border-radius:8px;font-size:0.7rem;color:var(--text-muted);">
      <span>총 ${data.total_runs}회 실행</span>
      <span>효율 ${data.efficiency_pct}%</span>
      ${total > 0 ? `<span style="color:var(--text-secondary);">변경:${cls.has_change||0} / 무변경:${cls.no_change||0}</span>` : ''}
      ${adaptHtml}
    </div>`;
  } catch { el.innerHTML = ''; }
}

/* ── 새 자동화 생성 모달 ── */
function openCreatePipeline() {
  const cwd = document.getElementById('cwdInput')?.value?.trim() || '';
  const formId = 'pipeCreate_' + Date.now();
  const overlay = document.createElement('div');
  overlay.className = 'settings-overlay';
  overlay.style.cssText = 'display:flex;align-items:center;justify-content:center;';
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  overlay.innerHTML = `<div class="settings-panel" style="max-width:520px;margin:0;">
    <div class="settings-header">
      <div class="settings-title" style="display:flex;align-items:center;gap:8px;">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        <span>새 자동화</span>
      </div>
      <button class="settings-close" onclick="this.closest('.settings-overlay').remove()">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
    <div class="settings-body">
      <div style="margin-bottom:12px;">
        <label style="font-size:0.72rem;font-weight:600;color:var(--text-secondary);display:block;margin-bottom:4px;">이름</label>
        <input id="${formId}_name" type="text" placeholder="예: code-quality"
          style="width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-secondary);color:var(--text-primary);font-size:0.8rem;box-sizing:border-box;">
      </div>
      <div style="margin-bottom:12px;">
        <label style="font-size:0.72rem;font-weight:600;color:var(--text-secondary);display:block;margin-bottom:4px;">프로젝트 경로</label>
        <input id="${formId}_path" type="text" value="${escapeHtml(cwd)}"
          style="width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-secondary);color:var(--text-primary);font-size:0.8rem;font-family:var(--font-mono,monospace);box-sizing:border-box;">
      </div>
      <div style="margin-bottom:12px;">
        <label style="font-size:0.72rem;font-weight:600;color:var(--text-secondary);display:block;margin-bottom:4px;">명령어 (프롬프트)</label>
        <textarea id="${formId}_cmd" rows="4" placeholder="Claude에게 시킬 작업을 입력하세요"
          style="width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-secondary);color:var(--text-primary);font-size:0.8rem;font-family:var(--font-mono,monospace);resize:vertical;box-sizing:border-box;"></textarea>
      </div>
      <div style="display:flex;gap:12px;margin-bottom:12px;">
        <div style="flex:1;">
          <label style="font-size:0.72rem;font-weight:600;color:var(--text-secondary);display:block;margin-bottom:4px;">반복 간격 <span style="font-weight:400;color:var(--text-muted);">(비우면 1회)</span></label>
          <input id="${formId}_interval" type="text" placeholder="예: 5m, 1h"
            style="width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-secondary);color:var(--text-primary);font-size:0.8rem;box-sizing:border-box;">
        </div>
        <div style="flex:1;">
          <label style="font-size:0.72rem;font-weight:600;color:var(--text-secondary);display:block;margin-bottom:4px;">체이닝 <span style="font-weight:400;color:var(--text-muted);">(완료 시 트리거)</span></label>
          <select id="${formId}_chain"
            style="width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-secondary);color:var(--text-primary);font-size:0.8rem;box-sizing:border-box;">
            <option value="">없음</option>
            ${_pipelines.map(p => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name || p.id)}</option>`).join('')}
          </select>
        </div>
      </div>
    </div>
    <div class="settings-footer" style="display:flex;gap:6px;">
      <button class="btn btn-sm btn-primary" onclick="_submitCreatePipeline('${formId}',this)">생성 및 실행</button>
      <button class="btn btn-sm" onclick="this.closest('.settings-overlay').remove()">취소</button>
    </div>
  </div>`;
  document.body.appendChild(overlay);
  // 포커스
  setTimeout(() => document.getElementById(formId + '_name')?.focus(), 100);
}

async function _submitCreatePipeline(formId, btn) {
  const name = document.getElementById(formId + '_name').value.trim();
  const project_path = document.getElementById(formId + '_path').value.trim();
  const command = document.getElementById(formId + '_cmd').value.trim();
  const interval = document.getElementById(formId + '_interval').value.trim();
  const on_complete = document.getElementById(formId + '_chain').value;

  if (!project_path) { showToast('프로젝트 경로를 입력하세요', 'error'); return; }
  if (!command) { showToast('명령어를 입력하세요', 'error'); return; }

  btn.disabled = true;
  btn.textContent = '생성 중...';
  try {
    await apiFetch('/api/pipelines', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, project_path, command, interval, on_complete }),
    });
    showToast('자동화 생성 완료');
    btn.closest('.settings-overlay').remove();
    fetchPipelines();
    fetchJobs();
  } catch (err) {
    showToast(err.message || '생성 실패', 'error');
    btn.disabled = false;
    btn.textContent = '생성 및 실행';
  }
}

/* ── 실행 이력 모달 ── */
async function showPipelineHistory(pipeId) {
  try {
    const data = await apiFetch(`/api/pipelines/${encodeURIComponent(pipeId)}/history`);
    const overlay = document.createElement('div');
    overlay.className = 'settings-overlay';
    overlay.style.cssText = 'display:flex;align-items:center;justify-content:center;';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    const entries = data.entries || [];
    let tableHtml = '';
    if (entries.length === 0) {
      tableHtml = '<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:0.8rem;">실행 이력이 없습니다.</div>';
    } else {
      const rows = entries.map((h, i) => {
        const cls = h.classification || 'unknown';
        const clsBadge = cls === 'has_change'
          ? '<span class="pipe-hist-badge pipe-hist-change">변경</span>'
          : cls === 'no_change'
            ? '<span class="pipe-hist-badge pipe-hist-nochange">무변경</span>'
            : '<span class="pipe-hist-badge pipe-hist-unknown">?</span>';
        const dur = h.duration_ms ? `${(h.duration_ms / 1000).toFixed(1)}s` : '-';
        const time = h.completed_at || '';
        const resultPreview = escapeHtml((h.result || '').substring(0, 120));
        return `<tr>
          <td style="white-space:nowrap;">${time}</td>
          <td>${clsBadge}</td>
          <td>${dur}</td>
          <td class="pipe-hist-result" title="${escapeHtml(h.result || '')}">${resultPreview}${(h.result || '').length > 120 ? '...' : ''}</td>
        </tr>`;
      }).join('');
      tableHtml = `<div class="pipe-hist-table-wrap"><table class="pipe-hist-table">
        <thead><tr><th>시간</th><th>분류</th><th>소요</th><th>결과 요약</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>`;
    }

    const summaryHtml = `<div style="display:flex;gap:12px;font-size:0.72rem;color:var(--text-muted);margin-bottom:12px;">
      <span>총 ${data.run_count}회 실행</span>
    </div>`;

    overlay.innerHTML = `<div class="settings-panel" style="max-width:700px;margin:0;">
      <div class="settings-header">
        <div class="settings-title" style="display:flex;align-items:center;gap:8px;">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
          <span>${escapeHtml(data.name || pipeId)} — 실행 이력</span>
        </div>
        <button class="settings-close" onclick="this.closest('.settings-overlay').remove()">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
      <div class="settings-body" style="padding:12px 16px;">
        ${summaryHtml}
        ${tableHtml}
      </div>
      <div class="settings-footer">
        <button class="btn btn-sm" onclick="this.closest('.settings-overlay').remove()">닫기</button>
      </div>
    </div>`;
    document.body.appendChild(overlay);
  } catch (err) {
    showToast(err.message || '이력 조회 실패', 'error');
  }
}

// fetchPipelines 후 진화 요약도 갱신
const _origFetchPipelines = fetchPipelines;
fetchPipelines = async function() {
  await _origFetchPipelines();
  fetchEvolutionSummary();
};
