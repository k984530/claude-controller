/* ═══════════════════════════════════════════════
   Directory — 최근 디렉토리, 인라인 디렉토리 브라우저
   ═══════════════════════════════════════════════ */

const MAX_RECENT_DIRS = 8;
let _recentDirsCache = [];
let dirBrowserCurrentPath = '';
let dirBrowserOpen = false;

// ── Recent Directories ──

function getRecentDirs() {
  return _recentDirsCache;
}

async function loadRecentDirs() {
  try {
    const res = await apiFetch('/api/recent-dirs');
    _recentDirsCache = Array.isArray(res) ? res : [];
  } catch { _recentDirsCache = []; }
  renderRecentDirs();
}

function _saveRecentDirs() {
  apiFetch('/api/recent-dirs', {
    method: 'POST',
    body: JSON.stringify({ dirs: _recentDirsCache })
  }).catch(() => {});
}

function addRecentDir(path) {
  if (!path) return;
  _recentDirsCache = _recentDirsCache.filter(d => d !== path);
  _recentDirsCache.unshift(path);
  if (_recentDirsCache.length > MAX_RECENT_DIRS) _recentDirsCache = _recentDirsCache.slice(0, MAX_RECENT_DIRS);
  _saveRecentDirs();
  renderRecentDirs();
}

function removeRecentDir(path) {
  _recentDirsCache = _recentDirsCache.filter(d => d !== path);
  _saveRecentDirs();
  if (document.getElementById('cwdInput').value === path) {
    clearDirSelection();
  }
  renderRecentDirs();
}

function renderRecentDirs() {
  const container = document.getElementById('recentDirs');
  const dirs = _recentDirsCache;
  const currentCwd = document.getElementById('cwdInput').value;

  if (dirs.length === 0) {
    container.innerHTML = '';
    return;
  }

  let html = '<span class="recent-dirs-label">최근</span>';
  html += dirs.map(dir => {
    const parts = dir.replace(/\/+$/, '').split('/');
    const name = parts[parts.length - 1] || dir;
    const isActive = dir === currentCwd ? ' active' : '';
    const escapedDir = dir.replace(/'/g, "\\'");
    return `<span class="recent-chip${isActive}" onclick="selectRecentDir('${escapedDir}')" title="${dir}">
      <span class="recent-chip-name">${name}</span>
      <button class="recent-chip-remove" onclick="event.stopPropagation(); removeRecentDir('${escapedDir}')" title="제거">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </span>`;
  }).join('');

  container.innerHTML = html;
}

function selectRecentDir(path, force) {
  const current = document.getElementById('cwdInput').value;
  if (!force && current === path) {
    clearDirSelection();
    return;
  }
  document.getElementById('cwdInput').value = path;
  const text = document.getElementById('dirPickerText');
  text.textContent = path;
  document.getElementById('dirPickerDisplay').classList.add('has-value');
  document.getElementById('dirPickerClear').classList.add('visible');
  renderRecentDirs();
  if (dirBrowserOpen) {
    browseTo(path);
  } else {
    dirBrowserCurrentPath = path;
  }
}

// ── Inline Directory Browser ──

function toggleDirBrowser() {
  if (dirBrowserOpen) {
    closeDirBrowser();
  } else {
    openDirBrowser();
  }
}

function openDirBrowser() {
  const panel = document.getElementById('dirBrowserPanel');
  const chevron = document.getElementById('dirPickerChevron');
  const currentCwd = document.getElementById('cwdInput').value;
  const startPath = currentCwd || '~';

  panel.classList.add('open');
  if (chevron) chevron.style.transform = 'rotate(180deg)';
  dirBrowserOpen = true;
  browseTo(startPath);
}

function closeDirBrowser() {
  const panel = document.getElementById('dirBrowserPanel');
  const chevron = document.getElementById('dirPickerChevron');
  if (panel) panel.classList.remove('open');
  if (chevron) chevron.style.transform = '';
  dirBrowserOpen = false;
}

async function browseTo(path) {
  const list = document.getElementById('dirList');
  const breadcrumb = document.getElementById('dirBreadcrumb');
  const currentDisplay = document.getElementById('dirCurrentPath');

  list.innerHTML = '<div class="dir-modal-loading"><span class="spinner"></span> 불러오는 중...</div>';

  try {
    const data = await apiFetch(`/api/dirs?path=${encodeURIComponent(path)}`);
    dirBrowserCurrentPath = data.current;
    currentDisplay.textContent = data.current;
    currentDisplay.title = data.current;

    document.getElementById('cwdInput').value = data.current;
    document.getElementById('dirPickerText').textContent = data.current;
    document.getElementById('dirPickerDisplay').classList.add('has-value');
    document.getElementById('dirPickerClear').classList.add('visible');
    renderRecentDirs();

    renderBreadcrumb(data.current, breadcrumb);

    const dirs = data.entries.filter(e => e.type === 'dir');
    if (dirs.length === 0) {
      list.innerHTML = '<div class="dir-modal-loading" style="color:var(--text-muted);">하위 디렉토리가 없습니다</div>';
      return;
    }

    list.innerHTML = dirs.map(entry => {
      const isParent = entry.name === '..';
      const icon = isParent
        ? '<svg class="dir-item-icon is-parent" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>'
        : '<svg class="dir-item-icon is-dir" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>';
      const label = isParent ? '상위 디렉토리' : entry.name;
      return `<div class="dir-item" onclick="browseTo('${entry.path.replace(/'/g, "\\'")}')">
        ${icon}
        <span class="dir-item-name is-dir">${label}</span>
      </div>`;
    }).join('');

  } catch (err) {
    list.innerHTML = `<div class="dir-modal-loading" style="color:var(--red);">불러오기 실패: ${err.message}</div>`;
  }
}

function renderBreadcrumb(fullPath, container) {
  const parts = fullPath.split('/').filter(Boolean);
  let html = `<span class="breadcrumb-seg" onclick="browseTo('/')">/</span>`;
  let accumulated = '';
  for (const part of parts) {
    accumulated += '/' + part;
    const p = accumulated;
    html += `<span class="breadcrumb-sep">/</span><span class="breadcrumb-seg" onclick="browseTo('${p.replace(/'/g, "\\'")}')">${part}</span>`;
  }
  container.innerHTML = html;
}

function selectCurrentDir() {
  if (!dirBrowserCurrentPath) return;
  document.getElementById('cwdInput').value = dirBrowserCurrentPath;

  const text = document.getElementById('dirPickerText');
  text.textContent = dirBrowserCurrentPath;
  document.getElementById('dirPickerDisplay').classList.add('has-value');
  document.getElementById('dirPickerClear').classList.add('visible');

  addRecentDir(dirBrowserCurrentPath);
  closeDirBrowser();
  renderRecentDirs();
}

function clearDirSelection() {
  document.getElementById('cwdInput').value = '';
  const text = document.getElementById('dirPickerText');
  text.textContent = t('select_directory');
  document.getElementById('dirPickerDisplay').classList.remove('has-value');
  document.getElementById('dirPickerClear').classList.remove('visible');
  renderRecentDirs();
}

// ── 디렉토리 생성 ──

function showCreateDirInput() {
  const row = document.getElementById('dirCreateRow');
  const input = document.getElementById('dirCreateInput');
  row.style.display = 'flex';
  input.value = '';
  input.placeholder = t('new_folder_name');
  input.focus();
}

function hideCreateDirInput() {
  document.getElementById('dirCreateRow').style.display = 'none';
}

async function createDir() {
  const input = document.getElementById('dirCreateInput');
  const name = input.value.trim();
  if (!name) return;
  if (!dirBrowserCurrentPath) return;

  try {
    await apiFetch('/api/mkdir', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ parent: dirBrowserCurrentPath, name }),
    });
    hideCreateDirInput();
    browseTo(dirBrowserCurrentPath);
  } catch (err) {
    input.setCustomValidity(err.message);
    input.reportValidity();
    setTimeout(() => input.setCustomValidity(''), 2000);
  }
}

// ESC 키로 패널 닫기
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    hideCreateDirInput();
    closeDirBrowser();
  }
});
