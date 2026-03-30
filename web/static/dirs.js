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

// ── 폴더 드래그 & 드롭 → CWD 설정 ──

(function() {
  const dirPicker = document.querySelector('.dir-picker');
  const promptWrapper = document.getElementById('promptWrapper');
  if (!dirPicker) return;

  // dirPicker에만 드래그 호버 표시, 드롭은 실제 폴더만 처리
  dirPicker.addEventListener('dragover', function(e) {
    if (_hasFolderInDrag(e)) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'link';
      dirPicker.classList.add('dir-drop-hover');
    }
  });

  dirPicker.addEventListener('dragleave', function(e) {
    if (e.currentTarget === dirPicker) {
      dirPicker.classList.remove('dir-drop-hover');
    }
  });

  dirPicker.addEventListener('drop', function(e) {
    dirPicker.classList.remove('dir-drop-hover');

    // 실제 폴더 드롭만 처리 — 파일은 app.js의 sendTask 핸들러로 위임
    if (!_isActualFolderDrop(e)) return;

    e.preventDefault();
    const path = _extractPathFromDrop(e);
    if (path) {
      _applyDroppedPath(path);
      return;
    }

    const folderName = _extractFolderName(e);
    if (folderName) {
      _searchAndApplyFolder(folderName);
    }
  });

  function _hasFolderInDrag(e) {
    if (!e.dataTransfer) return false;
    return e.dataTransfer.types.indexOf('Files') !== -1
      || e.dataTransfer.types.indexOf('public.file-url') !== -1;
  }

  function _isActualFolderDrop(e) {
    if (!e.dataTransfer) return false;
    // webkitGetAsEntry로 실제 디렉토리인지 확인
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      const item = e.dataTransfer.items[0];
      if (item.webkitGetAsEntry) {
        const entry = item.webkitGetAsEntry();
        return entry && entry.isDirectory;
      }
    }
    // File 객체 힌트: type 없고 size 0이면 폴더일 가능성
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      return !file.type && file.size === 0;
    }
    return false;
  }

  function _extractPathFromDrop(e) {
    if (!e.dataTransfer) return null;

    // 1) text/uri-list에서 file:// URL 추출 (macOS Finder + Safari)
    for (const type of ['text/uri-list', 'URL', 'text/plain', 'public.file-url']) {
      try {
        const data = e.dataTransfer.getData(type);
        if (data) {
          const path = _parseFileUrl(data);
          if (path) return path;
        }
      } catch { /* 무시 */ }
    }

    // 2) DataTransferItem으로 디렉토리 판별 + 이름 추출
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      const item = e.dataTransfer.items[0];
      if (item.webkitGetAsEntry) {
        const entry = item.webkitGetAsEntry();
        if (entry && entry.isDirectory) {
          // 이름만 알 수 있음 — 파일 객체에서 추가 정보 시도
          const file = e.dataTransfer.files[0];
          if (file && file.path) return file.path; // Electron 환경
          // 브라우저 환경: 이름만으로 서버에 질의
          return null; // _applyDroppedPath에서 처리 안됨, 아래 files 폴백으로
        }
      }
    }

    // 3) File 객체의 path (Electron 등)
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      if (file.path) return file.path;
    }

    return null;
  }

  function _parseFileUrl(data) {
    // 여러 줄일 수 있음 (text/uri-list 형식)
    const lines = data.split(/[\r\n]+/).filter(l => l && !l.startsWith('#'));
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith('file://')) {
        // file:///path/to/folder → /path/to/folder
        try {
          const url = new URL(trimmed);
          return decodeURIComponent(url.pathname);
        } catch {
          return decodeURIComponent(trimmed.replace(/^file:\/\//, ''));
        }
      }
      // 슬래시로 시작하는 절대 경로
      if (trimmed.startsWith('/') && !trimmed.includes('\t')) {
        return trimmed;
      }
    }
    return null;
  }

  function _extractFolderName(e) {
    if (!e.dataTransfer) return null;
    // webkitGetAsEntry로 디렉토리 이름 추출
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      const item = e.dataTransfer.items[0];
      if (item.webkitGetAsEntry) {
        const entry = item.webkitGetAsEntry();
        if (entry && entry.isDirectory) return entry.name;
      }
    }
    // File 객체에서 디렉토리 힌트 (type 비어있고 size 0이면 폴더일 가능성)
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      if (!file.type && file.size === 0 && file.name) return file.name;
    }
    return null;
  }

  async function _searchAndApplyFolder(folderName) {
    const searchPaths = [];
    // 현재 CWD와 상위 경로 우선 탐색
    const cwd = document.getElementById('cwdInput')?.value?.trim();
    if (cwd) {
      searchPaths.push(cwd);
      const parent = cwd.replace(/\/[^/]+\/?$/, '');
      if (parent && parent !== cwd) searchPaths.push(parent);
      const grandparent = parent.replace(/\/[^/]+\/?$/, '');
      if (grandparent && grandparent !== parent) searchPaths.push(grandparent);
    }
    if (dirBrowserCurrentPath) searchPaths.push(dirBrowserCurrentPath);
    // 자주 쓰는 위치
    searchPaths.push('~', '~/Desktop', '~/Documents', '~/Downloads',
      '~/Projects', '~/Development', '~/dev', '~/repos', '~/src',
      '~/code', '~/workspace', '~/workspaces');

    for (const base of searchPaths) {
      try {
        const data = await apiFetch(`/api/dirs?path=${encodeURIComponent(base)}`);
        if (!data || !data.entries) continue;
        const match = data.entries.find(e => e.type === 'dir' && e.name === folderName);
        if (match) {
          selectRecentDir(match.path, true);
          addRecentDir(match.path);
          showToast(`CWD: ${match.path}`);
          return;
        }
      } catch { /* 계속 */ }
    }
    // 서버 측 깊은 검색 (mdfind/find)
    try {
      const found = await apiFetch(`/api/find-dir?name=${encodeURIComponent(folderName)}`);
      if (found && found.path) {
        selectRecentDir(found.path, true);
        addRecentDir(found.path);
        showToast(`CWD: ${found.path}`);
        return;
      }
    } catch { /* 서버 검색도 실패 */ }

    // 최종 실패 시 디렉토리 브라우저 열기
    showToast(`"${folderName}" 자동 검색 실패 — 직접 선택해주세요.`, 'error');
    if (typeof toggleDirBrowser === 'function') toggleDirBrowser();
  }

  async function _applyDroppedPath(path) {
    // 서버에서 디렉토리인지 확인
    try {
      const data = await apiFetch(`/api/dirs?path=${encodeURIComponent(path)}`);
      if (data && data.current) {
        selectRecentDir(data.current, true);
        addRecentDir(data.current);
        showToast(`CWD: ${data.current}`);
      }
    } catch {
      // 디렉토리가 아니거나 접근 불가 — 상위 디렉토리 시도
      const parent = path.replace(/\/[^/]+\/?$/, '') || '/';
      try {
        const data = await apiFetch(`/api/dirs?path=${encodeURIComponent(parent)}`);
        if (data && data.current) {
          selectRecentDir(data.current, true);
          addRecentDir(data.current);
          showToast(`CWD: ${data.current}`);
          }
      } catch {
        showToast('경로를 인식할 수 없습니다', 'error');
      }
    }
  }

  // 외부(app.js 등)에서 프롬프트 영역 폴더 드롭을 CWD로 위임할 수 있도록 노출
  window.handleFolderDrop = function(e) {
    if (!_isActualFolderDrop(e)) return false;
    const path = _extractPathFromDrop(e);
    if (path) {
      _applyDroppedPath(path);
      return true;
    }
    const folderName = _extractFolderName(e);
    if (folderName) {
      _searchAndApplyFolder(folderName);
      return true;
    }
    return false;
  };
})();
