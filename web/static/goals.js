/* ═══════════════════════════════════════════════
   Goals — 전체 프로젝트 현황 대시보드
   data/goals/*.md (YAML frontmatter + checkbox)
   모든 프로젝트의 Goal을 그룹별로 한눈에 조회
   ═══════════════════════════════════════════════ */

let _goals = [];
let _goalFilter = 'active';

function _goalProject() {
  return (document.getElementById('cwdInput')?.value || '').trim();
}

function _projectShort(path) {
  if (!path) return t('unspecified');
  return path.replace(/\/+$/, '').split('/').pop() || path;
}

async function loadGoals() {
  try {
    const qs = _goalFilter !== 'all' ? `?status=${_goalFilter}` : '';
    _goals = await apiFetch('/api/goals' + qs);
    if (!Array.isArray(_goals)) _goals = [];
  } catch {
    _goals = [];
  }
  _renderGoals();
}

function setGoalFilter(status) {
  _goalFilter = status;
  document.querySelectorAll('.goal-filter-btn').forEach(b => b.classList.remove('active'));
  const btn = document.querySelector(`.goal-filter-btn[data-filter="${status}"]`);
  if (btn) btn.classList.add('active');
  loadGoals();
}

/* ── 프로젝트별 그룹 렌더링 ── */

function _renderGoals() {
  const list = document.getElementById('goalsList');
  const empty = document.getElementById('goalsEmpty');
  if (!list) return;

  if (_goals.length === 0) {
    list.innerHTML = '';
    if (empty) {
      empty.style.display = '';
      empty.innerHTML = `<p>${t('goal_empty')}</p><button class="btn-small" onclick="openGoalCreate()">${t('goal_add')}</button>`;
    }
    return;
  }
  if (empty) empty.style.display = 'none';

  // 프로젝트별 그룹화
  const groups = {};
  for (const g of _goals) {
    const key = g.project || '';
    if (!groups[key]) groups[key] = [];
    groups[key].push(g);
  }

  // 현재 선택된 CWD의 프로젝트를 최상단으로
  const currentCwd = _goalProject();
  const sortedKeys = Object.keys(groups).sort((a, b) => {
    if (a === currentCwd) return -1;
    if (b === currentCwd) return 1;
    return a.localeCompare(b);
  });

  list.innerHTML = sortedKeys.map(projectPath => {
    const goals = groups[projectPath];
    const totalTasks = goals.reduce((s, g) => s + g.tasks_total, 0);
    const doneTasks = goals.reduce((s, g) => s + g.tasks_done, 0);
    const pct = totalTasks > 0 ? Math.round((doneTasks / totalTasks) * 100) : 0;
    const isCurrent = projectPath === currentCwd;
    const shortName = _projectShort(projectPath);

    return `
      <div class="goal-group${isCurrent ? ' current' : ''}">
        <div class="goal-group-header" title="${escapeHtml(projectPath)}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
          <span class="goal-group-name">${escapeHtml(shortName)}</span>
          ${totalTasks > 0 ? `
            <div class="goal-group-progress">
              <div class="goal-progress-bar" style="width:60px;">
                <div class="goal-progress-fill" style="width:${pct}%"></div>
              </div>
              <span class="goal-progress-text">${doneTasks}/${totalTasks}</span>
            </div>
          ` : ''}
          <span class="goal-group-count">${goals.length}</span>
          ${doneTasks < totalTasks ? `
            <button class="goal-dispatch-next-btn" data-dispatch-project="${escapeHtml(projectPath)}" onclick="event.stopPropagation();_dispatchNext(this.dataset.dispatchProject)" title="${t('goal_dispatch_title')}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            </button>
          ` : ''}
        </div>
        <div class="goal-group-cards">
          ${goals.map(g => _renderGoalCard(g)).join('')}
        </div>
      </div>
    `;
  }).join('');
}

function _renderGoalCard(g) {
  const pct = g.tasks_total > 0 ? Math.round((g.tasks_done / g.tasks_total) * 100) : 0;
  const statusCls = g.status === 'completed' ? 'done' : g.status === 'archived' ? 'archived' : '';
  return `
    <div class="goal-card ${statusCls}" data-goal-id="${escapeHtml(g.id)}">
      <div class="goal-card-header">
        <span class="goal-card-title">${escapeHtml(g.title)}</span>
        ${g.tasks_total > 0 ? `<span class="goal-progress-text">${g.tasks_done}/${g.tasks_total}</span>` : ''}
        ${g.status === 'active' && g.tasks_done < g.tasks_total ? `
          <button class="goal-exec-btn" data-exec-goal="${escapeHtml(g.id)}" title="${t('goal_exec_title')}">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          </button>
        ` : ''}
      </div>
      ${g.tasks_total > 0 ? `
        <div class="goal-progress">
          <div class="goal-progress-bar">
            <div class="goal-progress-fill" style="width:${pct}%"></div>
          </div>
        </div>
      ` : ''}
    </div>
  `;
}

/* ── Goal 생성 ── */

function openGoalCreate(presetProject) {
  const project = presetProject || _goalProject();

  const prev = document.getElementById('goalEditorOverlay');
  if (prev) prev.remove();

  const overlay = document.createElement('div');
  overlay.id = 'goalEditorOverlay';
  overlay.className = 'editor-overlay';
  overlay.innerHTML = `
    <div class="editor-modal goal-editor-modal">
      <div class="goal-editor-title">${t('goal_new_title')}</div>
      <label>${t('goal_label_path')}
        <input type="text" id="goalEdProject" value="${escapeHtml(project)}" placeholder="/path/to/project" />
      </label>
      <label>${t('goal_label_title')}
        <input type="text" id="goalEdTitle" placeholder="${t('goal_title_ph')}" />
      </label>
      <label>${t('goal_label_body')}
        <textarea id="goalEdBody" rows="10" placeholder="## Goal&#10;&#10;- [ ] Task 1&#10;- [ ] Task 2&#10;- [ ] Task 3"></textarea>
      </label>
      <div class="goal-editor-actions">
        <button class="btn-small btn-muted" onclick="document.getElementById('goalEditorOverlay').remove()">${t('cancel')}</button>
        <button class="btn-small" onclick="_createGoal(false)">${t('create')}</button>
        <button class="btn-small btn-execute" onclick="_createGoal(true)">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          ${t('goal_create_run')}
        </button>
      </div>
    </div>
  `;
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  document.body.appendChild(overlay);
  if (project) {
    document.getElementById('goalEdTitle').focus();
  } else {
    document.getElementById('goalEdProject').focus();
  }
}

async function _createGoal(executeNow) {
  const project = document.getElementById('goalEdProject').value.trim();
  const title = document.getElementById('goalEdTitle').value.trim();
  const body = document.getElementById('goalEdBody').value;
  if (!project) { showToast(t('goal_path_req'), 'error'); return; }
  if (!title) { showToast(t('goal_title_req'), 'error'); return; }

  try {
    const goal = await apiFetch('/api/goals', {
      method: 'POST',
      body: JSON.stringify({ title, body, project }),
    });
    document.getElementById('goalEditorOverlay').remove();
    showToast(executeNow ? t('goal_created_run') : t('goal_created'));
    loadGoals();
    if (executeNow && goal && goal.id) {
      _executeGoal(goal.id);
    }
  } catch (e) {
    showToast(t('goal_create_fail') + ': ' + e.message, 'error');
  }
}

/* ── Goal 상세 / 편집 ── */

async function openGoalDetail(goalId) {
  let goal;
  try {
    goal = await apiFetch(`/api/goals/${goalId}`);
  } catch {
    showToast(t('goal_load_fail'), 'error');
    return;
  }

  const prev = document.getElementById('goalEditorOverlay');
  if (prev) prev.remove();

  const projectShort = _projectShort(goal.project);

  const overlay = document.createElement('div');
  overlay.id = 'goalEditorOverlay';
  overlay.className = 'editor-overlay';
  overlay.innerHTML = `
    <div class="editor-modal goal-editor-modal">
      <div class="goal-editor-header">
        <div class="goal-editor-title">${escapeHtml(goal.title)} <span class="goal-project-badge">${escapeHtml(projectShort)}</span></div>
        <div class="goal-editor-header-actions">
          <select id="goalStatusSelect" class="goal-status-select">
            <option value="active" ${goal.status === 'active' ? 'selected' : ''}>active</option>
            <option value="completed" ${goal.status === 'completed' ? 'selected' : ''}>completed</option>
            <option value="archived" ${goal.status === 'archived' ? 'selected' : ''}>archived</option>
          </select>
          <button class="skills-icon-btn goal-delete-btn" onclick="_deleteGoal('${goal.id}')" title="${t('delete_label')}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
          </button>
        </div>
      </div>
      <label>${t('goal_label_title')}
        <input type="text" id="goalEdTitle" value="${escapeHtml(goal.title)}" />
      </label>
      <label>${t('goal_label_content')}
        <textarea id="goalEdBody" rows="14">${escapeHtml(goal.body || '')}</textarea>
      </label>
      <div class="goal-editor-actions">
        <button class="btn-small btn-muted" onclick="document.getElementById('goalEditorOverlay').remove()">${t('close')}</button>
        <button class="btn-small" onclick="_updateGoal('${goal.id}')">${t('save')}</button>
        ${goal.status === 'active' ? `
          <button class="btn-small btn-execute" onclick="_executeGoal('${goal.id}')">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            ${t('goal_ai_run')}
          </button>
        ` : ''}
      </div>
    </div>
  `;
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  document.body.appendChild(overlay);
}

async function _updateGoal(goalId) {
  const title = document.getElementById('goalEdTitle').value.trim();
  const body = document.getElementById('goalEdBody').value;
  const status = document.getElementById('goalStatusSelect').value;
  if (!title) { showToast(t('goal_title_req'), 'error'); return; }

  try {
    await apiFetch(`/api/goals/${goalId}/update`, {
      method: 'POST',
      body: JSON.stringify({ title, body, status }),
    });
    document.getElementById('goalEditorOverlay').remove();
    showToast(t('goal_saved'));
    loadGoals();
  } catch (e) {
    showToast(t('goal_save_fail') + ': ' + e.message, 'error');
  }
}

async function _deleteGoal(goalId) {
  if (!confirm(t('goal_confirm_del'))) return;
  try {
    await apiFetch(`/api/goals/${goalId}`, { method: 'DELETE' });
    document.getElementById('goalEditorOverlay').remove();
    showToast(t('goal_deleted'));
    loadGoals();
  } catch (e) {
    showToast(t('goal_delete_fail') + ': ' + e.message, 'error');
  }
}

/* ── AI 실행 ── */

async function _executeGoal(goalId) {
  try {
    const result = await apiFetch(`/api/goals/${goalId}/execute`, {
      method: 'POST',
      body: JSON.stringify({}),
    });
    const overlay = document.getElementById('goalEditorOverlay');
    if (overlay) overlay.remove();
    showToast(t('goal_dispatch_done') + ' (' + t('goal_pending_tasks').replace('{n}', result.pending_tasks.length) + ')');
    if (typeof fetchJobs === 'function') fetchJobs();
  } catch (e) {
    showToast(t('goal_exec_fail') + ': ' + e.message, 'error');
  }
}

/* ── 다음 태스크 자동 디스패치 (Goal 기반 실행) ── */

async function _dispatchNext(projectPath) {
  try {
    const result = await apiFetch('/api/goals/dispatch-next', {
      method: 'POST',
      body: JSON.stringify({ project: projectPath }),
    });
    if (result.dispatched) {
      showToast(`[${_projectShort(projectPath)}] "${result.task}" → ${t('goal_ai_run')}`);
      if (typeof fetchJobs === 'function') fetchJobs();
      loadGoals();
    } else {
      showToast(result.reason || t('goal_no_pending'));
    }
  } catch (e) {
    showToast(t('goal_dispatch_fail') + ': ' + e.message, 'error');
  }
}

/* ── 빠른 추가 (Enter: 생성만, Shift+Enter: 생성+즉시실행) ── */

(function() {
  const input = document.getElementById('goalQuickInput');
  if (!input) return;
  input.addEventListener('keydown', async function(e) {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const title = input.value.trim();
    if (!title) return;
    const project = _goalProject();
    if (!project) { showToast(t('goal_select_project'), 'error'); return; }
    const executeNow = e.shiftKey;

    input.disabled = true;
    try {
      const goal = await apiFetch('/api/goals', {
        method: 'POST',
        body: JSON.stringify({
          title,
          project,
          body: `## ${title}\n\n- [ ] ${title}`,
        }),
      });
      input.value = '';
      showToast(executeNow ? t('goal_created_run') : t('goal_created_done'));
      loadGoals();
      if (executeNow && goal && goal.id) {
        _executeGoal(goal.id);
      }
    } catch (err) {
      showToast(t('goal_create_fail') + ': ' + err.message, 'error');
    } finally {
      input.disabled = false;
      input.focus();
    }
  });
})();

/* ── 이벤트 위임 (XSS-safe: inline onclick 대신 data 속성 사용) ── */
(function() {
  const list = document.getElementById('goalsList');
  if (!list) return;
  list.addEventListener('click', function(e) {
    const dispBtn = e.target.closest('[data-dispatch-project]');
    if (dispBtn) { e.stopPropagation(); _dispatchNext(dispBtn.dataset.dispatchProject); return; }
    const execBtn = e.target.closest('[data-exec-goal]');
    if (execBtn) { e.stopPropagation(); _executeGoal(execBtn.dataset.execGoal); return; }
    const card = e.target.closest('[data-goal-id]');
    if (card) { openGoalDetail(card.dataset.goalId); }
  });
})();

/* ── 자동 갱신 ── */
setInterval(() => { if (!document.hidden) loadGoals(); }, 5000);

/* ── 초기화 ── */
loadGoals();
