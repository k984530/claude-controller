/* ═══════════════════════════════════════════════
   Settings — 설정 패널
   ═══════════════════════════════════════════════ */

let _settingsData = {};

function openSettings() {
  loadSettings().then(() => {
    document.getElementById('settingsOverlay').classList.add('open');
  });
}

function closeSettings() {
  document.getElementById('settingsOverlay').classList.remove('open');
}

async function loadSettings() {
  try {
    _settingsData = await apiFetch('/api/config');
  } catch {
    _settingsData = {};
  }
  _populateSettingsUI();
}

function _populateSettingsUI() {
  const d = _settingsData;
  const sel = document.getElementById('cfgLocale');
  if (sel) sel.value = d.locale || _currentLocale;
}

async function saveSettings() {
  const locale = document.getElementById('cfgLocale').value;
  const payload = { locale };
  try {
    await apiFetch('/api/config', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    setLocale(locale);
    showToast(t('msg_settings_saved'));
  } catch (e) {
    showToast(t('msg_settings_save_failed') + ': ' + e.message, 'error');
  }
}
