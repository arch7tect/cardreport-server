import {api, el, field, button, link, heading, notice, message, select, formats, formatFor, mutationError, query} from './common.js';

export async function newReport(root, ctx, params) {
  const template = select([['', 'Select a template…']]), version = select([['', 'Latest at submission']]);
  const renderer = select([['chromium', 'Chromium'], ['weasyprint', 'WeasyPrint']], params.get('renderer') || 'chromium');
  const output = select([['pdf', 'PDF'], ['html', 'HTML']], params.get('output') || 'pdf');
  const mode = select([['file', 'Upload file'], ['paste', 'Paste text'], ['csv', 'CSV files']]);
  const format = select(formats), file = el('input', {type:'file', accept:'.json,.yaml,.yml', required:true});
  const text = el('textarea', {spellcheck:false, placeholder:'Paste a cardreport.data/1 JSON or YAML bundle…'});
  const fileField = field('Dataset file', file), textField = field('Dataset source', text); textField.hidden = true;
  const csvFiles = el('input', {type:'file', accept:'.csv', multiple:true});
  const bundle = el('input', {type:'file', accept:'.json,.yaml,.yml'});
  const encoding = el('input', {value:'utf-8', maxLength:128});
  const delimiter = el('input', {value:',', maxLength:2});
  const nullTokens = el('textarea', {rows:2, placeholder:'NULL\nN/A', spellcheck:false});
  const emptyNull = el('input', {type:'checkbox'});
  const formatField = field('Data format', format);
  const csvFields = el('div', {hidden:true},
    field('CSV files', csvFiles, 'Select all files for this run. summary.csv supplies dataset summary; column types come from the selected template.'),
    field('Additional JSON/YAML bundle (optional)', bundle, 'Dataset names must not duplicate those in the CSV files.'),
    el('details', {class:'csv-options'}, el('summary', {}, 'CSV options'),
      el('div', {class:'grid equal'}, field('CSV encoding', encoding), field('CSV delimiter', delimiter, 'One character; use \\t for a tab.')),
      field('Null tokens', nullTokens, 'One exact token per line. By default, no values are converted to null.'),
      el('label', {class:'check-field'}, emptyNull, 'Treat empty cells as null')));
  const status = notice(), submit = el('button', {type:'submit', class:'primary', disabled:true}, 'Generate report');
  const moreTemplates = button('Load more templates', loadTemplates), moreVersions = button('Load more versions', loadVersions);
  const fields = el('fieldset', {class:'form-fields'},
    field('Template', template), moreTemplates, field('Template version', version, 'Pin a version, or resolve the latest when the server accepts this upload.'), moreVersions,
    el('div', {class:'grid equal'}, field('Renderer', renderer), field('Output', output)),
    el('hr', {class:'divider'}), el('h2', {}, 'Named datasets'),
    el('div', {class:'grid equal'}, field('Data input', mode), formatField), fileField, textField, csvFields);
  const form = el('form', {}, fields, submit);
  root.replaceChildren(heading('New report', 'Choose a stored template. Supply the data for this run.'), status,
    el('div', {class:'grid'}, el('section', {class:'panel'}, form), el('aside', {class:'panel'}, el('h2', {}, 'From data to a report'),
      el('ol', {class:'steps'}, el('li', {}, 'Select a template and version.'), el('li', {}, 'Upload CSV files, or upload or paste a JSON/YAML bundle.'), el('li', {}, 'Generate, follow the status, then download.')),
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
  for (const control of [file, text, csvFiles, bundle, encoding, delimiter, nullTokens, emptyNull]) control.addEventListener('input', () => { ctx.dirty = true; });
  template.addEventListener('change', () => chooseTemplate());
  mode.addEventListener('change', () => {
    fileField.hidden = mode.value !== 'file'; textField.hidden = mode.value !== 'paste';
    file.required = mode.value === 'file'; text.required = mode.value === 'paste';
    csvFields.hidden = mode.value !== 'csv'; formatField.hidden = mode.value === 'csv';
    csvFiles.required = mode.value === 'csv';
  });
  file.addEventListener('change', () => { if (file.files[0]) format.value = formatFor(file.files[0].name); });
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (sending || archived || !selectedId) return;
    let payload, size = 0, headers = {};
    if (mode.value === 'csv') {
      if (!csvFiles.files.length) return;
      const names = [...csvFiles.files].map(f => f.name.slice(0, -4));
      if (csvFiles.files.length > 32 || new Set(names).size !== names.length) {
        message(status, 'Choose at most 32 CSV files with distinct dataset names.', 'error'); return;
      }
      const separator = delimiter.value === '\\t' ? '\t' : delimiter.value;
      if ([...separator].length !== 1 || !encoding.value) {
        message(status, 'Enter a CSV delimiter and encoding.', 'error'); return;
      }
      const tokens = nullTokens.value.split(/\r?\n/).filter(token => token !== '');
      if (emptyNull.checked) tokens.push('');
      if (tokens.length > 32) { message(status, 'Use at most 32 null tokens.', 'error'); return; }
      payload = new FormData();
      for (const source of csvFiles.files) { payload.append('files', source); size += source.size; }
      if (bundle.files[0]) { payload.append('data', bundle.files[0]); size += bundle.files[0].size; }
      payload.append('csv_encoding', encoding.value);
      payload.append('csv_delimiter', separator);
      for (const token of tokens) payload.append('csv_null', token);
    } else {
      payload = mode.value === 'file' ? file.files[0] : text.value;
      if (!payload || (typeof payload === 'string' && !payload.trim())) return;
      size = payload instanceof File ? payload.size : new Blob([payload]).size;
      headers = {'Content-Type':format.value};
    }
    if (size > 16 * 1024 * 1024) { message(status, 'Dataset bundle exceeds the 16 MiB library limit. This server may use a lower limit.', 'error'); return; }
    sending = true; ctx.dirty = true; submit.disabled = true; fields.disabled = true;
    message(status, 'Sending… Leaving this page does not cancel a report accepted by the server.');
    try {
      const result = await api(query('/v1/reports', {template_id:selectedId, template_version:version.value, renderer:renderer.value, output:output.value}),
        {method:'POST', headers, body:payload});
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
