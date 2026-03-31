/* ═══════════════════════════════════════════════
   Presets — 전송 폼 프리셋 저장/불러오기
   ═══════════════════════════════════════════════ */

let _presets = [];
let _presetMenuOpen = false;

// ── API ─────────────────────────────────────────

async function fetchPresets() {
  try {
    _presets = await apiFetch('/api/presets');
  } catch { _presets = []; }
  _renderPresetBar();
}

async function saveCurrentAsPreset() {
  const name = prompt(t('preset_name_prompt'));
  if (!name || !name.trim()) return;

  const config = _captureFormState();
  if (!config.skill_ids.length && !config.prompt && !config.cwd) {
    showToast(t('preset_empty_warn'), 'error');
    return;
  }

  try {
    const preset = await apiFetch('/api/presets', {
      method: 'POST',
      body: JSON.stringify({ name: name.trim(), config }),
    });
    showToast(t('preset_saved'));
    await fetchPresets();
  } catch (err) {
    showToast(t('preset_save_failed') + ': ' + err.message, 'error');
  }
}

async function deletePreset(presetId, e) {
  if (e) e.stopPropagation();
  if (!confirm(t('preset_delete_confirm'))) return;
  try {
    await apiFetch(`/api/presets/${encodeURIComponent(presetId)}`, { method: 'DELETE' });
    showToast(t('preset_deleted'));
    await fetchPresets();
  } catch (err) {
    showToast(t('preset_delete_failed') + ': ' + err.message, 'error');
  }
}

// ── 상태 캡처/복원 ──────────────────────────────

function _captureFormState() {
  return {
    prompt: document.getElementById('promptInput').value || '',
    cwd: document.getElementById('cwdInput').value || '',
    skill_ids: typeof _selectedSkills !== 'undefined' ? Array.from(_selectedSkills) : [],
    automation_mode: typeof _automationMode !== 'undefined' ? _automationMode : false,
    automation_interval: _automationMode
      ? (document.getElementById('automationInterval').value || null)
      : null,
    context_mode: typeof _contextMode !== 'undefined' ? _contextMode : 'new',
  };
}

function applyPreset(presetId) {
  const preset = _presets.find(p => p.id === presetId);
  if (!preset) return;
  const cfg = preset.config || {};

  // 프롬프트
  const promptInput = document.getElementById('promptInput');
  if (cfg.prompt) {
    promptInput.value = cfg.prompt;
    if (typeof updatePromptMirror === 'function') updatePromptMirror();
  }

  // CWD
  if (cfg.cwd) {
    document.getElementById('cwdInput').value = cfg.cwd;
    const display = document.getElementById('dirPickerText');
    if (display) { display.textContent = cfg.cwd; display.style.color = ''; }
    const clearBtn = document.getElementById('dirPickerClear');
    if (clearBtn) clearBtn.style.display = '';
  }

  // 스킬 선택 복원
  if (typeof _selectedSkills !== 'undefined' && cfg.skill_ids && cfg.skill_ids.length > 0) {
    _selectedSkills.clear();
    for (const sid of cfg.skill_ids) _selectedSkills.add(sid);
    if (typeof _renderSkillsSection === 'function') _renderSkillsSection();
  }

  // 자동화 모드
  if (cfg.automation_mode && !_automationMode) {
    if (typeof toggleAutomation === 'function') toggleAutomation();
    if (cfg.automation_interval) {
      document.getElementById('automationInterval').value = cfg.automation_interval;
    }
  } else if (!cfg.automation_mode && _automationMode) {
    if (typeof toggleAutomation === 'function') toggleAutomation();
  }

  // 컨텍스트 모드
  if (cfg.context_mode && cfg.context_mode !== 'new' && typeof setContextMode === 'function') {
    setContextMode(cfg.context_mode);
  }

  _closePresetMenu();
  showToast(t('preset_loaded') + ': ' + preset.name);
  promptInput.focus();
}

// ── 렌더링 ──────────────────────────────────────

function _renderPresetBar() {
  const bar = document.getElementById('presetBar');
  if (!bar) return;

  const countEl = document.getElementById('presetCount');
  if (countEl) countEl.textContent = _presets.length || '';

  const listEl = document.getElementById('presetDropdownList');
  if (!listEl) return;

  if (_presets.length === 0) {
    listEl.innerHTML = `<div class="preset-empty">${escapeHtml(t('preset_none'))}</div>`;
    return;
  }

  listEl.innerHTML = _presets.map(p => {
    const cfg = p.config || {};
    const tags = [];
    if (cfg.skill_ids && cfg.skill_ids.length > 0) {
      const names = (cfg.skill_names || cfg.skill_ids).slice(0, 3);
      tags.push(...names.map(n => `<span class="preset-tag preset-tag-skill">${escapeHtml(n)}</span>`));
    }
    if (cfg.automation_mode) tags.push(`<span class="preset-tag preset-tag-auto">${escapeHtml(t('automation'))}</span>`);
    if (cfg.cwd) tags.push(`<span class="preset-tag preset-tag-cwd" title="${escapeHtml(cfg.cwd)}">${escapeHtml(cfg.cwd.split('/').pop())}</span>`);

    return `<div class="preset-item" onclick="applyPreset('${escapeHtml(p.id)}')">
      <div class="preset-item-header">
        <span class="preset-item-name">${escapeHtml(p.name)}</span>
        <button class="preset-item-del" onclick="deletePreset('${escapeHtml(p.id)}', event)" title="${escapeHtml(t('delete_label'))}">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
      ${tags.length ? `<div class="preset-item-tags">${tags.join('')}</div>` : ''}
      ${cfg.prompt ? `<div class="preset-item-prompt">${escapeHtml(cfg.prompt.slice(0, 60))}${cfg.prompt.length > 60 ? '...' : ''}</div>` : ''}
    </div>`;
  }).join('');
}

function togglePresetMenu() {
  _presetMenuOpen = !_presetMenuOpen;
  const dropdown = document.getElementById('presetDropdown');
  if (!dropdown) return;
  dropdown.classList.toggle('open', _presetMenuOpen);
  if (_presetMenuOpen) {
    setTimeout(() => document.addEventListener('click', _onPresetOutsideClick, { once: true }), 0);
  }
}

function _closePresetMenu() {
  _presetMenuOpen = false;
  const dropdown = document.getElementById('presetDropdown');
  if (dropdown) dropdown.classList.remove('open');
}

function _onPresetOutsideClick(e) {
  const bar = document.getElementById('presetBar');
  if (bar && bar.contains(e.target)) {
    if (_presetMenuOpen) {
      setTimeout(() => document.addEventListener('click', _onPresetOutsideClick, { once: true }), 0);
    }
    return;
  }
  _closePresetMenu();
}

// ── 초기화 ──────────────────────────────────────
fetchPresets();
