import {api, APIError, el, field, button, link, heading, notice, message, badge, date, details, select, query, copy} from './common.js';

export async function reports(root, ctx) {
  const template = el('input', {placeholder:'All templates', maxLength:64, pattern:'[a-z0-9][a-z0-9_-]{0,63}'});
  const state = select([['','All states'], ...['queued','running','succeeded','failed','expired'].map(x => [x,x[0].toUpperCase()+x.slice(1)])]);
  const status = notice(), body = el('tbody'), more = button('Load more', () => load(false));
  const filters = el('form', {class:'toolbar'}, field('Template ID', template), field('State', state), el('button', {type:'submit'}, 'Refresh'));
  root.replaceChildren(heading('Reports', 'Shared history of retained jobs, newest first.', link('＋ New report', '#/new-report', true)),
    filters, status, el('div', {class:'panel flush'}, el('div', {class:'table-wrap'}, el('table', {},
      el('thead', {}, el('tr', {}, ...['Report', 'Template', 'State', 'Output', 'Created'].map(x => el('th', {}, x)))), body)),
      el('div', {class:'table-footer'}, more)));
  let after = '', token = 0, applied = {};
  async function load(reset) {
    const request = ++token; more.disabled = true;
    if (reset) { applied = {template_id:template.value.trim(), state:state.value}; after = ''; body.replaceChildren(); more.hidden = true; }
    try {
      const data = await api(query('/v1/reports', {...applied, after:reset ? '' : after}), {}, ctx.controller.signal);
      if (!ctx.active || request !== token) return;
      if (reset) body.replaceChildren();
      for (const row of data.items) body.append(el('tr', {}, el('td', {}, link(row.id.slice(0,8), `#/reports/${row.id}`)),
        el('td', {}, link(row.template_id, `#/templates/${row.template_id}?version=${row.template_version}`), el('div', {class:'muted'}, `Version ${row.template_version}`)),
        el('td', {}, badge(row.state, row.terminal_state)), el('td', {}, row.output.toUpperCase(), el('div', {class:'muted'}, row.renderer)), el('td', {}, date(row.created_at))));
      after = data.next; more.hidden = !after; message(status, body.children.length ? '' : 'No retained reports match these filters.');
    } catch (error) { if (ctx.active && request === token) message(status, `History could not be refreshed. ${error.message}`, 'error'); }
    finally { if (request === token) more.disabled = false; }
  }
  filters.addEventListener('submit', event => {event.preventDefault(); load(true);});
  state.addEventListener('change', () => load(true));
  template.addEventListener('change', () => load(true));
  await load(true);
}

export async function reportDetail(root, ctx, id, params = new URLSearchParams()) {
  let accepted = params.get('accepted') === '1';
  const acceptance = notice();
  if (accepted) history.replaceState(null, '', `#/reports/${encodeURIComponent(id)}`);
  const status = notice(), info = el('div', {class:'panel'}), errorBox = notice();
  const previewArea = el('section', {class:'panel', hidden:true});
  const contentUrl = `/v1/reports/${encodeURIComponent(id)}/content`;
  let row = null, busy = false, timer = null, delay = 2000, missing = false, halted = false;
  const refresh = button('Refresh status', () => load(true));
  const download = el('a', {href:contentUrl, class:'button primary', hidden:true}, 'Download');
  const preview = button('Preview HTML', showPreview); preview.hidden = true;
  const reuse = link('Use these settings', '#/new-report'); reuse.hidden = true;
  const templateLink = link('Open template version', '#/templates'); templateLink.hidden = true;
  const badgeArea = el('div');
  root.replaceChildren(link('← Reports', '#/reports'), heading('Report details', id, badgeArea), acceptance, status,
    el('div', {class:'toolbar'}, refresh, download, preview, button('Copy link', () => copy(location.href, status)), button('Copy ID', () => copy(id, status))),
    el('div', {class:'grid'}, el('section', {}, info, errorBox), el('aside', {class:'panel'}, el('h2', {}, 'This run'),
      el('div', {class:'actions'}, templateLink, reuse), el('hr', {class:'divider'}), el('p', {class:'muted'}, 'Accepted means the data and job were stored. The worker validates inputs and generates the result.'),
      el('p', {class:'muted'}, 'Use these settings starts a new form. You must supply data again. No automatic retry or cancellation is available.'))), previewArea);
  function terminal() { return row && ['succeeded','failed','expired'].includes(row.state); }
  function schedule() {
    clearTimeout(timer);
    if (ctx.active && !document.hidden && !terminal() && !missing && !halted) timer = setTimeout(() => load(), delay);
  }
  function render(user) {
    badgeArea.replaceChildren(badge(row.state, row.terminal_state));
    info.replaceChildren(details([['Report ID', el('span', {class:'mono'}, row.id)], ['Template', `${row.template_id} · v${row.template_version}`], ['Renderer / output', `${row.renderer} / ${row.output.toUpperCase()}`], ['Attempts', String(row.attempts)], ['Created', date(row.created_at)], ['Started', date(row.started_at)], ['Finished', date(row.finished_at)], ['Result expires', date(row.result_expires_at)], ['Terminal state', row.terminal_state], ['Engine version', row.engine_version], ['Service version', row.service_version], ['Image', el('span', {class:'mono'}, row.image_id || '—')]]));
    message(errorBox, row.error ? `${row.error.message} (${row.error.code})${row.error.id ? ` · Reference ${row.error.id}` : ''}` : '', row.error ? 'error' : '', user);
    download.hidden = row.state !== 'succeeded'; preview.hidden = row.state !== 'succeeded' || row.output !== 'html';
    download.textContent = `Download ${row.output.toUpperCase()}`;
    templateLink.hidden = false; templateLink.href = `#/templates/${encodeURIComponent(row.template_id)}?version=${row.template_version}`;
    reuse.hidden = false; reuse.href = `#/new-report?${new URLSearchParams({template:row.template_id,version:row.template_version,renderer:row.renderer,output:row.output})}`;
    if (row.state !== 'succeeded') { previewArea.replaceChildren(); previewArea.hidden = true; }
  }
  async function load(user = false) {
    if (!ctx.active || busy || document.hidden) return false;
    clearTimeout(timer); busy = true; refresh.disabled = true;
    try {
      const next = await api(`/v1/reports/${encodeURIComponent(id)}`, {}, ctx.controller.signal);
      if (!ctx.active) return false;
      row = next; missing = false; halted = false; delay = 2000; render(user);
      if (accepted) { message(acceptance, `Accepted (202): ${row.id} · ${row.template_id} version ${row.template_version}. Data and job are stored.`, 'success'); accepted = false; }
      message(status, `Status checked ${date(new Date().toISOString())}.`);
      return true;
    } catch (error) {
      if (!ctx.active) return false;
      missing = error instanceof APIError && error.status === 404;
      halted = error instanceof APIError && error.status >= 400 && error.status < 500 && error.status !== 429;
      delay = Math.max(Math.min(delay * 2, 30000), (error.retryAfter || 0) * 1000);
      message(status, missing ? 'This report does not exist or its metadata has expired.' : `Status is stale. ${error.message || 'Connection failed.'} Refresh to try again.`, 'error', user);
      download.hidden = true; preview.hidden = true;
      previewArea.replaceChildren(); previewArea.hidden = true;
      return false;
    } finally { busy = false; refresh.disabled = false; schedule(); }
  }
  download.addEventListener('click', async event => {
    event.preventDefault(); if (await load(true) && row.state === 'succeeded') {
      const anchor = el('a', {href:contentUrl, download:''}); anchor.click();
    }
  });
  async function showPreview() {
    if (!await load(true) || row.state !== 'succeeded' || row.output !== 'html') return;
    previewArea.hidden = false;
    previewArea.replaceChildren(el('h2', {}, 'HTML preview'), el('p', {class:'muted'}, 'HTML may differ from checked PDF output. If an expiry error appears here, refresh the report status.'),
      el('iframe', {class:'preview', title:'Report preview', sandbox:'allow-scripts', src:contentUrl + '?disposition=inline'}));
  }
  const visibility = () => { clearTimeout(timer); if (!document.hidden) load(); };
  document.addEventListener('visibilitychange', visibility);
  ctx.cleanup.push(() => { clearTimeout(timer); document.removeEventListener('visibilitychange', visibility); });
  await load();
}
