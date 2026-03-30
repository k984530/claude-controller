/* ═══════════════════════════════════════════════
   Skills — 고정 카테고리 + 스킬 CRUD
   카테고리: 기획, 개발, 디자인, 검증, 기타 (고정)
   각 스킬 카드에 수정/실행 버튼 제공
   ═══════════════════════════════════════════════ */

let _skillCategories = [];

const _FIXED_CATEGORIES = [
  { id: 'plan',   name: '기획',  color: 'accent' },
  { id: 'dev',    name: '개발',  color: 'green'  },
  { id: 'design', name: '디자인', color: 'yellow' },
  { id: 'verify', name: '검증',  color: 'red'    },
  { id: 'etc',    name: '기타',  color: 'blue'   },
];

/* ── 데이터 로드/저장 ── */

async function loadSkills() {
  let saved = [];
  try {
    saved = await apiFetch('/api/skills');
    if (!Array.isArray(saved)) saved = [];
  } catch {
    saved = [];
  }
  _skillCategories = _mergeWithDefaults(saved);
  _renderSkillsSection();
}

function _mergeWithDefaults(saved) {
  const savedMap = {};
  for (const cat of saved) {
    if (cat && cat.id) savedMap[cat.id] = cat.skills || [];
  }
  return _FIXED_CATEGORIES.map(def => ({
    id: def.id,
    name: def.name,
    color: def.color,
    skills: savedMap[def.id] || [],
  }));
}

async function _saveSkills() {
  try {
    await apiFetch('/api/skills', {
      method: 'POST',
      body: JSON.stringify(_skillCategories),
    });
  } catch (e) {
    showToast('스킬 저장 실패: ' + e.message, 'error');
  }
}

/* ── 렌더링 ── */

function _renderSkillsSection() {
  const grid = document.getElementById('skillsGrid');
  if (!grid) return;

  grid.innerHTML = _skillCategories.map((cat, ci) => `
    <div class="skills-column" data-cat-idx="${ci}">
      <div class="skills-column-header">
        <span class="skills-col-name">${escapeHtml(cat.name)}</span>
      </div>
      <div class="skills-cards">
        ${cat.skills.length === 0 ? `
          <div class="skill-card-empty">스킬 없음</div>
        ` : ''}
        ${cat.skills.map((s, si) => _renderSkillCard(s, ci, si)).join('')}
        <button class="skill-add-btn" onclick="addSkill(${ci})">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          스킬 추가
        </button>
      </div>
    </div>
  `).join('');
}

function _renderSkillCard(skill, catIdx, skillIdx) {
  return `
    <div class="skill-card">
      <div class="skill-card-name">${escapeHtml(skill.name)}</div>
      <div class="skill-card-desc">${escapeHtml(skill.desc || '')}</div>
      <div class="skill-card-btns">
        <button class="skill-btn skill-btn-edit" onclick="editSkill(${catIdx},${skillIdx})" title="수정">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          수정
        </button>
        <button class="skill-btn skill-btn-run" onclick="runSkill(${catIdx},${skillIdx})" title="실행">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          실행
        </button>
        <button class="skill-btn skill-btn-del" onclick="deleteSkill(${catIdx},${skillIdx})" title="삭제">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
    </div>
  `;
}

/* ── 실행 모달 (프로젝트 + 시간 입력) ── */

function runSkill(catIdx, skillIdx) {
  const cat = _skillCategories[catIdx];
  if (!cat) return;
  const skill = cat.skills[skillIdx];
  if (!skill) return;
  _showSkillRunModal(skill);
}

async function _showSkillRunModal(skill) {
  const prev = document.getElementById('skillRunOverlay');
  if (prev) prev.remove();

  let recentDirs = [];
  try { recentDirs = await apiFetch('/api/recent-dirs'); } catch {}
  if (!Array.isArray(recentDirs)) recentDirs = [];

  let projects = [];
  try { projects = await apiFetch('/api/projects'); } catch {}
  if (!Array.isArray(projects)) projects = [];

  const allPaths = [];
  const seen = new Set();
  for (const p of projects) {
    const pp = p.path || p.project_path || '';
    if (pp && !seen.has(pp)) { seen.add(pp); allPaths.push({ path: pp, label: p.name || pp.split('/').pop(), type: 'project' }); }
  }
  for (const d of recentDirs) {
    const dp = typeof d === 'string' ? d : (d.path || '');
    if (dp && !seen.has(dp)) { seen.add(dp); allPaths.push({ path: dp, label: dp.split('/').pop(), type: 'recent' }); }
  }

  const optionsHtml = allPaths.map(p =>
    `<option value="${escapeHtml(p.path)}">${escapeHtml(p.label)} (${p.type === 'project' ? '프로젝트' : '최근'})</option>`
  ).join('');

  const overlay = document.createElement('div');
  overlay.id = 'skillRunOverlay';
  overlay.className = 'editor-overlay';
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  overlay.innerHTML = `
    <div class="editor-modal skill-run-modal">
      <div class="skill-run-title">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        <span>${escapeHtml(skill.name)}</span>
        <span class="skill-run-subtitle">실행</span>
      </div>
      <div class="skill-run-prompt">${escapeHtml(skill.prompt || '(프롬프트 없음)')}</div>
      <label class="skill-run-label">
        프로젝트
        <select id="skillRunProject" class="skill-run-input">
          <option value="">선택하세요</option>
          ${optionsHtml}
        </select>
      </label>
      <label class="skill-run-label">
        실행 주기 (선택)
        <input type="text" id="skillRunInterval" class="skill-run-input" placeholder="예: 30m, 1h, 매일 09:00" />
      </label>
      <div class="skill-editor-actions">
        <button class="btn-small btn-muted" onclick="this.closest('.editor-overlay').remove()">취소</button>
        <button class="btn-small" onclick="_execSkillRun('${escapeHtml(escapeJsStr(skill.id))}')">실행</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
}

async function _execSkillRun(skillId) {
  const projectPath = document.getElementById('skillRunProject').value;
  const interval = document.getElementById('skillRunInterval').value.trim();

  if (!projectPath) {
    showToast('프로젝트를 선택하세요', 'error');
    return;
  }

  const skill = _findSkill(skillId);
  if (!skill || !skill.prompt) {
    showToast('스킬 프롬프트가 없습니다', 'error');
    return;
  }

  const overlay = document.getElementById('skillRunOverlay');
  if (overlay) overlay.remove();

  try {
    const pipeBody = {
      project_path: projectPath,
      command: skill.prompt,
      name: skill.name,
      skill_ids: [skillId],
    };
    if (interval) pipeBody.interval = interval;

    const pipe = await apiFetch('/api/pipelines', {
      method: 'POST',
      body: JSON.stringify(pipeBody),
    });
    showToast(`실행 등록: ${pipe.name || pipe.id}`);
    if (typeof fetchPipelines === 'function') fetchPipelines();
    if (typeof runPipeline === 'function') runPipeline(pipe.id);
  } catch (err) {
    showToast(`실행 실패: ${err.message}`, 'error');
  }
}

function _findSkill(skillId) {
  for (const cat of _skillCategories) {
    const s = cat.skills.find(x => x.id === skillId);
    if (s) return s;
  }
  return null;
}

/* ── CRUD: 스킬 ── */

function addSkill(catIdx) {
  _openSkillEditor(catIdx, -1);
}

function editSkill(catIdx, skillIdx) {
  _openSkillEditor(catIdx, skillIdx);
}

function deleteSkill(catIdx, skillIdx) {
  const cat = _skillCategories[catIdx];
  if (!cat) return;
  const skill = cat.skills[skillIdx];
  if (!skill) return;
  if (!confirm(`"${skill.name}" 스킬을 삭제하시겠습니까?`)) return;

  cat.skills.splice(skillIdx, 1);
  _saveSkills();
  _renderSkillsSection();
}

/* ── 스킬 편집 모달 (프롬프트 전문 표시) ── */

function _openSkillEditor(catIdx, skillIdx) {
  const cat = _skillCategories[catIdx];
  const isNew = skillIdx < 0;
  const skill = isNew ? { id: '', name: '', desc: '', prompt: '' } : { ...cat.skills[skillIdx] };

  const prev = document.getElementById('skillEditorOverlay');
  if (prev) prev.remove();

  const overlay = document.createElement('div');
  overlay.id = 'skillEditorOverlay';
  overlay.className = 'editor-overlay';
  overlay.innerHTML = `
    <div class="editor-modal skill-editor-modal">
      <div class="skill-editor-title">${escapeHtml(cat.name)} — ${isNew ? '스킬 추가' : '스킬 수정'}</div>
      <label>이름
        <input type="text" id="skillEdName" value="${escapeHtml(skill.name)}" placeholder="스킬 이름" />
      </label>
      <label>설명
        <input type="text" id="skillEdDesc" value="${escapeHtml(skill.desc)}" placeholder="짧은 설명 (선택)" />
      </label>
      <label>프롬프트
        <textarea id="skillEdPrompt" rows="12" placeholder="이 스킬의 전체 프롬프트">${escapeHtml(skill.prompt)}</textarea>
      </label>
      <div class="skill-editor-actions">
        <button class="btn-small btn-muted" onclick="document.getElementById('skillEditorOverlay').remove()">취소</button>
        <button class="btn-small" onclick="_saveSkillEditor(${catIdx},${skillIdx})">저장</button>
      </div>
    </div>
  `;
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) overlay.remove();
  });
  document.body.appendChild(overlay);
  document.getElementById('skillEdName').focus();
}

function _saveSkillEditor(catIdx, skillIdx) {
  const name = document.getElementById('skillEdName').value.trim();
  const desc = document.getElementById('skillEdDesc').value.trim();
  const promptVal = document.getElementById('skillEdPrompt').value.trim();

  if (!name) {
    showToast('스킬 이름을 입력하세요', 'error');
    return;
  }

  const cat = _skillCategories[catIdx];
  const isNew = skillIdx < 0;

  if (isNew) {
    cat.skills.push({
      id: cat.id + '-' + Date.now(),
      name,
      desc,
      prompt: promptVal,
    });
  } else {
    cat.skills[skillIdx].name = name;
    cat.skills[skillIdx].desc = desc;
    cat.skills[skillIdx].prompt = promptVal;
  }

  document.getElementById('skillEditorOverlay').remove();
  _saveSkills();
  _renderSkillsSection();
}

/* ── 초기화 ── */
loadSkills();
