import {api, el, field, button, link, heading, notice, message, select, formats, formatFor, mutationError, query} from './common.js';

export async function newReport(root, ctx, params) {
  const template = select([['', 'Select a template…']]), version = select([['', 'Latest at submission']]);
  const renderer = select([['chromium', 'Chromium'], ['weasyprint', 'WeasyPrint']], params.get('renderer') || 'chromium');
  const output = select([['pdf', 'PDF'], ['html', 'HTML']], params.get('output') || 'pdf');
  const mode = select([['file', 'Upload file'], ['paste', 'Paste text']]);
  const format = select(formats), file = el('input', {type:'file', accept:'.json,.yaml,.yml', required:true});
  const text = el('textarea', {spellcheck:false, placeholder:'Paste a cardreport.data/1 JSON or YAML bundle…'});
  const fileField = field('Dataset file', file), textField = field('Dataset source', text); textField.hidden = true;
  const status = notice(), submit = el('button', {type:'submit', class:'primary', disabled:true}, 'Generate report');
  const moreTemplates = button('Load more templates', loadTemplates), moreVersions = button('Load more versions', loadVersions);
  const fields = el('fieldset', {class:'form-fields'},
    field('Template', template), moreTemplates, field('Template version', version, 'Pin a version, or resolve the latest when the server accepts this upload.'), moreVersions,
    el('div', {class:'grid equal'}, field('Renderer', renderer), field('Output', output)),
    el('hr', {class:'divider'}), el('h2', {}, 'Named datasets'),
    el('div', {class:'grid equal'}, field('Data input', mode), field('Data format', format)), fileField, textField);
  const form = el('form', {}, fields, submit);
  root.replaceChildren(heading('New report', 'Choose a stored template. Supply the data for this run.'), status,
    el('div', {class:'grid'}, el('section', {class:'panel'}, form), el('aside', {class:'panel'}, el('h2', {}, 'From data to a report'),
      el('ol', {class:'steps'}, el('li', {}, 'Select a template and version.'), el('li', {}, 'Upload or paste a named-dataset bundle.'), el('li', {}, 'Generate, follow the status, then download.')),
      el('hr', {class:'divider'}), el('p', {class:'muted'}, 'Chromium supports dashboard and flow layouts. WeasyPrint supports dashboards only. HTML is a preview; PDF is the checked output.'),
      el('p', {class:'muted'}, 'Acceptance is not render success. Input is validated by the worker. No dataset is saved in this browser.'), link('View shared report history', '#/reports'))));
  let templateAfter = '', versionAfter = 0, versionRequest = 0, selectedId = '', archived = false, sending = false;
  async function loadTemplates() {
    moreTemplates.disabled = true;
    try {
      const data = await api(query('/v1/templates', {archived:false, after:templateAfter}), {}, ctx.controller.signal);
      if (!ctx.active) return;
      const existing = new Set([...template.options].map(x => x.value));
      for (const row of data.items) if (!existing.has(row.id)) template.append(el('option', {value:row.id}, row.id));
      templateAfter = data.next; moreTemplates.hidden = !templateAfter;
    } catch (error) { if (ctx.active) message(status, error.message, 'error'); }
    finally { moreTemplates.disabled = false; }
  }
  async function chooseTemplate(wantedVersion = null) {
    const token = ++versionRequest;
    selectedId = template.value; versionAfter = 0; submit.disabled = true;
    version.replaceChildren(el('option', {value:''}, 'Latest at submission')); moreVersions.hidden = true;
    if (!selectedId) return;
    try {
      const row = await api(`/v1/templates/${encodeURIComponent(selectedId)}`, {}, ctx.controller.signal);
      if (!ctx.active || token !== versionRequest) return;
      archived = row.archived;
      const chosen = wantedVersion || String(row.latest_version);
      version.append(el('option', {value:chosen}, `Version ${chosen}`)); version.value = chosen;
      message(status, archived ? 'This template is archived. Restore it before generating a report.' : '', archived ? 'error' : '');
      submit.disabled = archived;
      await loadVersions();
    } catch (error) { if (ctx.active && token === versionRequest) message(status, error.message, 'error'); }
  }
  async function loadVersions() {
    if (!selectedId) return;
    const token = versionRequest, id = selectedId; moreVersions.disabled = true;
    try {
      const data = await api(query(`/v1/templates/${encodeURIComponent(id)}/versions`, {after:versionAfter}), {}, ctx.controller.signal);
      if (!ctx.active || token !== versionRequest) return;
      const existing = new Set([...version.options].map(x => x.value));
      for (const row of data.items) if (!existing.has(String(row.version))) version.append(el('option', {value:row.version}, `Version ${row.version}`));
      versionAfter = data.next; moreVersions.hidden = versionAfter === null;
    } catch (error) { if (ctx.active && token === versionRequest) message(status, error.message, 'error'); }
    finally { if (token === versionRequest) moreVersions.disabled = false; }
  }
  for (const control of [file, text]) control.addEventListener('input', () => { ctx.dirty = true; });
  template.addEventListener('change', () => chooseTemplate());
  mode.addEventListener('change', () => {
    fileField.hidden = mode.value !== 'file'; textField.hidden = mode.value !== 'paste';
    file.required = mode.value === 'file'; text.required = mode.value === 'paste';
  });
  file.addEventListener('change', () => { if (file.files[0]) format.value = formatFor(file.files[0].name); });
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (sending || archived || !selectedId) return;
    const payload = mode.value === 'file' ? file.files[0] : text.value;
    if (!payload || (typeof payload === 'string' && !payload.trim())) return;
    const size = payload instanceof File ? payload.size : new Blob([payload]).size;
    if (size > 16 * 1024 * 1024) { message(status, 'Dataset bundle exceeds the 16 MiB library limit. This server may use a lower limit.', 'error'); return; }
    sending = true; ctx.dirty = true; submit.disabled = true; fields.disabled = true;
    message(status, 'Sending… Leaving this page does not cancel a report accepted by the server.');
    try {
      const result = await api(query('/v1/reports', {template_id:selectedId, template_version:version.value, renderer:renderer.value, output:output.value}),
        {method:'POST', headers:{'Content-Type':format.value}, body:payload});
      if (ctx.active) ctx.go(`#/reports/${result.id}?accepted=1`);
    } catch (error) { if (ctx.active) message(status, mutationError(error), 'error'); }
    finally { sending = false; submit.disabled = archived; fields.disabled = false; }
  });
  await loadTemplates();
  if (params.get('template') && ctx.active) {
    const id = params.get('template');
    if (![...template.options].some(x => x.value === id)) template.append(el('option', {value:id}, id));
    template.value = id; await chooseTemplate(params.get('version'));
  }
}
