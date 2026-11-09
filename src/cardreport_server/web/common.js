export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'class') node.className = value;
    else if (key in node && !key.startsWith('aria')) node[key] = value;
    else node.setAttribute(key, value);
  }
  node.append(...children.flat().filter(x => x !== null && x !== undefined));
  return node;
}
let fieldId = 0;
export function field(label, control, help = '') {
  control.id ||= `field-${++fieldId}`;
  return el('div', {class: 'field'}, el('label', {htmlFor: control.id}, label), control,
    help ? el('small', {}, help) : null);
}
export function button(label, onClick, primary = false) {
  return el('button', {type: 'button', class: primary ? 'primary' : '', onclick: onClick}, label);
}
export function link(label, href, primary = false) {
  return el('a', {href, class: primary ? 'button primary' : ''}, label);
}
export function heading(title, subtitle, action = null) {
  return el('div', {class: 'page-heading'}, el('div', {}, el('p', {class: 'eyebrow'}, 'REPORT WORKSPACE'),
    el('h1', {}, title), el('p', {class: 'subtitle'}, subtitle)), action);
}
export function notice() { return el('div', {class: 'notice', role: 'status', tabIndex: -1}); }
export function message(node, text, kind = '', focus = true) {
  node.className = `notice ${kind}`;
  node.textContent = text;
  if (kind === 'error' && focus) node.focus();
}
export function badge(state, terminal = null) {
  return el('span', {class: `badge ${state}`}, terminal && state === 'expired' ? `Expired · ${terminal}` : state[0].toUpperCase() + state.slice(1));
}
export function date(value) {
  if (!value) return '—';
  return new Intl.DateTimeFormat(undefined, {dateStyle: 'medium', timeStyle: 'short'}).format(new Date(value)) +
    ` (${Intl.DateTimeFormat().resolvedOptions().timeZone})`;
}
export function duration(seconds) {
  if (!Number.isInteger(seconds) || seconds < 1) return '—';
  const parts = [];
  for (const [size, unit] of [[86400, 'day'], [3600, 'hour'], [60, 'minute'], [1, 'second']]) {
    const count = Math.floor(seconds / size); seconds %= size;
    if (count) parts.push(`${count} ${unit}${count === 1 ? '' : 's'}`);
  }
  return parts.join(' ');
}
export function details(entries) {
  return el('dl', {class: 'key-values'}, ...entries.flatMap(([key, value]) => [el('dt', {}, key), el('dd', {}, value ?? '—')]));
}
export function select(options, value = '') {
  const node = el('select', {}, ...options.map(([id, label]) => el('option', {value: id}, label)));
  if (value !== '') node.value = value;
  return node;
}
export function formatFor(name) { return /\.ya?ml$/i.test(name) ? 'application/yaml' : 'application/json'; }
export const formats = [['application/json', 'JSON'], ['application/yaml', 'YAML']];
export function saveText(name, text) {
  const url = URL.createObjectURL(new Blob([text], {type: 'application/json'}));
  const anchor = el('a', {href: url, download: name}); anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export async function copy(text, status) {
  try { await navigator.clipboard.writeText(text); message(status, 'Copied.', 'success'); }
  catch { message(status, 'Clipboard access is unavailable. Select and copy the displayed text.', 'error'); }
}
export class APIError extends Error {
  constructor(status, body, retryAfter = 0) {
    const error = body?.error ?? {};
    super(`${error.message || 'Request failed'}${error.code ? ` (${error.code})` : ''}${error.template_path ? ` · ${error.template_path}` : ''}`);
    this.status = status; this.retryAfter = retryAfter;
  }
}
export async function api(path, options = {}, signal = undefined) {
  const method = options.method || 'GET';
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener('abort', abort, {once: true});
  const timeout = method === 'GET' ? setTimeout(abort, 15000) : null;
  try {
    const response = await fetch(path, {...options, signal: controller.signal, cache: 'no-store'});
    const text = await response.text();
    let body;
    try { body = text ? JSON.parse(text) : {}; } catch { body = {}; }
    if (!response.ok) {
      const retry = response.headers.get('Retry-After');
      const seconds = retry && /^\d+$/.test(retry) ? Number(retry) : Math.max(0, (Date.parse(retry) - Date.now()) / 1000) || 0;
      throw new APIError(response.status, body, seconds);
    }
    return body;
  } finally {
    clearTimeout(timeout); signal?.removeEventListener('abort', abort);
  }
}
export function mutationError(error) {
  const uncertain = !(error instanceof APIError) || error.status >= 500 || error.status === 408;
  return uncertain ? 'Acceptance is uncertain. The server may have saved your request. Check history or versions before deliberately submitting again. Your draft is preserved.' : error.message;
}
export function query(path, params) {
  const values = new URLSearchParams(Object.entries(params).filter(([,value]) => value !== null && value !== undefined && value !== ''));
  return path + (values.size ? `?${values}` : '');
}
