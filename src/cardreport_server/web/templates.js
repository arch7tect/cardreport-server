import {api, el, field, button, link, heading, notice, message, badge, date, duration, details, select, formats, formatFor, saveText, copy, mutationError, query} from './common.js';

export async function templates(root, ctx) {
  const filter = select([['false', 'Active'], ['true', 'Archived'], ['', 'All templates']]);
  const search = el('input', {type:'search', placeholder:'Name or ID', maxLength:200});
  const status = notice(), body = el('tbody'), pageLabel = el('span', {class:'muted'});
  const previous = button('Previous', () => load('previous')), next = button('Next', () => load('next'));
  const filters = el('form', {class:'toolbar'}, field('Search templates', search), field('Show', filter),
    el('button', {type:'submit'}, 'Search'), button('Refresh', () => load('reset')), button('Clear filters', () => {
      search.value = ''; filter.value = 'false'; load('reset');
    }));
  const table = el('div', {class:'panel flush'}, el('div', {class:'table-wrap'}, el('table', {},
    el('thead', {}, el('tr', {}, ...['Template', 'State', 'Latest version', 'Created'].map(x => el('th', {}, x)))), body)),
    el('div', {class:'table-footer actions'}, previous, pageLabel, next));
  root.replaceChildren(heading('Templates', 'Versioned definitions, ready to reuse with fresh data.', link('＋ Create template', '#/create-template', true)),
    filters, status, table);
  let cursors = [''], page = 0, nextCursor = null, request = 0, applied = {};
  async function load(direction = 'reset') {
    const token = ++request; previous.disabled = true; next.disabled = true;
    if (direction === 'reset') {
      page = 0; cursors = ['']; nextCursor = null; body.replaceChildren(); pageLabel.textContent = '';
      if (!filters.reportValidity()) return;
      applied = {archived:filter.value, q:search.value.trim()};
    }
    const target = direction === 'next' ? page+1 : direction === 'previous' ? page-1 : 0;
    const cursor = direction === 'next' ? nextCursor : cursors[target];
    try {
      const data = await api(query('/v1/templates', {...applied, after:cursor, limit:50}), {}, ctx.controller.signal);
      if (!ctx.active || token !== request) return;
      body.replaceChildren();
      for (const row of data.items) body.append(el('tr', {}, el('td', {}, link(row.id, `#/templates/${row.id}`),
        row.title ? el('div', {class:'muted'}, row.title) : null), el('td', {}, badge(row.archived ? 'archived' : 'active')),
        el('td', {}, `v${row.latest_version}`), el('td', {}, date(row.created_at))));
      page = target; cursors = cursors.slice(0, target); cursors.push(cursor); nextCursor = data.next;
      pageLabel.textContent = `Page ${page+1} · ${data.items.length} templates`;
      message(status, data.items.length ? '' : 'No templates match these filters. Create one or change the filters.');
    } catch (error) { if (ctx.active && token === request) message(status, error.message, 'error'); }
    finally { if (ctx.active && token === request) { previous.disabled = page === 0; next.disabled = !nextCursor; } }
  }
  filters.addEventListener('submit', event => {event.preventDefault(); load('reset');});
  for (const control of [filter, search]) control.addEventListener('change', () => load('reset'));
  await load();
}

export async function templateDetail(root, ctx, id, chosen = null) {
  const metadata = await api(`/v1/templates/${encodeURIComponent(id)}`, {}, ctx.controller.signal);
  const initial = chosen || String(metadata.latest_version);
  const status = notice(), version = select([[initial, `Version ${initial}`]], initial);
  const definition = el('pre', {tabIndex:0}), info = el('div');
  let current = null, after = 0, request = 0;
  const more = button('Load more versions', loadVersions); more.hidden = true;
  const actions = el('div', {class:'actions'});
  const archive = button(metadata.archived ? 'Restore template' : 'Archive template', async () => {
    if (!metadata.archived && !confirm('Archive this template? New versions and new reports will be blocked. Existing reports stay available.')) return;
    archive.disabled = true;
    try { await api(`/v1/templates/${encodeURIComponent(id)}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({archived:!metadata.archived})});
      if (ctx.active) { metadata.archived = !metadata.archived; archive.textContent = metadata.archived ? 'Restore template' : 'Archive template'; renderActions(); message(status, metadata.archived ? 'Template archived.' : 'Template restored.', 'success'); }
    } catch (error) { if (ctx.active) message(status, mutationError(error), 'error'); }
    finally { archive.disabled = false; }
  });
  const unitSeconds = 86400;
  // Six decimal places round-trip every allowed whole-second duration in days.
  const displayValue = seconds => seconds == null ? '' : String(Number((seconds / unitSeconds).toFixed(6)));
  const retention = el('input', {type:'number', min:0, step:'any', value:displayValue(metadata.retention_seconds), placeholder:'Use server default'});
  const policyStatus = notice();
  const policyHint = el('p', {class:'muted'});
  function policyInfo() { policyHint.textContent = `Effective retention: ${duration(metadata.effective_retention_seconds)}. Applies to future reports only, from completion. Original files, normalized data and output expire together.`; }
  function secondsValue() {
    return retention.value === '' ? null : Math.round(Number(retention.value) * unitSeconds);
  }
  function validateRetention() {
    const seconds = secondsValue();
    retention.setCustomValidity(seconds !== null && (!Number.isFinite(seconds) || seconds < 1 || seconds > 2147483000)
      ? `Enter a duration from 1 second to ${duration(2147483000)}, or leave empty.` : '');
  }
  policyInfo();
  const savePolicy = el('button', {type:'submit'}, 'Save retention');
  const retentionField = field('Retention (days)', retention);
  const help = el('p', {class:'muted', id:`${retention.id}-help`}, 'Leave empty to inherit the server default. Fractions are allowed; durations are rounded to the nearest second.');
  retention.setAttribute('aria-describedby', help.id);
  const policyForm = el('form', {}, el('div', {class:'toolbar'}, retentionField, savePolicy), help, policyHint, policyStatus);
  retention.addEventListener('input', () => { validateRetention(); ctx.dirty = true; message(policyStatus, ''); });
  policyForm.addEventListener('submit', async event => {
    event.preventDefault(); validateRetention();
    if (!policyForm.reportValidity()) return;
    const seconds = secondsValue();
    savePolicy.disabled = true; retention.disabled = true;
    message(policyStatus, '');
    try {
      const updated = await api(`/v1/templates/${encodeURIComponent(id)}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({retention_seconds:seconds})});
      if (ctx.active) { Object.assign(metadata, updated); retention.value = displayValue(metadata.retention_seconds); ctx.dirty = false; policyInfo(); message(policyStatus, 'Retention saved for future reports.', 'success'); }
    } catch (error) { if (ctx.active) message(policyStatus, mutationError(error), 'error'); }
    finally { savePolicy.disabled = false; retention.disabled = false; }
  });
  function renderActions() {
    actions.replaceChildren(badge(metadata.archived ? 'archived' : 'active'));
    if (!metadata.archived && current) actions.append(link('New report', `#/new-report?template=${encodeURIComponent(id)}&version=${version.value}`, true), link('Create new version', `#/templates/${encodeURIComponent(id)}/edit?version=${version.value}`));
    actions.append(archive);
  }
  async function loadVersion() {
    const token = ++request; current = null; definition.textContent = 'Loading…'; info.replaceChildren(); renderActions();
    try {
      const row = await api(`/v1/templates/${encodeURIComponent(id)}/versions/${version.value}`, {}, ctx.controller.signal);
      if (!ctx.active || token !== request) return;
      current = row;
      definition.textContent = JSON.stringify(row.definition, null, 2);
      info.replaceChildren(details([['Version', `v${row.version}`], ['Created', date(row.created_at)], ['Validated with', row.validated_with], ['SHA-256', el('span', {class:'mono'}, row.digest)]]));
      renderActions(); message(status, '');
    } catch (error) { if (ctx.active && token === request) message(status, error.message, 'error'); }
  }
  async function loadVersions() {
    more.disabled = true;
    try {
      const data = await api(query(`/v1/templates/${encodeURIComponent(id)}/versions`, {after}), {}, ctx.controller.signal);
      if (!ctx.active) return;
      const existing = new Set([...version.options].map(x => x.value));
      for (const row of data.items) if (!existing.has(String(row.version))) version.append(el('option', {value:row.version}, `Version ${row.version}`));
      after = data.next; more.hidden = after === null;
    } catch (error) { if (ctx.active) message(status, error.message, 'error'); }
    finally { more.disabled = false; }
  }
  if (!ctx.active) return;
  root.replaceChildren(link('← Templates', '#/templates'), heading(id, 'Immutable versions. Editing always creates a new version.'), status,
    el('div', {class:'panel'}, actions), el('section', {class:'panel'}, el('h2', {}, 'Report retention'), policyForm), el('div', {class:'grid'},
      el('section', {class:'panel'}, el('div', {class:'toolbar'}, field('Version', version), more), definition,
        el('div', {class:'actions'}, button('Copy JSON', () => copy(definition.textContent, status)), button('Download JSON', () => {if (current) saveText(`${id}-v${current.version}.json`, definition.textContent);}))),
      el('aside', {class:'panel'}, el('h2', {}, 'Version details'), info, el('hr', {class:'divider'}), el('p', {class:'muted'}, 'Stored definitions are canonical JSON. Original YAML comments and formatting are not retained.'))));
  version.addEventListener('change', () => { history.replaceState(null, '', `#/templates/${encodeURIComponent(id)}?version=${version.value}`); loadVersion(); }); await loadVersion(); await loadVersions();
}

export async function templateEditor(root, ctx, id = null, revision = null) {
  const slug = el('input', {value:id || '', required:true, pattern:'[a-z0-9][a-z0-9_-]{0,63}', maxLength:64, readOnly:!!id, placeholder:'monthly-summary'});
  const format = select(formats), source = el('textarea', {required:true, spellcheck:false, placeholder:'Paste your cardreport.template/1 JSON or YAML here…'});
  const file = el('input', {type:'file', accept:'.json,.yaml,.yml'}), status = notice();
  if (id) {
    const metadata = await api(`/v1/templates/${encodeURIComponent(id)}`, {}, ctx.controller.signal);
    const row = await api(`/v1/templates/${encodeURIComponent(id)}/versions/${revision || metadata.latest_version}`, {}, ctx.controller.signal);
    if (!ctx.active) return;
    source.value = JSON.stringify(row.definition, null, 2);
    if (metadata.archived) throw new Error('This template is archived. Restore it before creating a version.');
  }
  const submit = el('button', {type:'submit', class:'primary'}, 'Save new version');
  const form = el('form', {}, field('Template ID', slug, 'Lowercase letters, numbers, hyphens and underscores.'),
    el('div', {class:'grid equal'}, field('Source format', format), field('Import template file', file)),
    field('Template source', source, 'Validation happens on save. YAML comments and formatting are not stored.'), el('div', {class:'actions'}, submit, link('Back to templates', '#/templates')));
  form.addEventListener('input', () => { ctx.dirty = true; });
  file.addEventListener('change', async () => {
    const chosen = file.files[0]; if (!chosen) return;
    if (chosen.size > 1024 * 1024) { message(status, 'Template exceeds the 1 MiB library limit.', 'error'); return; }
    const text = await chosen.text(); if (!ctx.active) return;
    source.value = text; format.value = formatFor(chosen.name); ctx.dirty = true;
  });
  let sending = false;
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (sending) return;
    sending = true; ctx.dirty = true; submit.disabled = true;
    const target = slug.value, body = source.value, kind = format.value;
    form.querySelectorAll('input,select,textarea').forEach(node => { node.disabled = true; });
    message(status, 'Saving and validating…');
    try {
      const result = await api(`/v1/templates/${encodeURIComponent(target)}/versions`, {method:'POST', headers:{'Content-Type':kind}, body});
      if (ctx.active) ctx.go(`#/templates/${encodeURIComponent(target)}?version=${result.version}`);
    } catch (error) { if (ctx.active) message(status, mutationError(error), 'error'); }
    finally { sending = false; submit.disabled = false; form.querySelectorAll('input,select,textarea').forEach(node => { node.disabled = false; }); }
  });
  if (!ctx.active) return;
  root.replaceChildren(heading(id ? 'New template version' : 'Create template', id ? `Editing ${id}. Existing versions will stay unchanged.` : 'Define the report once. Supply fresh data on every run.'), status,
    el('div', {class:'grid'}, el('section', {class:'panel'}, form), el('aside', {class:'panel'}, el('h2', {}, 'A reusable definition'),
      el('ol', {class:'steps'}, el('li', {}, 'Choose a stable template ID.'), el('li', {}, 'Import or paste a CardReport template.'), el('li', {}, 'Save a validated, immutable version.')),
      el('p', {class:'muted'}, 'Templates describe presentation and dataset bindings. Data is supplied separately when you generate a report.'), link('Template API documentation ↗', '/docs'))));
}
