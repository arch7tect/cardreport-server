import {el, details} from './common.js';

const reasons = {
  content_overflow: ['Content exceeds its allocated area', 'Give this block more space, reduce its content or move it to another page.'],
  page_overflow: ['Content exceeds the page area', 'Move a block to another page or reduce the space used by other blocks. For long tables, consider Chromium with flow mode.'],
  label_outside: ['A chart label exceeds its allocated area', 'Give the chart more space. If value labels are optional, disable them; axis and legend labels are checked separately.'],
  label_overlap: ['Chart labels overlap', 'Widen the chart, use a full-width row or disable optional value labels. The required size has not been measured.'],
  insufficient_space: ['Too little space for the chart', 'Give the chart more width or height, including room for axes and legends.'],
  fragmented: ['An indivisible block crossed a page boundary', 'Move the block to a separate page or use Chromium flow mode for a long top-level table.'],
  page_limit: ['The report exceeds the page limit', 'Reduce the report or review its page limit.'],
  missing_content: ['Content is missing from the measured layout', 'Review the block layout and renderer capabilities.'],
  layout_overflow: ['The layout does not fit', 'Review the indicated block and its available space.'],
};
const finite = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const mm = value => `${value > 0 && value < 0.1 ? 'less than 0.1' : value.toFixed(1)} mm`;

export function renderLayoutDiagnostic(root, diagnostic) {
  root.replaceChildren();
  if (!diagnostic || typeof diagnostic !== 'object' || typeof diagnostic.path !== 'string') return;
  const [title, hint] = Object.hasOwn(reasons, diagnostic.reason) ? reasons[diagnostic.reason] : reasons.layout_overflow;
  const facts = [['Component path', el('code', {}, diagnostic.path)]];
  if (Number.isInteger(diagnostic.page) && diagnostic.page > 0) facts.push(['Page', String(diagnostic.page)]);
  if (finite(diagnostic.available_width_mm)) facts.push(['Available width', mm(diagnostic.available_width_mm)]);
  if (finite(diagnostic.available_height_mm)) facts.push(['Available height', mm(diagnostic.available_height_mm)]);
  const boxes = {content:'Content area', padding:'Content and padding area', border:'Outer border area', viewport:'Chart viewport'};
  if (boxes[diagnostic.box]) facts.push(['Measured area', boxes[diagnostic.box]]);
  const measured = [], excess = [];
  for (const side of ['left','top','right','bottom']) {
    const value = diagnostic[`overflow_${side}_mm`];
    if (!finite(value)) continue;
    measured.push(side);
    if (value > 0) excess.push(`${side}: ${mm(value)}`);
  }
  root.append(el('section', {class:'panel layout-diagnostic', 'aria-label':'Layout diagnostics'},
    el('h2', {}, title), details(facts),
    excess.length ? el('p', {}, el('strong', {}, 'Overflow — '), excess.join(' · ')) : null,
    measured.length ? el('p', {class:'muted'}, `Measured sides: ${measured.join(', ')}.${measured.length < 4 ? ' Other sides were not measured.' : ''}`) : el('p', {class:'muted'}, 'No overflow measurement is available for this check.'),
    el('p', {}, hint),
    el('p', {class:'muted'}, 'Measurements describe the current layout, not the space guaranteed to fix it. Resizing can change line wrapping and move other blocks.')));
}
