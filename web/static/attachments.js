/* ═══════════════════════════════════════════════
   Attachments — 파일 업로드, 첨부 관리
   ═══════════════════════════════════════════════ */

const attachments = [];

function updateAttachBadge() {
  document.getElementById('imgCountBadge').textContent = '';
}

function insertAtCursor(textarea, text) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const before = textarea.value.substring(0, start);
  const after = textarea.value.substring(end);
  const space = (before.length > 0 && !before.endsWith(' ') && !before.endsWith('\n')) ? ' ' : '';
  textarea.value = before + space + text + ' ' + after;
  const newPos = start + space.length + text.length + 1;
  textarea.selectionStart = textarea.selectionEnd = newPos;
  textarea.focus();
  updatePromptMirror();
}

function updatePromptMirror() {
  const ta = document.getElementById('promptInput');
  const mirror = document.getElementById('promptMirror');
  if (!ta || !mirror) return;
  const val = ta.value;
  if (!val) {
    mirror.innerHTML = '';
    syncAttachmentsFromText('');
    return;
  }
  const escaped = escapeHtml(val);
  mirror.innerHTML = escaped.replace(/@(\/[^\s,]+|image\d+)/g, (match) => {
    return `<span class="prompt-at-ref">${escapeHtml(match)}</span>`;
  }) + '\n';
  mirror.scrollTop = ta.scrollTop;
  syncAttachmentsFromText(val);
}

function syncAttachmentsFromText(text) {
  const container = document.getElementById('attachmentPreviews');
  if (!container) return;
  let changed = false;
  attachments.forEach((att, idx) => {
    if (!att) return;
    const ref = `@image${idx}`;
    if (!text.includes(ref)) {
      attachments[idx] = null;
      const thumb = container.querySelector(`[data-idx="${idx}"]`);
      if (thumb) thumb.remove();
      changed = true;
    }
  });
  if (changed) updateAttachBadge();
}

async function uploadFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const data = await apiFetch('/api/upload', {
          method: 'POST',
          body: JSON.stringify({ filename: file.name, data: reader.result }),
        });
        resolve(data);
      } catch (err) {
        reject(err);
      }
    };
    reader.onerror = () => reject(new Error(t('msg_file_read_failed')));
    reader.readAsDataURL(file);
  });
}

function removeAttachment(idx) {
  attachments[idx] = null;
  const container = document.getElementById('attachmentPreviews');
  const thumb = container.querySelector(`[data-idx="${idx}"]`);
  if (thumb) thumb.remove();
  const ta = document.getElementById('promptInput');
  ta.value = ta.value.replace(new RegExp(`\\s*@image${idx}\\b`, 'g'), '');
  updateAttachBadge();
  updatePromptMirror();
}

function clearAttachments() {
  attachments.length = 0;
  document.getElementById('attachmentPreviews').innerHTML = '';
  updateAttachBadge();
  updatePromptMirror();
}

function openFilePicker() {
  document.getElementById('filePickerInput').click();
}

async function handleFiles(files) {
  const container = document.getElementById('attachmentPreviews');
  for (const file of files) {
    const isImage = file.type.startsWith('image/');
    const localUrl = isImage ? URL.createObjectURL(file) : null;

    const tempIdx = attachments.length;
    attachments.push({ localUrl, serverPath: null, filename: file.name, isImage, size: file.size });

    const thumb = document.createElement('div');
    thumb.dataset.idx = tempIdx;

    if (isImage) {
      thumb.className = 'img-thumb uploading';
      thumb.innerHTML = `<img src="${localUrl}" alt="${escapeHtml(file.name)}">
        <button class="img-remove" onclick="removeAttachment(${tempIdx})" title="${t('remove')}">&times;</button>`;
    } else {
      thumb.className = 'file-thumb uploading';
      thumb.innerHTML = `
        <div class="file-icon">${escapeHtml(getFileExt(file.name))}</div>
        <div class="file-info">
          <div class="file-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</div>
          <div class="file-size">${formatFileSize(file.size)}</div>
        </div>
        <button class="file-remove" onclick="removeAttachment(${tempIdx})" title="${t('remove')}">&times;</button>`;
    }
    container.appendChild(thumb);
    updateAttachBadge();

    try {
      const data = await uploadFile(file);
      if (!attachments[tempIdx]) continue;
      attachments[tempIdx].serverPath = data.path;
      attachments[tempIdx].filename = data.filename || file.name;
      thumb.classList.remove('uploading');
      const ta = document.getElementById('promptInput');
      insertAtCursor(ta, `@image${tempIdx}`);
    } catch (err) {
      showToast(`${t('msg_upload_failed')}: ${escapeHtml(file.name)} — ${err.message}`, 'error');
      if (attachments[tempIdx]) attachments[tempIdx] = null;
      if (thumb.parentNode) thumb.remove();
      updateAttachBadge();
    }
  }
}
