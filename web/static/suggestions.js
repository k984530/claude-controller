/* ═══════════════════════════════════════════════
   Suggestions — 스킬/자동화 개선 제안 UI
   작업 이력을 분석하여 제안을 생성하고
   사용자가 적용/무시를 선택할 수 있다.
   ═══════════════════════════════════════════════ */

let _suggestions = [];
let _sugLoading = false;

/* ── 데이터 로드 ── */

async function loadSuggestions() {
  try {
    _suggestions = await apiFetch('/api/suggestions?status=pending');
    if (!Array.isArray(_suggestions)) _suggestions = [];
  } catch {
    _suggestions = [];
  }
  _renderSuggestions();
}

/* ── 분석 실행 ── */

async function generateSuggestions() {
  if (_sugLoading) return;
  _sugLoading = true;
  const btn = document.getElementById('btnGenerateSug');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = _sugSpinner() + ' ' + t('sug_analyzing');
  }

  try {
    const result = await apiFetch('/api/suggestions/generate', { method: 'POST' });
    const count = result.generated || 0;
    if (count > 0) {
      showToast(t('sug_new_count').replace('{n}', count));
    } else {
      showToast(t('sug_no_new'));
    }
    await loadSuggestions();
  } catch (e) {
    showToast(t('sug_analyze_fail') + ': ' + e.message, 'error');
  } finally {
    _sugLoading = false;
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = _sugBtnIcon() + ' ' + t('sug_start');
    }
  }
}

/* ── 제안 적용 ── */

async function applySuggestion(id) {
  const card = document.querySelector(`[data-sug-id="${id}"]`);
  if (card) card.classList.add('applying');

  try {
    const result = await apiFetch(`/api/suggestions/${id}/apply`, { method: 'POST' });
    showToast(t('sug_applied'));
    // 스킬이 변경되었을 수 있으므로 리로드
    if (typeof loadSkills === 'function') loadSkills();
    if (typeof fetchPipelines === 'function') fetchPipelines();
    await loadSuggestions();
  } catch (e) {
    showToast(t('sug_apply_fail') + ': ' + e.message, 'error');
    if (card) card.classList.remove('applying');
  }
}

/* ── 제안 무시 ── */

async function dismissSuggestion(id) {
  const card = document.querySelector(`[data-sug-id="${id}"]`);
  if (card) {
    card.style.opacity = '0.3';
    card.style.transform = 'translateX(20px)';
  }

  try {
    await apiFetch(`/api/suggestions/${id}/dismiss`, { method: 'POST' });
    await loadSuggestions();
  } catch (e) {
    showToast(t('sug_process_fail') + ': ' + e.message, 'error');
    if (card) {
      card.style.opacity = '';
      card.style.transform = '';
    }
  }
}

/* ── 렌더링 ── */

function _renderSuggestions() {
  const list = document.getElementById('suggestionsList');
  const empty = document.getElementById('suggestionsEmpty');
  const badge = document.getElementById('sugCount');
  if (!list) return;

  if (badge) {
    badge.textContent = _suggestions.length > 0 ? _suggestions.length : '';
  }

  if (_suggestions.length === 0) {
    list.innerHTML = '';
    if (empty) {
      empty.style.display = '';
      empty.innerHTML = `
        <p>${t('sug_no_pending')}</p>
        <p style="font-size:0.7rem;color:var(--text-muted);margin-top:4px;">
          ${t('sug_help')}
        </p>
      `;
    }
    return;
  }
  if (empty) empty.style.display = 'none';

  // 신뢰도순 정렬
  const sorted = [..._suggestions].sort((a, b) => (b.confidence || 0) - (a.confidence || 0));

  list.innerHTML = sorted.map(s => _renderSuggestionCard(s)).join('');
}

function _renderSuggestionCard(s) {
  const typeInfo = _sugTypeInfo(s.type);
  const confidencePct = Math.round((s.confidence || 0) * 100);
  const actionDesc = _sugActionDesc(s.action);

  return `
    <div class="sug-card" data-sug-id="${escapeHtml(s.id)}">
      <div class="sug-card-header">
        <span class="sug-type-badge sug-type-${escapeHtml(s.type)}">${typeInfo.icon} ${typeInfo.label}</span>
        <span class="sug-confidence" title="${t('sug_confidence').replace('{pct}', confidencePct)}">
          <span class="sug-confidence-bar" style="width:${confidencePct}%"></span>
          ${confidencePct}%
        </span>
      </div>
      <div class="sug-card-title">${escapeHtml(s.title)}</div>
      <div class="sug-card-desc">${escapeHtml(s.description)}</div>
      ${actionDesc ? `<div class="sug-card-preview">${actionDesc}</div>` : ''}
      <div class="sug-card-actions">
        <button class="sug-btn sug-btn-dismiss" onclick="event.stopPropagation();dismissSuggestion('${escapeHtml(s.id)}')" title="${t('sug_dismiss')}">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          ${t('sug_dismiss')}
        </button>
        <button class="sug-btn sug-btn-apply" onclick="event.stopPropagation();applySuggestion('${escapeHtml(s.id)}')">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
          ${t('sug_apply')}
        </button>
      </div>
    </div>
  `;
}

/* ── 유틸 ── */

function _sugTypeInfo(type) {
  const map = {
    'new_skill': { label: t('sug_type_new_skill'), icon: '⚡' },
    'improve_skill': { label: t('sug_type_improve_skill'), icon: '🔧' },
    'new_pipeline': { label: t('sug_type_new_pipeline'), icon: '⏱' },
    'cleanup': { label: t('sug_type_cleanup'), icon: '🧹' },
  };
  return map[type] || { label: type, icon: '💡' };
}

function _sugActionDesc(action) {
  if (!action || !action.payload) return '';
  const p = action.payload;

  if (action.type === 'new_skill') {
    const cat = { plan: t('skill_cat_plan'), dev: t('skill_cat_dev'), design: t('skill_cat_design'), verify: t('skill_cat_verify'), etc: t('skill_cat_etc') };
    return `<span class="sug-preview-label">${t('sug_label_category')}:</span> ${escapeHtml(cat[p.category] || p.category)} · `
         + `<span class="sug-preview-label">${t('name_label')}:</span> ${escapeHtml(p.name || '')}`;
  }
  if (action.type === 'new_pipeline') {
    return `<span class="sug-preview-label">${t('sug_label_interval')}:</span> ${escapeHtml(p.interval || '')} · `
         + `<span class="sug-preview-label">${t('project_label')}:</span> ${escapeHtml((p.project || '').split('/').pop())}`;
  }
  if (action.type === 'improve_skill') {
    return `<span class="sug-preview-label">${t('sug_label_target')}:</span> ${escapeHtml(p.skill_id || p.name || '')}`;
  }
  if (action.type === 'cleanup_skill') {
    return `<span class="sug-preview-label">${t('sug_label_del_target')}:</span> ${escapeHtml(p.skill_id || '')}`;
  }
  return '';
}

function _sugSpinner() {
  return '<svg class="sug-spinner" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 11-6.219-8.56"/></svg>';
}

function _sugBtnIcon() {
  return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';
}

/* ── 초기화 ── */
loadSuggestions();
