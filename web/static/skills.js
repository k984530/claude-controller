/* ═══════════════════════════════════════════════
   Skills — 고정 카테고리 + 스킬 CRUD
   카테고리: 기획, 개발, 디자인, 검증, 기타 (고정)
   사용자는 각 카테고리 내 스킬만 관리
   ═══════════════════════════════════════════════ */

let _skillCategories = [];
let _selectedSkills = new Set();
let _skillEditMode = false;

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

/* ── 편집 모드 토글 ── */

function toggleSkillEditMode() {
  _skillEditMode = !_skillEditMode;
  const btn = document.getElementById('btnSkillEdit');
  if (btn) {
    btn.style.cssText = _skillEditMode
      ? 'border-color:var(--accent);color:var(--accent);background:rgba(99,102,241,0.1);'
      : '';
  }
  _renderSkillsSection();
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
        ${cat.skills.length === 0 && !_skillEditMode ? `
          <div class="skill-card-empty">스킬 없음</div>
        ` : ''}
        ${cat.skills.map((s, si) => _renderSkillCard(s, ci, si)).join('')}
        ${_skillEditMode ? `
          <button class="skill-add-btn" onclick="addSkill(${ci})">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            스킬 추가
          </button>
        ` : ''}
      </div>
    </div>
  `).join('');

  _updateSkillsBar();
}

function _renderSkillCard(skill, catIdx, skillIdx) {
  const selected = _selectedSkills.has(skill.id);
  return `
    <div class="skill-card${selected ? ' selected' : ''}${_skillEditMode ? ' edit-mode' : ''}"
         data-skill-id="${skill.id}"
         onclick="${_skillEditMode ? '' : `toggleSkill('${skill.id}')`}">
      ${!_skillEditMode ? `
        <div class="skill-card-check">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
        </div>
      ` : `
        <div class="skill-card-edit-actions">
          <button class="skills-icon-btn" onclick="event.stopPropagation();editSkill(${catIdx},${skillIdx})" title="수정">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          </button>
          <button class="skills-icon-btn" onclick="event.stopPropagation();deleteSkill(${catIdx},${skillIdx})" title="삭제">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
          </button>
        </div>
      `}
      <div class="skill-card-name">${escapeHtml(skill.name)}</div>
      <div class="skill-card-desc">${escapeHtml(skill.desc || '')}</div>
    </div>
  `;
}

/* ── 스킬 선택 (전송 시 system_prompt 주입) ── */

function toggleSkill(skillId) {
  if (_selectedSkills.has(skillId)) {
    _selectedSkills.delete(skillId);
  } else {
    _selectedSkills.add(skillId);
  }
  _renderSkillsSection();
}

function clearSkillSelection() {
  _selectedSkills.clear();
  _renderSkillsSection();
}

function _updateSkillsBar() {
  let bar = document.getElementById('skillsActiveBar');
  if (!bar) {
    const section = document.getElementById('skillsGrid');
    if (!section) return;
    bar = document.createElement('div');
    bar.id = 'skillsActiveBar';
    bar.className = 'skills-active-bar';
    section.parentElement.insertBefore(bar, section);
  }

  if (_selectedSkills.size === 0) {
    bar.classList.remove('visible');
    return;
  }

  const tags = [];
  for (const sid of _selectedSkills) {
    const skill = _findSkill(sid);
    if (skill) tags.push(`<span class="skills-active-tag" onclick="toggleSkill('${sid}')" title="클릭하여 해제">${escapeHtml(skill.name)}</span>`);
  }

  bar.innerHTML = `
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/></svg>
    <div class="skills-active-bar-tags">${tags.join('')}</div>
    <span class="skills-clear-btn" onclick="clearSkillSelection()">전체 해제</span>
  `;
  bar.classList.add('visible');
}

function _findSkill(skillId) {
  for (const cat of _skillCategories) {
    const s = cat.skills.find(x => x.id === skillId);
    if (s) return s;
  }
  return null;
}

/** 전송 시 선택된 스킬의 프롬프트를 결합하여 반환 */
function getSkillSystemPrompt() {
  if (_selectedSkills.size === 0) return '';
  const parts = [];
  for (const sid of _selectedSkills) {
    const skill = _findSkill(sid);
    if (skill && skill.prompt) parts.push(`[${skill.name}] ${skill.prompt}`);
  }
  return parts.join('\n\n');
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

  _selectedSkills.delete(skill.id);
  cat.skills.splice(skillIdx, 1);
  _saveSkills();
  _renderSkillsSection();
}

/* ── 스킬 편집 모달 ── */

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
      <label>시스템 프롬프트
        <textarea id="skillEdPrompt" rows="5" placeholder="이 스킬 선택 시 주입될 시스템 프롬프트">${escapeHtml(skill.prompt)}</textarea>
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
