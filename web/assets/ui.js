const paths = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  nodes: '<rect x="3" y="3" width="18" height="6" rx="2"/><rect x="3" y="15" width="18" height="6" rx="2"/><path d="M7 6h.01M7 18h.01M12 9v6"/>',
  route: '<circle cx="5" cy="6" r="2"/><circle cx="19" cy="18" r="2"/><path d="M7 6h9a4 4 0 0 1 0 8H8a4 4 0 0 0 0 8M19 3v5m-2-2h4"/>',
  link: '<path d="m10 13 4-4m-5 7-2 2a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2-1 2-2a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0"/>',
  tasks: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2h6v2M9 10h6M9 15h6"/>',
  settings: '<path d="M4 7h16M4 17h16"/><circle cx="8" cy="7" r="3"/><circle cx="16" cy="17" r="3"/>',
  pool: '<path d="m3 7 9-4 9 4-9 4-9-4Zm0 5 9 4 9-4M3 17l9 4 9-4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
  logout: '<path d="M9 4H4v16h5M9 12h12m-4-4 4 4-4 4"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  copy: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
  edit: '<path d="m16 3 5 5-12 12-6 1 1-6L16 3ZM13 6l5 5"/>',
  trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 13 3M18 18a8 8 0 0 1-13-3"/>',
};
export function icon(name, cls = '') {
  return `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.info}</svg>`;
}
export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}
export function date(value) {
  if (!value) return '尚无记录';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '时间未知' : parsed.toLocaleString('zh-CN', {hour12: false});
}
export function status(value) {
  const map = {new:['待检测','neutral'],unknown:['未验证','neutral'],healthy:['健康','good'],failed:['检测失败','bad'],unhealthy:['不健康','bad'],disabled:['已禁用','neutral'],configured:['已配置 · 未执行','neutral'],unprovisioned:['未部署','neutral'],running:['运行中','good'],pending:['等待中','neutral'],completed:['已完成','good'],success:['成功','good'],error:['失败','bad']};
  Object.assign(map, {queued:['排队中','neutral'],checking:['检测中','neutral'],blocked:['已阻止','bad'],expired:['已过期','neutral'],succeeded:['已完成','good'],cancelled:['已取消','neutral'],abandoned:['已中止','neutral'],passed:['检查通过','good'],timeout:['超时','bad']});
  const [label, cls] = map[value] || [value || '未知','neutral'];
  return `<span class="status ${cls}"><i></i>${esc(label)}</span>`;
}
export function toast(message, type = 'success') {
  const node = document.createElement('div');
  node.className = `toast ${type}`;
  node.setAttribute('role', type === 'error' ? 'alert' : 'status');
  const label = document.createElement('span');
  label.textContent = message;
  node.innerHTML = icon(type === 'error' ? 'info' : 'check');
  node.append(label);
  document.querySelector('#toasts').append(node);
  setTimeout(() => node.remove(), type === 'error' ? 8000 : 4200);
}
export function heading(kicker, title, description, actions = '') {
  return `<div class="page-heading"><div><div class="kicker">${esc(kicker)}</div><h1>${esc(title)}</h1><p>${esc(description)}</p></div><div class="heading-actions">${actions}</div></div>`;
}
export function empty(title, text, action = '', image = 'nodes') {
  return `<div class="empty"><div class="empty-symbol">${icon(image)}</div><h3>${esc(title)}</h3><p>${esc(text)}</p>${action}</div>`;
}
export function notice(text, tone = '') {
  return `<div class="notice ${tone}">${icon('info')}<div>${esc(text)}</div></div>`;
}
export function loading(root) {
  root.innerHTML = '<div class="page-loading" role="status"><span class="spinner"></span>正在读取真实数据…</div>';
}
export function pageError(root, error, retry) {
  root.innerHTML = `<div class="error-panel">${icon('info')}<h2>暂时无法读取数据</h2><p>${esc(error.message)}</p><button class="btn" data-retry>重新请求</button></div>`;
  root.querySelector('[data-retry]').addEventListener('click', retry);
}
export function formError(form, message) {
  const target = form.querySelector('.form-error');
  if (target) { target.textContent = message; target.hidden = false; target.scrollIntoView({block:'nearest'}); }
}
export function busy(button, active, label = '正在保存…') {
  if (active) {
    button.dataset.originalHtml = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<span class="spinner"></span>${esc(label)}`;
  } else {
    button.disabled = false;
    button.innerHTML = button.dataset.originalHtml || button.innerHTML;
  }
}
let closeCurrent = null;
export function closeModal() { closeCurrent?.(); }
export function modal(title, subtitle, content, {wide = false} = {}) {
  closeModal();
  const previousFocus = document.activeElement;
  const overlay = document.createElement('div');
  overlay.className = 'modal-backdrop';
  overlay.innerHTML = `<section class="modal ${wide ? 'wide' : ''}" role="dialog" aria-modal="true" aria-labelledby="modal-title" tabindex="-1"><header class="modal-head"><div><div class="kicker">CONFIGURATION</div><h2 id="modal-title">${esc(title)}</h2><p>${esc(subtitle)}</p></div><button class="icon-btn" data-close aria-label="关闭对话框">${icon('close')}</button></header><div class="modal-content">${content}</div></section>`;
  const panel = overlay.querySelector('.modal');
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    overlay.remove();
    document.removeEventListener('keydown', keydown);
    if (closeCurrent === close) {
      document.body.classList.remove('modal-open');
      if (previousFocus?.isConnected) previousFocus.focus();
      closeCurrent = null;
    }
  };
  const keydown = event => {
    if (event.key === 'Escape' && !panel.querySelector('[data-submitting="true"]')) close();
    if (event.key !== 'Tab') return;
    const items = [...panel.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]')].filter(el => !el.hidden && el.offsetParent !== null);
    if (!items.length) { event.preventDefault(); panel.focus(); return; }
    if (event.shiftKey && (document.activeElement === items[0] || document.activeElement === panel)) { event.preventDefault(); items.at(-1).focus(); }
    if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0].focus(); }
  };
  overlay.addEventListener('click', event => {
    if ((event.target === overlay || event.target.closest('[data-close]')) && !panel.querySelector('[data-submitting="true"]')) close();
  });
  document.addEventListener('keydown', keydown);
  document.querySelector('#modal-root').append(overlay);
  document.body.classList.add('modal-open');
  closeCurrent = close;
  requestAnimationFrame(() => (panel.querySelector('input:not([type="checkbox"]),select,textarea') || panel).focus());
  return {panel, close};
}
export function confirmAction({title, text, label = '确认删除', action}) {
  const dialog = modal(title, '此操作需要管理员确认', `<p class="confirm-text">${esc(text)}</p><div class="form-error" role="alert" hidden></div><div class="form-actions"><button class="btn" data-close>取消</button><button class="btn danger" data-confirm>${esc(label)}</button></div>`);
  const button = dialog.panel.querySelector('[data-confirm]');
  button.addEventListener('click', async () => {
    if (button.disabled) return;
    busy(button, true, '正在提交…'); button.dataset.submitting = 'true';
    try { await action(); dialog.close(); } catch (error) { formError(dialog.panel, error.message); }
    finally { busy(button, false); delete button.dataset.submitting; }
  });
}
export async function copyText(text, source) {
  try {
    if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); toast('已复制，请仅分享给受信任的使用者'); return; }
  } catch { /* fall back to local selection */ }
  const textarea = document.createElement('textarea');
  textarea.value = text; textarea.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
  document.body.append(textarea); textarea.select();
  let copied = false;
  try { copied = document.execCommand('copy'); } catch { /* manual selection below */ }
  textarea.remove();
  if (copied) toast('已复制，请仅分享给受信任的使用者');
  else { source?.focus(); source?.select?.(); toast('自动复制不可用。已选中内容，请使用系统复制快捷键', 'error'); }
}
export function toggleButton(enabled, attrs = '') {
  return `<button type="button" class="toggle ${enabled ? 'on' : ''}" role="switch" aria-checked="${Boolean(enabled)}" aria-label="${enabled ? '禁用此配置' : '启用此配置'}" ${attrs}><span></span></button>`;
}
