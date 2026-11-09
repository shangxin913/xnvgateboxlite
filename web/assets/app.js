import {api, setSession, getSession} from './api.js';
import {icon, esc, busy, formError, toast, closeModal, pageError} from './ui.js';
import {dashboardPage, tasksPage, settingsPage, poolPage} from './pages.js';
import {nodesPage} from './nodes.js';
import {egressesPage} from './egresses.js';
import {subscriptionsPage, clearReceipts} from './subscriptions.js';

const routes = {
  '/': {title:'总览', kicker:'OVERVIEW', icon:'grid', page:dashboardPage},
  '/nodes': {title:'节点管理', kicker:'NODES', icon:'nodes', page:nodesPage},
  '/egresses': {title:'出口配置', kicker:'EGRESSES', icon:'route', page:egressesPage},
  '/subscriptions': {title:'私密订阅', kicker:'SUBSCRIPTIONS', icon:'link', page:subscriptionsPage},
  '/pool': {title:'候选池', kicker:'CANDIDATE POOL', icon:'pool', page:poolPage},
  '/tasks': {title:'任务与计划', kicker:'JOBS & SCHEDULES', icon:'tasks', page:tasksPage},
  '/settings': {title:'系统设置', kicker:'SETTINGS', icon:'settings', page:settingsPage},
};
const app = document.querySelector('#app');
let returnPath = '/';
let passwordMode = false;
let renderSequence = 0;
let navigating = false;

function navigate(path, replace = false) {
  const url = new URL(path, location.origin);
  if (url.origin !== location.origin) return;
  const target = url.pathname + url.search;
  if (replace) history.replaceState({}, '', target);
  else if (location.pathname + location.search !== target) history.pushState({}, '', target);
  render();
}
function clearAuth() {
  setSession(null); passwordMode = false; clearReceipts(); closeModal();
}
async function logout() {
  if (navigating) return;
  navigating = true;
  const button = app.querySelector('[data-logout]');
  if (button) busy(button, true, '退出中');
  try {
    await api('/api/auth/logout', {method:'POST'});
    clearAuth(); toast('已安全退出'); navigate('/login', true);
  } catch (error) { toast(error.message, 'error'); }
  finally { navigating = false; if (button?.isConnected) busy(button, false); }
}
function requestPassword() {
  returnPath = location.pathname in routes ? location.pathname : '/';
  passwordMode = true;
  navigate('/login');
}
function shell(route) {
  const user = getSession().user;
  const link = (path, value) => `<a class="nav-link ${location.pathname === path ? 'active' : ''}" href="${path}" data-nav ${location.pathname === path ? 'aria-current="page"' : ''}>${icon(value.icon)}<span>${value.title}</span></a>`;
  app.innerHTML = `<div class="shell"><aside class="sidebar"><a class="brand" href="/" data-nav aria-label="GateBox 总览"><img src="/assets/logo.svg" alt=""><div><div class="brand-word">GATEBOX</div><div class="brand-sub">LITE / NETWORK CONSOLE</div></div></a><div class="nav-group-label">WORKSPACE / 工作空间</div><nav class="nav" aria-label="主要导航">${['/','/nodes','/egresses','/subscriptions'].map(path => link(path,routes[path])).join('')}</nav><div class="nav-group-label">OPERATIONS / 运行管理</div><nav class="nav" aria-label="运行管理导航">${['/pool','/tasks','/settings'].map(path => link(path,routes[path])).join('')}</nav><div class="sidebar-bottom"><div class="sidebar-signal"><span class="signal-dot"></span>配置工作台 · 第一阶段</div><p>配置透明，执行边界清晰。<br>只呈现真实资源与检查结果。</p><div class="sidebar-version"><span>SELF-HOSTED</span><span>V0.1.0</span></div></div></aside><div class="mobile-overlay" data-menu-close></div><div class="workspace"><header class="topbar"><div class="breadcrumb"><button class="icon-btn menu-btn" data-menu aria-label="打开导航菜单" aria-expanded="false">${icon('menu')}</button><span>工作空间</span>${icon('chevron')}<span>${esc(route?.title || '页面未找到')}</span></div><div class="top-right"><div class="session-status"><span class="signal-dot"></span>会话已验证</div><button class="account icon-btn" data-password title="修改管理员密码"><span class="avatar">${esc(user.username.slice(0,2).toUpperCase())}</span><span class="username">${esc(user.username)}</span></button><button class="icon-btn" data-logout title="安全退出" aria-label="安全退出">${icon('logout')}</button></div></header><main id="page" class="content" tabindex="-1"></main><footer class="site-footer"><span>GATEBOX LITE · 配置状态不代表链路可用</span><span>PRIVATE NETWORK WORKSPACE</span></footer></div></div>`;
  const shellNode = app.querySelector('.shell');
  const menuButton = app.querySelector('[data-menu]');
  menuButton.addEventListener('click', () => {
    const open = shellNode.classList.toggle('menu-open'); menuButton.setAttribute('aria-expanded',String(open));
  });
  app.querySelector('[data-menu-close]').addEventListener('click', () => {shellNode.classList.remove('menu-open');menuButton.setAttribute('aria-expanded','false');});
  app.querySelector('[data-logout]').addEventListener('click',logout);
  app.querySelector('[data-password]').addEventListener('click',requestPassword);
  return app.querySelector('#page');
}
function loginPage() {
  const currentSession = getSession();
  const change = Boolean(currentSession && (passwordMode || currentSession.user.must_change_password));
  const forced = Boolean(currentSession?.user.must_change_password);
  document.title = `${change ? '修改密码' : '安全登录'} · GateBox`;
  app.innerHTML = `<div class="login-layout"><section class="login-brand"><a class="brand" href="${currentSession ? '/' : '/login'}" data-nav aria-label="GateBox"><img src="/assets/logo.svg" alt=""><div><div class="brand-word">GATEBOX</div><div class="brand-sub">LITE / NETWORK CONSOLE</div></div></a><div class="login-main-copy"><div class="kicker">YOUR NETWORK. YOUR CONTROL.</div><h1>让每一条出口，<br>都有<em>清晰的边界。</em></h1><p>为自有 VPS 构建轻量网络配置工作台。<br>保存可信节点，管理私密订阅，不掩盖执行状态。</p><div class="login-boundaries"><div>${icon('nodes')}真实节点配置，不预置演示资源</div><div>${icon('lock')}独立管理员 · Cookie 会话 · CSRF 保护</div><div>${icon('route')}默认出口仅配置，不修改系统路由</div></div></div><div class="login-brand-bottom"><span>SELF-HOSTED / FIRST PHASE</span><span>CONFIGURE WITH CONFIDENCE</span></div></section><section class="login-side"><div class="login-topnote">${icon('shield')}管理员专属工作空间</div><div class="login-box"><div class="kicker">${change ? 'PASSWORD / SECURITY' : 'AUTHENTICATION / 01'}</div><h2>${change ? forced ? '设置你的新密码' : '修改管理员密码' : '安全登录'}</h2><p>${change ? forced ? '初始密码仅用于首次验证。请设置新的独立密码，完成后所有旧会话将撤销，需要重新登录。' : '修改密码会撤销全部会话。请准备好当前密码，并将新密码保存在可信的密码管理器中。' : '使用初始化时创建的真实管理员账号。初始密码由部署管理员私密提供，不在页面中保存。'}</p><form id="auth-form">${change ? `<div class="field"><label for="current-password">当前密码</label><input id="current-password" name="current_password" type="password" autocomplete="current-password" required maxlength="128" placeholder="输入当前管理员密码"></div><div class="field"><label for="new-password">新密码 <small>12–128 个字符</small></label><input id="new-password" name="new_password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required placeholder="建议使用随机且唯一的长密码"><div class="password-strength" aria-hidden="true"><span></span><span></span><span></span><span></span></div></div><div class="field"><label for="confirm-password">确认新密码</label><input id="confirm-password" name="confirm_password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required placeholder="再次输入新密码"></div>` : `<div class="field"><label for="login-username">管理员账号</label><input id="login-username" name="username" autocomplete="username" required maxlength="128" placeholder="输入管理员账号" autofocus></div><div class="field"><label for="login-password">密码</label><input id="login-password" name="password" type="password" autocomplete="current-password" required maxlength="128" placeholder="输入管理员密码"></div>`}<div class="form-error" role="alert" hidden></div><button class="btn dark" type="submit">${change ? '保存新密码并重新登录' : '进入控制台'}${icon('arrow')}</button>${change ? `<button type="button" class="btn" data-auth-back>${forced ? '退出当前会话' : '取消，返回控制台'}</button>` : ''}</form><div class="notice">${icon('info')}<div>${change ? '不要重复使用初始密码或其他服务的密码。密码仅通过同源 API 提交。' : '仅供可信管理员访问。执行器、VPN Gate 抓取与链路检测尚未接入，不宣称代理服务已运行。'}</div></div><div class="login-box-bottom"><span>GATEBOX LITE V0.1.0</span><span>PRIVATE BY DESIGN</span></div></div></section></div>`;
  const form = app.querySelector('#auth-form');
  const submit = form.querySelector('[type="submit"]');
  if (change) {
    form.querySelector('[name="new_password"]').addEventListener('input', event => {
      const value = event.target.value;
      const count = value.length < 12 ? value.length > 0 ? 1 : 0 : value.length < 20 ? 2 : value.length < 32 ? 3 : 4;
      form.querySelectorAll('.password-strength span').forEach((el,index) => el.classList.toggle('on',index < count));
    });
    form.querySelector('[data-auth-back]').addEventListener('click', () => {
      if (forced) logout(); else {passwordMode = false; navigate(returnPath in routes ? returnPath : '/',true);}
    });
  }
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (submit.disabled) return;
    form.querySelector('.form-error').hidden = true;
    const data = new FormData(form);
    if (change && data.get('new_password') !== data.get('confirm_password')) {formError(form,'两次输入的新密码不一致');return;}
    if (change && data.get('new_password') === data.get('current_password')) {formError(form,'新密码不能与当前密码相同');return;}
    busy(submit,true,change ? '正在更新密码…' : '正在验证会话…');
    try {
      if (change) {
        await api('/api/auth/password',{method:'POST',body:{current_password:data.get('current_password'),new_password:data.get('new_password')}});
        form.reset(); clearAuth(); toast('密码已修改，所有旧会话已撤销。请使用新密码登录'); navigate('/login',true);
      } else {
        const session = await api('/api/auth/login',{method:'POST',body:{username:data.get('username'),password:data.get('password')}});
        setSession(session); form.reset();
        // Confirm the browser really accepted the HttpOnly session cookie before entering the console.
        try {setSession(await api('/api/auth/me'));}
        catch (error) {clearAuth(); throw new Error(error.status === 401 ? '浏览器未保留会话 Cookie。请在独立 HTTPS 标签页打开，并检查浏览器 Cookie 策略或服务器配置。' : error.message);}
        if (getSession().user.must_change_password) {passwordMode = true;render();}
        else {toast('管理员身份已验证');navigate(returnPath in routes ? returnPath : '/',true);}
      }
    } catch (error) {formError(form,error.message);}
    finally {if(submit.isConnected) busy(submit,false);}
  });
}
async function render() {
  const sequence = ++renderSequence;
  closeModal();
  const path = location.pathname;
  if (!getSession()) {
    if (path !== '/login') {returnPath = path in routes ? path : '/';history.replaceState({},'','/login');}
    loginPage(); return;
  }
  if (getSession().user.must_change_password || passwordMode) {
    if (path !== '/login') {returnPath = path in routes ? path : '/';history.replaceState({},'','/login');}
    loginPage();return;
  }
  if (path === '/login') {navigate('/',true);return;}
  const route = routes[path];
  document.title = `${route?.title || '页面未找到'} · GateBox`;
  const root = shell(route);
  if (!route) {
    root.innerHTML = '<div class="error-panel"><div class="kicker">404 / NOT FOUND</div><h2>这条路径不存在</h2><p>请返回工作空间，选择左侧导航中的页面。</p><a class="btn primary" href="/" data-nav>返回总览</a></div>';return;
  }
  const context = {navigate,reload:() => render(),requestPassword,logout,user:getSession().user};
  try {await route.page(root,context);}
  catch (error) {if(sequence === renderSequence && root.isConnected) pageError(root,error,() => render());}
}
document.addEventListener('click',event => {
  const link = event.target.closest('a[data-nav]');
  if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault(); navigate(link.getAttribute('href'));
});
window.addEventListener('popstate',render);
window.addEventListener('gatebox:session-expired',() => {
  if (!getSession()) return;
  returnPath = location.pathname in routes ? location.pathname : '/';
  clearAuth();toast('会话已过期，请重新登录','error');navigate('/login',true);
});
window.addEventListener('gatebox:password-required',() => {
  if (!getSession()) return;
  getSession().user.must_change_password = true; passwordMode = true; navigate('/login',true);
});
window.addEventListener('pagehide', () => {
  clearReceipts();
  closeModal();
  app.querySelectorAll('input[type="password"], #receipt-url').forEach(input => {input.value = '';});
});
window.addEventListener('pageshow', event => {if (event.persisted) boot();});
async function boot() {
  try {setSession(await api('/api/auth/me'));await render();}
  catch (error) {
    if(error.status === 401) {clearAuth();await render();}
    else pageError(app,error,boot);
  }
}
boot();
