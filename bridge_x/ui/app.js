'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const catalog = window.BridgeTranslations;
  const languagePreference = 'bridge-x-language';
  let language = /^ru\b/i.test(navigator.language || '') ? 'ru' : 'en';
  try { const saved = localStorage.getItem(languagePreference); if (saved === 'en' || saved === 'ru') language = saved; } catch { /* Browser storage can be disabled. */ }
  let key = '', selected = null, snapshot = null, config = null, next = null, timer = null;
  let refreshEpoch = null, sessionEpoch = 0, staleError = null, operations = [];
  const feedback = new Map();
  const uncertain = new Set(['DISPATCHED', 'EXECUTION_UNKNOWN', 'ACKNOWLEDGED', 'CANCELLED', 'TIMED_OUT']);
  const node = (tag, text, cls) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (cls) element.className = cls;
    return element;
  };
  function t(name, values = {}) {
    const text = catalog[language][name] || catalog.en[name] || name;
    return text.replace(/\{([a-z]+)\}/g, (match, field) => String(values[field] ?? match));
  }
  const stateLabel = state => t('state_' + state);
  function errorText(error) {
    const code = typeof error?.message === 'string' && /^[A-Z0-9_]{1,80}$/.test(error.message) ? error.message : 'NETWORK_UNAVAILABLE';
    return (catalog[language]['err_' + code] ? t('err_' + code) : t('requestFailed')) + ' (' + code + ')';
  }
  function show(id, name, values = {}) {
    if (name) feedback.set(id, {name, values}); else feedback.delete(id);
    $(id).textContent = name ? t(name, values) : '';
  }
  function showError(id, error) {
    if (error?.message === 'SESSION_CHANGED') return;
    feedback.set(id, {error}); $(id).textContent = errorText(error);
  }
  function renderFeedback() {
    for (const [id, value] of feedback) {
      const values = {...value.values, ...(value.error ? {error: errorText(value.error)} : {})};
      $(id).textContent = value.name ? t(value.name, values) : errorText(value.error);
    }
  }
  function renderDetail() {
    $('facts').replaceChildren();
    if (!selected) {
      $('detail-caption').textContent = t('chooseAction'); $('detail-name').textContent = '';
      $('detail-id').hidden = true; $('detail-id').textContent = ''; $('resolution').hidden = true;
      return;
    }
    $('detail-caption').textContent = selected.updated_at; $('detail-name').textContent = selected.name;
    $('detail-id').textContent = selected.id; $('detail-id').hidden = false;
    const outcome = selected.result_kind ? t('outcome_' + selected.result_kind) : t('noReceipt');
    for (const [label, value] of [
      [t('result'), stateLabel(selected.status)], [t('category'), outcome],
      [t('executor'), t('client')], [t('taskVerification'), t('notEstablished')]
    ]) {
      const row = node('div'); row.append(node('dt', label), node('dd', value)); $('facts').append(row);
    }
    $('resolution').hidden = !uncertain.has(selected.status);
  }
  function renderOperations() {
    $('operations').replaceChildren();
    for (const operation of operations) {
      const row = node('button', undefined, 'wb-event'); row.type = 'button'; row.dataset.id = operation.id;
      row.setAttribute('aria-pressed', String(selected?.id === operation.id));
      row.classList.toggle('wb-event-selected', selected?.id === operation.id);
      const mark = uncertain.has(operation.status) ? '—' : operation.status === 'FAILED' ? '×' : ['EXECUTED', 'VERIFIED'].includes(operation.status) ? '✓' : '·';
      row.append(node('time', operation.created_at?.split(' ')[1] || ''), node('span', mark),
        node('span', operation.name, 'wb-tool'), node('span', operation.session || t('withoutSession'), 'wb-path'),
        node('span', stateLabel(operation.status), 'wb-result'));
      row.addEventListener('click', () => select(operation.id)); $('operations').append(row);
    }
    $('empty').hidden = operations.length > 0;
  }
  function renderMeta() {
    if (!snapshot) { $('connection-state').textContent = t('checking'); return; }
    $('version').textContent = 'Bridge X ' + snapshot.version + ' · ' + snapshot.provider;
    $('attention').textContent = snapshot.unresolved ? t('needsCheck', {count: snapshot.unresolved}) : '';
    $('address').textContent = location.host;
    $('storage-state').textContent = t('storage', {mode: snapshot.journal_mode});
    const connection = snapshot.connection, cooldown = snapshot.rate_control.cooldown_remaining_seconds || 0;
    $('connection-state').textContent = staleError ? t('stale', {error: errorText(staleError)})
      : snapshot.provider === 'fake' ? t('offline') : cooldown ? t('cooldown', {seconds: cooldown})
      : connection.verified ? t('recentSuccess') : connection.last_failure_code ? 'Molab · ' + connection.last_failure_code : t('unverifiedGeneration');
    $('events').replaceChildren();
    for (const event of snapshot.events) {
      const row = node('div');
      row.append(node('time', event.at?.split(' ')[1] || ''), node('span', t('event_' + event.event)),
        node('code', event.error_code || event.outcome || event.agent_state || ''));
      $('events').append(row);
    }
  }
  function renderConfig() {
    if (!config) return;
    $('base-url').textContent = config.base_url;
    $('config-present').textContent = t(config.config_present ? 'configPresent' : 'configMissing');
  }
  function applyLanguage() {
    document.documentElement.lang = language; $('language').value = language;
    document.querySelectorAll('[data-i18n]').forEach(element => { element.textContent = t(element.dataset.i18n); });
    document.querySelectorAll('[data-i18n-aria]').forEach(element => { element.setAttribute('aria-label', t(element.dataset.i18nAria)); });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(element => { element.setAttribute('placeholder', t(element.dataset.i18nPlaceholder)); });
    renderOperations(); renderDetail(); renderMeta(); renderConfig(); renderFeedback();
  }
  $('language').addEventListener('change', event => {
    if (!['en', 'ru'].includes(event.target.value)) return;
    language = event.target.value;
    try { localStorage.setItem(languagePreference, language); } catch { /* Preference storage is optional. */ }
    applyLanguage();
  });
  function logout() {
    sessionEpoch++; key = ''; selected = null; snapshot = null; config = null; operations = []; staleError = null;
    clearInterval(timer); timer = null; next = null; feedback.clear();
    $('app').hidden = true; $('login').hidden = false; $('key').value = ''; $('key-file').value = '';
    $('config-form').reset(); $('recovery').reset(); $('detail').hidden = false; $('recovery').hidden = true;
    $('events').replaceChildren(); $('base-url').textContent = '';
    for (const id of ['message', 'config-result', 'recovery-error', 'login-error']) $(id).textContent = '';
    renderOperations(); renderDetail(); renderMeta();
  }
  async function api(path, data) {
    const epoch = sessionEpoch;
    let response;
    try {
      response = await fetch(path, {method: data === undefined ? 'GET' : 'POST',
        headers: {Authorization: 'Bearer ' + key, ...(data === undefined ? {} : {'Content-Type': 'application/json'})},
        body: data === undefined ? undefined : JSON.stringify(data), cache: 'no-store', credentials: 'omit'});
    } catch { throw new Error('NETWORK_UNAVAILABLE'); }
    if (epoch !== sessionEpoch) throw new Error('SESSION_CHANGED');
    let value; try { value = await response.json(); } catch { throw new Error('SERVER_RESPONSE_INVALID'); }
    if (!response.ok) { if (response.status === 401) logout(); throw new Error(value.error?.code || 'REQUEST_FAILED'); }
    return value;
  }
  async function refresh(before) {
    if (!key || refreshEpoch === sessionEpoch) return;
    const epoch = sessionEpoch; refreshEpoch = epoch;
    try {
      const data = await api('/ui/api/snapshot' + (before ? '?before=' + encodeURIComponent(before) : ''));
      snapshot = data; staleError = null; next = data.next_cursor;
      operations = before ? [...operations, ...data.operations] : data.operations;
      $('more').hidden = next === null; renderOperations(); renderMeta();
      if (selected) {
        const current = data.operations.find(operation => operation.id === selected.id);
        if (current && current.status !== selected.status) await select(selected.id);
      }
    } finally { if (refreshEpoch === epoch) refreshEpoch = null; }
  }
  async function loadConfig() {
    config = await api('/ui/api/config'); renderConfig(); $('config-form').querySelector('button').disabled = !config.editable;
  }
  async function login(value) {
    if (!value.trim()) return;
    logout(); key = value.trim();
    try {
      await refresh(); await loadConfig(); $('key').value = ''; $('login').hidden = true; $('app').hidden = false;
      timer = setInterval(() => { if (!document.hidden) refresh().catch(error => {
        if (error.message !== 'SESSION_CHANGED') { staleError = error; renderMeta(); }
      }); }, 3000);
    } catch (error) { if (error.message !== 'SESSION_CHANGED') { logout(); feedback.set('login-error', {name: 'loginFailed', error}); renderFeedback(); } }
  }
  async function select(id) {
    try {
      selected = await api('/v1/operations/' + encodeURIComponent(id)); $('detail').hidden = false; $('recovery').hidden = true;
      renderDetail(); renderOperations();
    } catch (error) { showError('message', error); }
  }
  $('login-form').addEventListener('submit', event => { event.preventDefault(); login($('key').value); });
  $('key-file').addEventListener('change', async event => {
    const file = event.target.files[0];
    if (file && file.size <= 1024) await login(await file.text()); else show('login-error', 'invalidKeyFile');
    event.target.value = '';
  });
  $('logout').addEventListener('click', logout);
  document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-tab]').forEach(other => {
      other.classList.toggle('wb-selected', other === button); other.setAttribute('aria-pressed', String(other === button));
    });
    document.querySelectorAll('[data-page]').forEach(page => { page.hidden = page.dataset.page !== button.dataset.tab; });
  }));
  $('refresh').addEventListener('click', () => refresh().catch(error => showError('message', error)));
  $('more').addEventListener('click', () => {
    if (operations.length >= 200) { show('message', 'historyLimit'); return; }
    refresh(next).catch(error => showError('message', error));
  });
  $('open-recovery').addEventListener('click', () => {
    $('detail').hidden = true; $('recovery').hidden = false; $('recovery').reset(); show('recovery-error', '');
  });
  $('back').addEventListener('click', () => { $('detail').hidden = false; $('recovery').hidden = true; });
  $('recovery').addEventListener('submit', async event => {
    event.preventDefault(); if (!selected) return; const button = event.submitter; button.disabled = true;
    try {
      await api('/ui/api/verify/' + encodeURIComponent(selected.id), {conversation_id: selected.conversation_id,
        expected_sha256: $('expected').value.trim(), observed_sha256: $('observed').value.trim(), execution_stopped: $('stopped').checked});
      await select(selected.id); await refresh(); show('message', 'checkSaved');
    } catch (error) { showError('recovery-error', error); } finally { button.disabled = false; }
  });
  $('config-form').addEventListener('submit', async event => {
    event.preventDefault(); const button = event.submitter; button.disabled = true;
    try {
      const result = await api('/ui/api/config', {chat_url: $('runtime-url').value.trim(), marimo_session_id: $('session-id').value.trim(), marimo_server_token: $('server-token').value});
      $('config-form').reset(); show('config-result', result.provider_restart_required ? 'savedRestart' : 'saved'); await loadConfig();
    } catch (error) { showError('config-result', error); } finally { button.disabled = config?.editable === false; }
  });
  async function checkRuntime(configure) {
    $('check-runtime').disabled = true; $('set-manual').disabled = true; show('config-result', 'checkingRuntime');
    try {
      const result = await api('/ui/api/check-runtime', {configure}); show('config-result', 'runtimeReady', {mode: result.mode});
      $('set-manual').hidden = result.mode !== 'code_mode';
    } catch (error) { showError('config-result', error); } finally { $('check-runtime').disabled = false; $('set-manual').disabled = false; }
  }
  $('check-runtime').addEventListener('click', () => checkRuntime(false));
  $('set-manual').addEventListener('click', () => { if (confirm(t('confirmManual'))) checkRuntime(true); });
  async function copyValue(value, message) {
    try { await navigator.clipboard.writeText(value); show('message', message); }
    catch { showError('message', new Error('CLIPBOARD_UNAVAILABLE')); }
  }
  $('copy-base').addEventListener('click', () => copyValue(config.base_url, 'baseCopied'));
  $('copy-model').addEventListener('click', () => copyValue('molab-glm', 'modelCopied'));
  $('copy-key').addEventListener('click', () => copyValue(key, 'keyCopied'));
  $('report').addEventListener('click', async () => {
    try {
      const result = await api('/diagnostics/report'); const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], {type: 'application/json'}));
      const link = node('a'); link.href = url; link.download = 'bridge-x-report.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { showError('message', error); }
  });
  window.addEventListener('pagehide', () => { key = ''; clearInterval(timer); });
  applyLanguage();
})();
