/* ===================================================
   Personas -- 직군별 전문가 페르소나 관리 UI
   =================================================== */

let _personas = [];
let _selectedPersona = null; // 전송 시 적용할 페르소나 ID

const _PERSONA_ICONS = {
  compass:      '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></svg>',
  server:       '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>',
  layout:       '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>',
  palette:      '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="13.5" cy="6.5" r="0.5" fill="currentColor"/><circle cx="17.5" cy="10.5" r="0.5" fill="currentColor"/><circle cx="8.5" cy="7.5" r="0.5" fill="currentColor"/><circle cx="6.5" cy="12.5" r="0.5" fill="currentColor"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/></svg>',
  'check-circle':'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
  shield:       '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
  cloud:        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/></svg>',
  database:     '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>',
  user:         '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
};

async function fetchPersonas() {
  try {
    _personas = await apiFetch('/api/personas');
    renderPersonaCards();
    _updatePersonaPicker();
  } catch { /* silent */ }
}

function renderPersonaCards() {
  const container = document.getElementById('personaGrid');
  if (!container) return;

  if (_personas.length === 0) {
    container.innerHTML = '<div class="empty-state" style="padding:20px;text-align:center;color:var(--text-muted);font-size:0.8rem;">페르소나가 없습니다.</div>';
    return;
  }

  container.innerHTML = _personas.map(p => {
    const icon = _PERSONA_ICONS[p.icon] || _PERSONA_ICONS.user;
    const builtinBadge = p.builtin
      ? '<span class="persona-badge persona-badge-builtin">내장</span>'
      : '<span class="persona-badge persona-badge-custom">커스텀</span>';

    return `<div class="persona-card" data-persona-id="${escapeHtml(p.id)}" style="--persona-color:${escapeHtml(p.color)}">
      <div class="persona-card-avatar" style="background:${escapeHtml(p.color)}20;color:${escapeHtml(p.color)}">${icon}</div>
      <div class="persona-card-body">
        <div class="persona-card-header">
          <span class="persona-card-name">${escapeHtml(p.name)}</span>
          ${builtinBadge}
        </div>
        <div class="persona-card-desc">${escapeHtml(p.description)}</div>
      </div>
      <div class="persona-card-actions">
        <button class="btn btn-sm btn-primary" onclick="selectPersonaForSend('${escapeHtml(p.id)}')" title="이 페르소나로 작업 전송">배정</button>
        <button class="btn btn-sm" onclick="openPersonaDetail('${escapeHtml(p.id)}')" title="상세 보기">상세</button>
        ${!p.builtin ? `<button class="btn btn-sm btn-danger" onclick="deletePersona('${escapeHtml(p.id)}')">삭제</button>` : ''}
      </div>
    </div>`;
  }).join('');
}

/* ── 페르소나 선택 (전송 폼 연동) ── */

function selectPersonaForSend(personaId) {
  if (_selectedPersona === personaId) {
    _selectedPersona = null;
  } else {
    _selectedPersona = personaId;
  }
  _updatePersonaPicker();
  const persona = _personas.find(p => p.id === personaId);
  if (_selectedPersona && persona) {
    showToast(`${persona.name} 페르소나 배정됨`);
  } else {
    showToast('페르소나 배정 해제됨');
  }
}

function clearPersonaSelection() {
  _selectedPersona = null;
  _updatePersonaPicker();
}

function _updatePersonaPicker() {
  const badge = document.getElementById('personaBadge');
  if (!badge) return;
  if (_selectedPersona) {
    const p = _personas.find(x => x.id === _selectedPersona);
    if (p) {
      const icon = _PERSONA_ICONS[p.icon] || _PERSONA_ICONS.user;
      badge.innerHTML = `<span class="persona-active-badge" style="--persona-color:${escapeHtml(p.color)}" onclick="clearPersonaSelection()" title="${escapeHtml(p.name)} (클릭하여 해제)">${icon} ${escapeHtml(p.name)}</span>`;
      badge.style.display = '';
      return;
    }
  }
  badge.innerHTML = '';
  badge.style.display = 'none';
}

/* ── 페르소나 상세 다이얼로그 ── */

async function openPersonaDetail(personaId) {
  let persona;
  try {
    persona = await apiFetch(`/api/personas/${encodeURIComponent(personaId)}`);
  } catch (err) {
    showToast(err.message, 'error');
    return;
  }

  const icon = _PERSONA_ICONS[persona.icon] || _PERSONA_ICONS.user;
  const overlay = document.createElement('div');
  overlay.className = 'settings-overlay';
  overlay.style.cssText = 'display:flex;align-items:center;justify-content:center;';
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

  overlay.innerHTML = `<div class="settings-panel" style="max-width:560px;margin:0;">
    <div class="settings-header">
      <div class="settings-title" style="display:flex;align-items:center;gap:8px;">
        <span style="color:${escapeHtml(persona.color)}">${icon}</span>
        <span>${escapeHtml(persona.name)}</span>
        ${persona.builtin ? '<span class="persona-badge persona-badge-builtin">내장</span>' : '<span class="persona-badge persona-badge-custom">커스텀</span>'}
      </div>
      <button class="settings-close" onclick="this.closest('.settings-overlay').remove()">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
    <div class="settings-body">
      <div style="margin-bottom:12px;font-size:0.78rem;color:var(--text-secondary);">${escapeHtml(persona.description)}</div>
      <div style="margin-bottom:8px;">
        <label style="font-size:0.72rem;font-weight:600;color:var(--text-secondary);display:block;margin-bottom:6px;">시스템 프롬프트</label>
        <pre class="persona-prompt-preview">${escapeHtml(persona.system_prompt || '(없음)')}</pre>
      </div>
    </div>
    <div class="settings-footer" style="display:flex;gap:6px;">
      <button class="btn btn-sm btn-primary" onclick="selectPersonaForSend('${escapeHtml(persona.id)}');this.closest('.settings-overlay').remove();">배정</button>
      <button class="btn btn-sm" onclick="this.closest('.settings-overlay').remove()">닫기</button>
    </div>
  </div>`;
  document.body.appendChild(overlay);
}

/* ── 커스텀 페르소나 생성 다이얼로그 ── */

function openCreatePersonaDialog() {
  const dlgId = 'personaCreate_' + Date.now();
  const overlay = document.createElement('div');
  overlay.className = 'settings-overlay';
  overlay.style.cssText = 'display:flex;align-items:center;justify-content:center;';
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

  const roleOptions = ['custom','planner','developer','designer','qa','security','devops','data']
    .map(r => `<option value="${r}">${r}</option>`).join('');

  overlay.innerHTML = `<div class="settings-panel" style="max-width:520px;margin:0;">
    <div class="settings-header">
      <div class="settings-title" style="display:flex;align-items:center;gap:8px;">
        ${_PERSONA_ICONS.user}
        <span>페르소나 만들기</span>
      </div>
      <button class="settings-close" onclick="this.closest('.settings-overlay').remove()">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
    <div class="settings-body">
      <div style="margin-bottom:10px;">
        <label class="persona-dlg-label">이름 *</label>
        <input id="${dlgId}_name" type="text" class="persona-dlg-input" placeholder="예: 코드 아키텍트">
      </div>
      <div style="margin-bottom:10px;">
        <label class="persona-dlg-label">역할</label>
        <select id="${dlgId}_role" class="persona-dlg-input">${roleOptions}</select>
      </div>
      <div style="margin-bottom:10px;">
        <label class="persona-dlg-label">설명</label>
        <input id="${dlgId}_desc" type="text" class="persona-dlg-input" placeholder="이 페르소나의 전문 분야를 설명하세요">
      </div>
      <div style="margin-bottom:10px;">
        <label class="persona-dlg-label">시스템 프롬프트 *</label>
        <textarea id="${dlgId}_prompt" class="persona-dlg-input" rows="8" placeholder="당신은 ... 전문가입니다.\n\n## 역할\n- ...\n\n## 원칙\n- ..."></textarea>
      </div>
    </div>
    <div class="settings-footer" style="display:flex;gap:6px;">
      <button class="btn btn-sm btn-primary" onclick="_doCreatePersona('${dlgId}',this)">생성</button>
      <button class="btn btn-sm" onclick="this.closest('.settings-overlay').remove()">취소</button>
    </div>
  </div>`;
  document.body.appendChild(overlay);
}

async function _doCreatePersona(dlgId, btn) {
  const name = document.getElementById(dlgId + '_name').value.trim();
  const role = document.getElementById(dlgId + '_role').value;
  const desc = document.getElementById(dlgId + '_desc').value.trim();
  const prompt = document.getElementById(dlgId + '_prompt').value.trim();

  if (!name) { showToast('이름을 입력하세요', 'error'); return; }
  if (!prompt) { showToast('시스템 프롬프트를 입력하세요', 'error'); return; }

  btn.disabled = true;
  btn.textContent = '생성 중...';
  try {
    await apiFetch('/api/personas', {
      method: 'POST',
      body: JSON.stringify({ name, role, description: desc, system_prompt: prompt }),
    });
    showToast(`페르소나 "${name}" 생성됨`);
    btn.closest('.settings-overlay').remove();
    fetchPersonas();
  } catch (err) {
    showToast(`생성 실패: ${err.message}`, 'error');
    btn.disabled = false;
    btn.textContent = '생성';
  }
}

/* ── 삭제 ── */

async function deletePersona(personaId) {
  if (!confirm('이 페르소나를 삭제하시겠습니까?')) return;
  try {
    await apiFetch(`/api/personas/${encodeURIComponent(personaId)}`, { method: 'DELETE' });
    showToast('페르소나 삭제됨');
    if (_selectedPersona === personaId) clearPersonaSelection();
    fetchPersonas();
  } catch (err) {
    showToast(err.message || '삭제 실패', 'error');
  }
}
