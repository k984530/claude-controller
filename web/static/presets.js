/* ===================================================
   Presets -- 자동화 프리셋 브라우징/적용 UI
   =================================================== */

let _presets = [];
let _presetsPanelOpen = false;

const _PRESET_ICONS = {
  rocket:   '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="M12 15l-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/></svg>',
  search:   '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
  book:     '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>',
  shield:   '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
  layers:   '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>',
  bookmark: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>',
};

async function fetchPresets() {
  try {
    _presets = await apiFetch('/api/presets');
    renderPresetCards();
  } catch { /* silent */ }
}

function renderPresetCards() {
  const container = document.getElementById('presetGrid');
  if (!container) return;

  if (_presets.length === 0) {
    container.innerHTML = '<div class="empty-state" style="padding:20px;text-align:center;color:var(--text-muted);font-size:0.8rem;">프리셋이 없습니다.</div>';
    return;
  }

  container.innerHTML = _presets.map(p => {
    const icon = _PRESET_ICONS[p.icon] || _PRESET_ICONS.layers;
    const pipeNames = (p.pipeline_names || []).map(n => escapeHtml(n)).join(' &rarr; ');
    const builtinBadge = p.builtin
      ? '<span class="preset-badge preset-badge-builtin">내장</span>'
      : '<span class="preset-badge preset-badge-custom">커스텀</span>';

    return `<div class="preset-card" data-preset-id="${escapeHtml(p.id)}">
      <div class="preset-card-icon">${icon}</div>
      <div class="preset-card-body">
        <div class="preset-card-header">
          <span class="preset-card-name">${escapeHtml(p.name)}</span>
          ${builtinBadge}
        </div>
        <div class="preset-card-desc">${escapeHtml(p.description)}</div>
        <div class="preset-card-pipes">${pipeNames} <span class="preset-pipe-count">(${p.pipeline_count}개)</span></div>
      </div>
      <div class="preset-card-actions">
        <button class="btn btn-sm btn-primary" onclick="openApplyPreset('${escapeHtml(p.id)}')">적용</button>
        ${!p.builtin ? `<button class="btn btn-sm btn-danger" onclick="deletePreset('${escapeHtml(p.id)}')">삭제</button>` : ''}
      </div>
    </div>`;
  }).join('');
}

function openApplyPreset(presetId) {
  const preset = _presets.find(p => p.id === presetId);
  if (!preset) return;

  const overlayId = 'presetApply_' + Date.now();
  const overlay = document.createElement('div');
  overlay.className = 'settings-overlay';
  overlay.style.cssText = 'display:flex;align-items:center;justify-content:center;';
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

  const icon = _PRESET_ICONS[preset.icon] || _PRESET_ICONS.layers;

  overlay.innerHTML = `<div class="settings-panel" style="max-width:480px;margin:0;">
    <div class="settings-header">
      <div class="settings-title" style="display:flex;align-items:center;gap:8px;">
        ${icon}
        <span>프리셋 적용: ${escapeHtml(preset.name)}</span>
      </div>
      <button class="settings-close" onclick="this.closest('.settings-overlay').remove()">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
    <div class="settings-body">
      <div style="margin-bottom:12px;font-size:0.78rem;color:var(--text-secondary);">
        ${escapeHtml(preset.description)}
      </div>
      <div style="margin-bottom:12px;font-size:0.72rem;color:var(--text-muted);display:flex;gap:6px;flex-wrap:wrap;">
        ${(preset.pipeline_names || []).map(n => `<span class="preset-pipe-tag">${escapeHtml(n)}</span>`).join('')}
      </div>
      <div style="margin-bottom:12px;">
        <label style="font-size:0.72rem;font-weight:600;color:var(--text-secondary);display:block;margin-bottom:4px;">프로젝트 경로</label>
        <div style="display:flex;gap:6px;">
          <input id="${overlayId}_path" type="text" placeholder="/path/to/project"
            value="${escapeHtml(document.getElementById('cwdInput')?.value || '')}"
            style="flex:1;padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-secondary);color:var(--text-primary);font-size:0.8rem;font-family:var(--font-mono,monospace);">
          <button class="btn btn-sm" onclick="_browseForPreset('${overlayId}_path')" title="디렉토리 탐색">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
          </button>
        </div>
      </div>
    </div>
    <div class="settings-footer" style="display:flex;gap:6px;">
      <button class="btn btn-sm btn-primary" onclick="_doApplyPreset('${escapeHtml(presetId)}','${overlayId}',this)">적용하기</button>
      <button class="btn btn-sm" onclick="this.closest('.settings-overlay').remove()">취소</button>
    </div>
  </div>`;
  document.body.appendChild(overlay);
}

function _browseForPreset(inputId) {
  // 기존 디렉토리 브라우저를 재활용: 선택 후 해당 input에 값 설정
  const input = document.getElementById(inputId);
  if (!input) return;
  // 임시로 cwdInput에 연결하여 기존 dir browser 활용
  const origCwd = document.getElementById('cwdInput')?.value || '';
  toggleDirBrowser();
  // dirBrowser 선택 시 cwdInput에 값이 설정되므로 polling으로 감지
  const poll = setInterval(() => {
    const newVal = document.getElementById('cwdInput')?.value || '';
    if (newVal && newVal !== origCwd) {
      input.value = newVal;
      clearInterval(poll);
    }
  }, 300);
  setTimeout(() => clearInterval(poll), 30000);
}

async function _doApplyPreset(presetId, overlayId, btn) {
  const path = document.getElementById(overlayId + '_path').value.trim();
  if (!path) { showToast('프로젝트 경로를 입력하세요', 'error'); return; }

  btn.disabled = true;
  btn.textContent = '적용 중...';
  try {
    const result = await apiFetch('/api/presets/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset_id: presetId, project_path: path }),
    });
    showToast(`프리셋 "${result.preset_name}" 적용 완료 (${result.pipelines_created}개 파이프라인 생성)`);
    btn.closest('.settings-overlay').remove();
    // 생성된 파이프라인 중 첫 번째를 즉시 실행 (나머지는 체이닝 또는 타이머로 자동 시작)
    if (result.pipelines && result.pipelines.length > 0) {
      runPipeline(result.pipelines[0].id);
    }
    fetchPipelines();
  } catch (err) {
    showToast(`적용 실패: ${err.message}`, 'error');
    btn.disabled = false;
    btn.textContent = '적용하기';
  }
}

async function deletePreset(presetId) {
  if (!confirm('이 프리셋을 삭제하시겠습니까?')) return;
  try {
    await apiFetch(`/api/presets/${encodeURIComponent(presetId)}`, { method: 'DELETE' });
    showToast('프리셋 삭제됨');
    fetchPresets();
  } catch (err) {
    showToast(err.message || '삭제 실패', 'error');
  }
}

/* -- 현재 파이프라인을 프리셋으로 저장 -- */

function openSavePresetDialog() {
  if (_pipelines.length === 0) {
    showToast('저장할 파이프라인이 없습니다', 'error');
    return;
  }
  const dlgId = 'presetSave_' + Date.now();
  const overlay = document.createElement('div');
  overlay.className = 'settings-overlay';
  overlay.style.cssText = 'display:flex;align-items:center;justify-content:center;';
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

  const pipeChecks = _pipelines.map(p =>
    `<label style="display:flex;gap:6px;align-items:center;font-size:0.78rem;color:var(--text-primary);">
      <input type="checkbox" value="${escapeHtml(p.id)}" checked style="accent-color:var(--primary);">
      ${escapeHtml(p.name || p.id)}
      <span style="font-size:0.65rem;color:var(--text-muted);">${escapeHtml(p.interval || '1회')}</span>
    </label>`
  ).join('');

  overlay.innerHTML = `<div class="settings-panel" style="max-width:440px;margin:0;">
    <div class="settings-header">
      <div class="settings-title" style="display:flex;align-items:center;gap:8px;">
        ${_PRESET_ICONS.bookmark}
        <span>프리셋으로 저장</span>
      </div>
      <button class="settings-close" onclick="this.closest('.settings-overlay').remove()">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
    <div class="settings-body">
      <div style="margin-bottom:12px;">
        <label style="font-size:0.72rem;font-weight:600;color:var(--text-secondary);display:block;margin-bottom:4px;">프리셋 이름</label>
        <input id="${dlgId}_name" type="text" placeholder="나의 자동화 프리셋"
          style="width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-secondary);color:var(--text-primary);font-size:0.8rem;box-sizing:border-box;">
      </div>
      <div style="margin-bottom:12px;">
        <label style="font-size:0.72rem;font-weight:600;color:var(--text-secondary);display:block;margin-bottom:4px;">설명</label>
        <input id="${dlgId}_desc" type="text" placeholder="이 프리셋의 용도를 설명하세요"
          style="width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-secondary);color:var(--text-primary);font-size:0.8rem;box-sizing:border-box;">
      </div>
      <div style="margin-bottom:8px;">
        <label style="font-size:0.72rem;font-weight:600;color:var(--text-secondary);display:block;margin-bottom:6px;">포함할 파이프라인</label>
        <div id="${dlgId}_pipes" style="display:flex;flex-direction:column;gap:6px;max-height:200px;overflow-y:auto;">
          ${pipeChecks}
        </div>
      </div>
    </div>
    <div class="settings-footer" style="display:flex;gap:6px;">
      <button class="btn btn-sm btn-primary" onclick="_doSavePreset('${dlgId}',this)">저장</button>
      <button class="btn btn-sm" onclick="this.closest('.settings-overlay').remove()">취소</button>
    </div>
  </div>`;
  document.body.appendChild(overlay);
}

async function _doSavePreset(dlgId, btn) {
  const name = document.getElementById(dlgId + '_name').value.trim();
  if (!name) { showToast('프리셋 이름을 입력하세요', 'error'); return; }

  const desc = document.getElementById(dlgId + '_desc').value.trim();
  const checks = document.querySelectorAll(`#${dlgId}_pipes input[type="checkbox"]:checked`);
  const pipeIds = Array.from(checks).map(c => c.value);
  if (pipeIds.length === 0) { showToast('최소 1개 파이프라인을 선택하세요', 'error'); return; }

  btn.disabled = true;
  btn.textContent = '저장 중...';
  try {
    const result = await apiFetch('/api/presets/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description: desc, pipeline_ids: pipeIds }),
    });
    showToast(`프리셋 "${result.name}" 저장됨 (${result.pipeline_count}개 파이프라인)`);
    btn.closest('.settings-overlay').remove();
    fetchPresets();
  } catch (err) {
    showToast(`저장 실패: ${err.message}`, 'error');
    btn.disabled = false;
    btn.textContent = '저장';
  }
}
