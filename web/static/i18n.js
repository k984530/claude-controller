/* ═══════════════════════════════════════════════
   i18n — 국제화 로직
   번역 데이터: i18n-data.js (I18N 객체)
   ═══════════════════════════════════════════════ */

let _currentLocale = localStorage.getItem('ctrl_locale') || 'ko';

function t(key) {
  const dict = I18N[_currentLocale] || I18N['ko'];
  return dict[key] || I18N['ko'][key] || key;
}

function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    const text = t(key);
    if (text) el.textContent = text;
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    const text = t(key);
    if (text) el.placeholder = text;
  });
  document.documentElement.lang = _currentLocale.split('-')[0];
  document.documentElement.setAttribute('data-locale', _currentLocale);
}

function setLocale(locale) {
  if (!I18N[locale]) return;
  _currentLocale = locale;
  localStorage.setItem('ctrl_locale', locale);
  applyI18n();
}

function onLocaleChange() {
  const sel = document.getElementById('cfgLocale');
  if (sel) setLocale(sel.value);
}
