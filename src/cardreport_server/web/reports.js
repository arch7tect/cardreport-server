import {renderLayoutDiagnostic} from './layout-diagnostics.js';
import {CursorPages, api, APIError, el, field, button, link, heading, notice, message, badge, date, duration, details, select, query, copy} from './common.js';

export async function reports(root, ctx) {
  const template = el('input', {placeholder:'All templates', maxLength:64, pattern:'[a-z0-9][a-z0-9_-]{0,63}'});
  const state = select([['','All states'], ...['queued','running','succeeded','failed','expired'].map(x => [x,x[0].toUpperCase()+x.slice(1)])]);
  const from = el('input', {type:'datetime-local', step:1}), before = el('input', {type:'datetime-local', step:1});
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const status = notice(), body = el('tbody'), pageLabel = el('span', {class:'muted'});
  const previous = button('Previous', () => load('previous')), next = button('Next', () => load('next'));
  const filters = el('form', {class:'toolbar'}, field('Template ID', template), field('State', state),
    field('Created from', from), field('Created before', before), el('button', {type:'submit'}, 'Refresh'), button('Clear filters', () => {
      template.value = ''; state.value = ''; from.value = ''; before.value = ''; load('reset');
    }));
  root.replaceChildren(heading('Reports', 'Shared history of retained jobs, newest first.', link('＋ New report', '#/new-report', true)),
    filters, el('p', {class:'muted'}, `Creation time in ${zone}. From is inclusive; before is exclusive. Leave either boundary empty for an open-ended search.`), status,
    el('div', {class:'panel flush'}, el('div', {class:'table-wrap'}, el('table', {},
      el('thead', {}, el('tr', {}, ...['Report', 'Template', 'State', 'Output', 'Created'].map(x => el('th', {}, x)))), body)),
      el('div', {class:'table-footer actions'}, previous, pageLabel, next)));
  const pages = new CursorPages();
  let token = 0, applied = {};
  function timestamp(control) {
    if (!control.value) return '';
    const date = new Date(control.value), parts = control.value.split(/\D/).map(Number);
    const actual = [date.getFullYear(), date.getMonth()+1, date.getDate(), date.getHours(), date.getMinutes(), date.getSeconds()];
    if (Number.isNaN(date.getTime()) || parts.some((part, index) => actual[index] !== part)) throw new Error(`Choose a valid local time in ${zone}.`);
    return date.toISOString();
  }
  /** @param {'reset' | 'next' | 'previous'} direction */
  async function load(direction = 'reset') {
    const request = ++token; previous.disabled = true; next.disabled = true;
    if (direction === 'reset') {
      pages.reset(); body.replaceChildren(); pageLabel.textContent = '';
      if (!filters.reportValidity()) return;
      try {
        applied = {template_id:template.value.trim(), state:state.value, created_from:timestamp(from), created_before:timestamp(before)};
        if (applied.created_from && applied.created_before && applied.created_from >= applied.created_before) throw new Error('Created from must be earlier than created before.');
      } catch (error) { message(status, error.message, 'error'); return; }
    }
    const target = pages.target(direction);
    try {
      const data = await api(query('/v1/reports', {...applied, after:target.cursor, limit:50}), {}, ctx.controller.signal);
      if (!ctx.active || request !== token) return;
      body.replaceChildren();
      for (const row of data.items) body.append(el('tr', {}, el('td', {}, link(row.id.slice(0,8), `#/reports/${row.id}`)),
        el('td', {}, link(row.template_id, `#/templates/${row.template_id}?version=${row.template_version}`), el('div', {class:'muted'}, `Version ${row.template_version}`)),
        el('td', {}, badge(row.state, row.terminal_state)), el('td', {}, row.output.toUpperCase(), el('div', {class:'muted'}, row.renderer)), el('td', {}, date(row.created_at))));
      pages.commit(target, data.next);
      pageLabel.textContent = `Page ${pages.page+1} · ${data.items.length} reports`;
      message(status, data.items.length ? '' : 'No retained reports match these filters.');
    } catch (error) { if (ctx.active && request === token) message(status, `History could not be refreshed. ${error.message}`, 'error'); }
    finally { if (request === token) { previous.disabled = pages.page === 0; next.disabled = !pages.next; } }
  }
  filters.addEventListener('submit', event => {event.preventDefault(); load('reset');});
  for (const control of [state, template, from, before]) control.addEventListener('change', () => load('reset'));
  await load();
}

export async function reportDetail(root, ctx, id, params = new URLSearchParams()) {
  let accepted = params.get('accepted') === '1';
  const acceptance = notice();
  if (accepted) history.replaceState(null, '', `#/reports/${encodeURIComponent(id)}`);
  const status = notice(), info = el('div', {class:'panel'}), errorBox = notice(), layoutDetails = el('div');
  const previewArea = el('section', {id:'html-preview', class:'panel', hidden:true});
  const dataArea = el('section', {id:'report-data', class:'panel', hidden:true});
  const showData = button('Show data', toggleData); showData.hidden = true;
  showData.setAttribute('aria-controls', 'report-data'); showData.setAttribute('aria-expanded', 'false');
  const dataHint = el('p', {class:'muted', hidden:true}, 'No saved data is available for this report. Snapshots are saved with successful reports generated by the current version.');
  const filesArea = el('section', {id:'report-files', class:'panel', hidden:true});
  const showFiles = button('Show input files', toggleFiles); showFiles.hidden = true;
  showFiles.setAttribute('aria-controls', 'report-files'); showFiles.setAttribute('aria-expanded', 'false');
  let filesRequest = 0;
  let dataRequest = 0;
  const contentUrl = `/v1/reports/${encodeURIComponent(id)}/content`;
  let row = null, busy = false, timer = null, delay = 2000, missing = false, halted = false;
  const refresh = button('Refresh status', () => load(true));
  const download = el('a', {href:contentUrl, class:'button primary', hidden:true}, 'Download');
  const preview = button('Preview HTML', showPreview); preview.hidden = true;
  preview.setAttribute('aria-controls', 'html-preview'); preview.setAttribute('aria-expanded', 'false');
  const openResult = el('a', {href:contentUrl + '?disposition=inline', target:'_blank', rel:'noopener noreferrer', class:'button', hidden:true}, 'Open PDF');
  const pdfHint = el('p', {class:'muted'}, 'Open PDF uses your browser’s viewer in a new tab. Browser settings may download it instead; an expired result opens an error.'); pdfHint.hidden = true;
  let previewObserver = null, previewRequest = 0;
  const reuse = link('Use these settings', '#/new-report'); reuse.hidden = true;
  const templateLink = link('Open template version', '#/templates'); templateLink.hidden = true;
  const badgeArea = el('div');
  root.replaceChildren(link('← Reports', '#/reports'), heading('Report details', id, badgeArea), acceptance, status,
    el('div', {class:'toolbar'}, refresh, download, openResult, preview, showData, showFiles, button('Copy link', () => copy(location.href, status)), button('Copy ID', () => copy(id, status))),
    el('div', {class:'grid'}, el('section', {}, info, errorBox, layoutDetails), el('aside', {class:'panel'}, el('h2', {}, 'This run'),
      el('div', {class:'actions'}, templateLink, reuse), el('hr', {class:'divider'}), el('p', {class:'muted'}, 'Accepted means the data and job were stored. The worker validates inputs and generates the result.'),
      pdfHint,
      el('p', {class:'muted'}, 'Use these settings starts a new form. You must supply data again. No automatic retry or cancellation is available.'))), dataHint, filesArea, dataArea, previewArea);
  function terminal() { return row && ['succeeded','failed','expired'].includes(row.state); }
  function schedule() {
    clearTimeout(timer);
    if (ctx.active && !document.hidden && !terminal() && !missing && !halted) timer = setTimeout(() => load(), delay);
  }
  function render(user) {
    badgeArea.replaceChildren(badge(row.state, row.terminal_state));
    info.replaceChildren(details([['Report ID', el('span', {class:'mono'}, row.id)], ['Template', `${row.template_id} · v${row.template_version}`], ['Renderer / output', `${row.renderer} / ${row.output.toUpperCase()}`], ['Attempts', String(row.attempts)], ['Created', date(row.created_at)], ['Started', date(row.started_at)], ['Finished', date(row.finished_at)], ['Result expires', date(row.result_expires_at)], ['Inputs expire', date(row.input_expires_at)], ['Input retention', duration(row.retention_seconds)], ['Terminal state', row.terminal_state], ['Engine version', row.engine_version], ['Service version', row.service_version], ['Image', el('span', {class:'mono'}, row.image_id || '—')]]));
    message(errorBox, row.error ? `${row.error.message} (${row.error.code})${row.error.id ? ` · Reference ${row.error.id}` : ''}` : '', row.error ? 'error' : '', user);
    renderLayoutDiagnostic(layoutDetails, row.error?.code === 'layout_overflow' ? row.error.diagnostic : null);
    download.hidden = row.state !== 'succeeded'; preview.hidden = row.state !== 'succeeded' || row.output !== 'html';
    download.textContent = `Download ${row.output.toUpperCase()}`;
    openResult.hidden = row.state !== 'succeeded';
    openResult.textContent = `Open ${row.output.toUpperCase()}`;
    pdfHint.hidden = row.output !== 'pdf';
    templateLink.hidden = false; templateLink.href = `#/templates/${encodeURIComponent(row.template_id)}?version=${row.template_version}`;
    reuse.hidden = false; reuse.href = `#/new-report?${new URLSearchParams({template:row.template_id,version:row.template_version,renderer:row.renderer,output:row.output})}`;
    showFiles.hidden = !row.inputs_available;
    if (!row.inputs_available) clearFiles();
    showData.hidden = !row.data_available;
    dataHint.hidden = row.state !== 'succeeded' || row.data_available;
    if (!row.data_available) clearData();
    if (row.state !== 'succeeded') clearPreview();
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
      download.hidden = true; preview.hidden = true; openResult.hidden = true;
      clearPreview(); clearData(); clearFiles(); showFiles.hidden = true; showData.hidden = true; dataHint.hidden = true;
      return false;
    } finally { busy = false; refresh.disabled = false; schedule(); }
  }
  download.addEventListener('click', async event => {
    event.preventDefault(); if (await load(true) && row.state === 'succeeded') {
      const anchor = el('a', {href:contentUrl, download:''}); anchor.click();
    }
  });
  function clearPreview() {
    ++previewRequest; previewObserver?.disconnect(); previewObserver = null;
    previewArea.replaceChildren(); previewArea.hidden = true;
    preview.textContent = 'Preview HTML'; preview.setAttribute('aria-expanded', 'false');
  }
  async function showPreview() {
    if (!previewArea.hidden) { clearPreview(); return; }
    if (!await load(true) || row.state !== 'succeeded' || row.output !== 'html') return;
    clearPreview(); const request = previewRequest; preview.disabled = true;
    try {
      let dimensions = null;
      try { dimensions = (await api(`/v1/templates/${encodeURIComponent(row.template_id)}/versions/${row.template_version}`, {}, ctx.controller.signal)).page_dimensions_mm; }
      catch { /* The original-size preview still works if metadata is unavailable. */ }
      if (!ctx.active || request !== previewRequest) return;
      // Render at the report's page width, leaving room for its vertical scrollbar.
      const width = dimensions ? Math.ceil(dimensions[0] * 96 / 25.4) + 24 : null;
      const scale = select(width ? [['fit', 'Fit width'], ['1', '100%']] : [['1', '100%']], width ? 'fit' : '1');
      scale.disabled = !width;
      const frame = el('iframe', {class:'preview-frame', title:'Report preview', sandbox:'allow-scripts', src:contentUrl + '?disposition=inline'});
      const canvas = el('div', {class:'preview-canvas'}, frame);
      const viewport = el('div', {class:'preview-viewport'}, canvas);
      previewArea.hidden = false;
      preview.textContent = 'Hide preview'; preview.setAttribute('aria-expanded', 'true');
      previewArea.replaceChildren(el('h2', {}, 'HTML preview'),
        el('p', {class:'muted'}, 'Scale changes the view, not the report layout. HTML may differ from checked PDF output. If an expiry error appears here, refresh the report status.'),
        el('div', {class:'toolbar'}, field('Preview scale', scale)),
        width ? '' : el('p', {class:'muted'}, 'Automatic scaling is unavailable. Showing the original layout with scrolling.'), viewport);
      function resize() {
        const naturalWidth = width || viewport.clientWidth;
        const factor = scale.value === 'fit' ? Math.min(1, viewport.clientWidth / naturalWidth) : 1;
        if (!factor) return;
        viewport.style.overflow = scale.value === 'fit' ? 'hidden' : 'auto';
        canvas.style.width = `${naturalWidth * factor}px`; canvas.style.height = `${viewport.clientHeight}px`;
        frame.style.width = `${naturalWidth}px`; frame.style.height = `${viewport.clientHeight / factor}px`;
        frame.style.transform = `scale(${factor})`;
      }
      scale.addEventListener('change', resize);
      previewObserver = new ResizeObserver(resize); previewObserver.observe(viewport); resize();
    } catch (error) {
      if (ctx.active && request === previewRequest) message(status, `Preview could not be opened. ${error.message}`, 'error');
    } finally { preview.disabled = false; }
  }
  function clearFiles() {
    ++filesRequest; filesArea.replaceChildren(); filesArea.hidden = true;
    showFiles.textContent = 'Show input files'; showFiles.setAttribute('aria-expanded', 'false');
  }
  async function toggleFiles() {
    if (!filesArea.hidden) { clearFiles(); return; }
    if (!await load(true) || !row.inputs_available) return;
    const token = ++filesRequest;
    filesArea.hidden = false; showFiles.textContent = 'Hide input files'; showFiles.setAttribute('aria-expanded', 'true');
    const fileStatus = notice(); message(fileStatus, 'Loading original input files…');
    const base = `/v1/reports/${encodeURIComponent(id)}`;
    filesArea.replaceChildren(el('h2', {}, 'Original input files'), fileStatus);
    try {
      const catalog = await api(base + '/files', {}, ctx.controller.signal);
      if (!ctx.active || token !== filesRequest) return;
      filesArea.append(el('p', {class:'muted'}, 'Exact uploaded bytes, before conversion. Parsed means the file was decoded; the report can still fail during binding or rendering. Skipped means not attempted. Unknown means no completed parse diagnostics are available.'),
        el('div', {class:'actions'}, el('a', {href:base + '/inputs.zip', class:'button'}, 'Download investigation ZIP'), el('a', {href:base + '/input', class:'button'}, 'Download original request')));
      if (catalog.structure === 'invalid') { message(fileStatus, 'The upload structure is invalid. Download the original request to investigate.', 'error'); return; }
      const table = el('table', {}, el('thead', {}, el('tr', {}, ...['File', 'Size', 'Parsing', 'Datasets', 'Download'].map(title => el('th', {}, title)))),
        el('tbody', {}, ...catalog.files.map(file => el('tr', {}, el('td', {}, file.name, el('div', {class:'muted mono'}, `SHA-256: ${file.sha256}`)), el('td', {}, `${file.size} bytes`), el('td', {}, file.status, file.error ? ` (${file.error})` : ''), el('td', {}, file.datasets.join(', ') || '—'), el('td', {}, el('a', {href:`${base}/files/${file.id}/content`}, 'Download original'))))));
      filesArea.append(el('div', {class:'table-wrap'}, table));
      if (catalog.fields.length) filesArea.append(el('h3', {}, 'Submitted CSV options'), el('pre', {}, JSON.stringify(catalog.fields, null, 2)));
      message(fileStatus, catalog.files.length ? '' : 'No file parts were found.');
    } catch (error) { if (ctx.active && token === filesRequest) message(fileStatus, error.message, 'error'); }
  }
  function clearData() {
    ++dataRequest; dataArea.replaceChildren(); dataArea.hidden = true;
    showData.textContent = 'Show data'; showData.setAttribute('aria-expanded', 'false');
  }
  async function toggleData() {
    if (!dataArea.hidden) { clearData(); return; }
    if (!await load(true) || !row.data_available) return;
    const token = ++dataRequest;
    dataArea.hidden = false; showData.textContent = 'Hide data'; showData.setAttribute('aria-expanded', 'true');
    const dataStatus = notice(); message(dataStatus, 'Loading report data…');
    const base = `/v1/reports/${encodeURIComponent(id)}`;
    dataArea.replaceChildren(el('h2', {}, 'Report data'), dataStatus);
    try {
      const catalog = await api(base + '/datasets', {}, ctx.controller.signal);
      if (!ctx.active || token !== dataRequest) return;
      const choice = select(catalog.items.map(item => [item.name, `${item.name} (${item.row_count} rows)`]));
      let offset = 0, pageRequest = 0;
      const dataDownload = el('a', {href:base + '/data', class:'button'}, 'Download data JSON');
      dataDownload.addEventListener('click', async event => {
        event.preventDefault();
        if (await load(true) && row.data_available) el('a', {href:base + '/data', download:''}).click();
      });
      const retry = button('Retry rows', () => loadPage()); retry.hidden = true;
      const table = el('table'), range = el('span', {class:'muted'});
      const previous = button('Previous rows', () => { offset = Math.max(0, offset - 100); loadPage(); });
      const next = button('Next rows', () => { offset += 100; loadPage(); });
      dataArea.append(el('p', {class:'muted'}, 'Immutable input datasets used for this report. Values are shown exactly; null is displayed as ∅.'),
        el('div', {class:'toolbar'}, field('Dataset', choice), dataDownload),
        el('div', {class:'table-wrap data-table'}, table), el('div', {class:'actions'}, previous, range, next, retry));
      async function loadPage() {
        const request = ++pageRequest; previous.disabled = true; next.disabled = true; retry.hidden = true;
        table.replaceChildren(); message(dataStatus, 'Loading dataset…');
        try {
          const data = await api(query(base + '/dataset', {name:choice.value, offset, limit:100}), {}, ctx.controller.signal);
          if (!ctx.active || token !== dataRequest || request !== pageRequest) return;
          table.replaceChildren(el('thead', {}, el('tr', {}, ...data.columns.map(column => el('th', {}, column)))),
            el('tbody', {}, ...data.rows.map(row => el('tr', {}, ...row.map(cell => el('td', {class:cell === null ? 'muted' : ''}, cell === null ? '∅' : cell))))));
          range.textContent = data.row_count ? `${data.offset + 1}–${data.offset + data.rows.length} of ${data.row_count}` : '0 rows';
          previous.disabled = data.offset === 0; next.disabled = data.offset + data.rows.length >= data.row_count;
          message(dataStatus, '');
        } catch (error) {
          if (ctx.active && token === dataRequest && request === pageRequest) {
            message(dataStatus, error.message, 'error'); retry.hidden = false;
          }
        }
      }
      choice.addEventListener('change', () => { offset = 0; loadPage(); });
      if (catalog.items.length) await loadPage();
      else { message(dataStatus, 'No datasets.'); previous.disabled = true; next.disabled = true; }
    } catch (error) {
      if (ctx.active && token === dataRequest) message(dataStatus, error.message, 'error');
    }
  }
  ctx.cleanup.push(clearFiles);
  ctx.cleanup.push(clearData);
  ctx.cleanup.push(clearPreview);
  const visibility = () => { clearTimeout(timer); if (!document.hidden) load(); };
  document.addEventListener('visibilitychange', visibility);
  ctx.cleanup.push(() => { clearTimeout(timer); document.removeEventListener('visibilitychange', visibility); });
  await load();
}
