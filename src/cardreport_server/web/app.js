import {api, el, heading, button, notice, message, details, date} from './common.js';
import {templates, templateDetail, templateEditor} from './templates.js';
import {newReport} from './submit.js';
import {reports, reportDetail} from './reports.js';

const main = document.querySelector('main');
let current = null;
let acceptedHash = '';
async function route() {
  const hash = location.hash.startsWith('#/') ? location.hash : '#/templates';
  if (current?.dirty && !confirm('Leave this page and discard the unsaved draft?')) {
    history.replaceState(null, '', acceptedHash); return;
  }
  if (current) { current.active = false; current.controller.abort(); current.cleanup.forEach(fn => fn()); }
  const context = {active: true, dirty: false, controller: new AbortController(), cleanup: []};
  context.go = path => { context.dirty = false; location.hash = path; };
  current = context; acceptedHash = hash;
  main.replaceChildren(el('p', {class: 'muted'}, 'Loading…'));
  const [path, search = ''] = hash.slice(1).split('?');
  let parts;
  try { parts = path.split('/').filter(Boolean).map(decodeURIComponent); }
  catch { main.replaceChildren(heading('Invalid address', 'Choose a page from the navigation.')); return; }
  document.querySelectorAll('[data-nav]').forEach(a => {
    if (a.dataset.nav === (parts[0] === 'create-template' ? 'templates' : parts[0])) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  try {
    if (parts[0] === 'create-template') await templateEditor(main, context);
    else if (parts[0] === 'templates' && parts[2] === 'edit') await templateEditor(main, context, parts[1], new URLSearchParams(search).get('version'));
    else if (parts[0] === 'templates' && parts[1]) await templateDetail(main, context, parts[1], new URLSearchParams(search).get('version'));
    else if (parts[0] === 'templates') await templates(main, context);
    else if (parts[0] === 'new-report') await newReport(main, context, new URLSearchParams(search));
    else if (parts[0] === 'reports' && parts[1]) await reportDetail(main, context, parts[1], new URLSearchParams(search));
    else if (parts[0] === 'reports') await reports(main, context);
    else if (parts[0] === 'status') await serviceStatus(main, context);
    else main.replaceChildren(heading('Page not found', 'Choose a page from the navigation.'));
    if (context.active) main.focus({preventScroll: true});
  } catch (error) {
    if (!context.active) return;
    const status = notice(); main.replaceChildren(heading('Unable to load this page', 'Your server may be unavailable.'), status, button('Try again', route));
    message(status, error.message || 'Connection failed.', 'error');
  }
}
async function serviceStatus(root, ctx) {
  const status = notice(), checks = el('div', {class: 'panel'});
  const refresh = button('Refresh status', load);
  root.replaceChildren(heading('Service status', 'API checks only. This does not confirm worker health or report success.'), status, checks, refresh);
  async function load() {
    refresh.disabled = true; message(status, 'Checking…');
    const result = await Promise.allSettled(['/health/live', '/health/ready'].map(path => api(path, {}, ctx.controller.signal)));
    if (!ctx.active) return;
    checks.replaceChildren(details([['API process', result[0].status === 'fulfilled' ? 'Available' : 'Unavailable'], ['Database and storage', result[1].status === 'fulfilled' ? 'Ready' : 'Unavailable'], ['Checked at', date(new Date().toISOString())]]));
    message(status, 'Checks complete.'); refresh.disabled = false;
  }
  await load();
}
document.querySelector('.skip').addEventListener('click', event => { event.preventDefault(); main.focus(); });
window.addEventListener('hashchange', route);
window.addEventListener('beforeunload', event => { if (current?.dirty) {event.preventDefault(); event.returnValue = ''; } });
route();
