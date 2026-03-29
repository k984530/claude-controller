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

  const whUrl = document.getElementById('cfgWebhookUrl');
  if (whUrl) whUrl.value = d.webhook_url || '';
  const whSecret = document.getElementById('cfgWebhookSecret');
  if (whSecret) whSecret.value = d.webhook_secret || '';
  const whEvents = document.getElementById('cfgWebhookEvents');
  if (whEvents) whEvents.value = d.webhook_events || 'done,failed';
}

async function saveSettings() {
  const locale = document.getElementById('cfgLocale').value;
  const webhookUrl = (document.getElementById('cfgWebhookUrl')?.value || '').trim();
  const webhookSecret = (document.getElementById('cfgWebhookSecret')?.value || '').trim();
  const webhookEvents = document.getElementById('cfgWebhookEvents')?.value || 'done,failed';
  const payload = {
    locale,
    webhook_url: webhookUrl,
    webhook_secret: webhookSecret,
    webhook_events: webhookEvents,
  };
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

async function testWebhook() {
  const btn = document.getElementById('btnWebhookTest');
  if (!btn) return;
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner" style="width:12px;height:12px;"></span>';
  try {
    const result = await apiFetch('/api/webhooks/test', { method: 'POST' });
    if (result.delivered) {
      showToast(`웹훅 전송 성공 (HTTP ${result.status_code})`);
    } else {
      showToast(`웹훅 전송 실패: ${result.error}`, 'error');
    }
  } catch (e) {
    showToast(`웹훅 테스트 실패: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}
