import {api,getSession} from './api.js';
import {icon,esc,date,heading,empty,notice,loading,modal,busy,formError,toast,confirmAction,copyText} from './ui.js';

// Deliberately memory-only: never persist a subscription token in localStorage/sessionStorage.
let receipt = null;
let receiptFormat = 'clash';
export function clearReceipts() {receipt = null;receiptFormat = 'clash';}
export function storePrivateReceipt(result, requestCSRF, dialogConnected) {
  // Each authenticated session has a unique CSRF value. Late responses must not
  // reintroduce bearer tokens after logout, re-login or closing their dialog.
  if (!dialogConnected || !requestCSRF || getSession()?.csrf_token !== requestCSRF) return false;
  receipt = result;receiptFormat = 'clash';
  return true;
}
const formatLabels = {clash:'Clash / YAML',mihomo:'Mihomo / YAML',v2ray:'V2Ray / SOCKS URI'};
const formats = () => Object.entries(formatLabels).map(([value,label]) => `<option value="${value}">${label}</option>`).join('');
function subscriptionUrl(format) {
  const path = receipt?.paths?.[format];
  if(typeof path !== 'string') throw new Error('服务端未返回此格式的订阅路径');
  const url = new URL(path,window.location.origin);
  if(url.origin !== window.location.origin || !url.pathname.startsWith('/sub/')) throw new Error('服务端订阅路径不属于本站，已阻止显示');
  return url.href;
}
function receiptMarkup() {
  if(!receipt) return '';
  return `<section class="panel receipt" aria-label="一次性订阅创建回执"><div class="panel-head"><div><div class="kicker">ONE-TIME RECEIPT / KEEP IT PRIVATE</div><h2>订阅已创建，保存这一次的链接</h2><p>${esc(receipt.name)} · 创建时输出 ${esc(receipt.node_count)} 个节点</p></div><button class="icon-btn" data-dismiss-receipt aria-label="隐藏并清除一次性链接" title="隐藏并清除一次性链接">${icon('close')}</button></div><div class="panel-body"><div class="receipt-tools"><label class="small" for="receipt-format">链接格式</label><select id="receipt-format" aria-label="选择订阅链接格式">${formats()}</select></div><div class="receipt-field"><input id="receipt-url" class="mono" aria-label="私密订阅链接" readonly autocomplete="off" spellcheck="false" value="${esc(subscriptionUrl(receiptFormat))}"><button class="btn primary" data-copy-receipt>${icon('copy')}复制链接</button></div><p class="field-hint mt">Token 只在创建时返回。这里仅保留当前标签页内存中的回执，刷新或关闭页面即丢失；不会写入浏览器持久存储。服务器仅保存摘要，现有订阅列表不能恢复链接。</p><p class="field-hint mt">链接可授权获取节点凭据，包括 SOCKS5 密码。只交给受信任使用者；不要粘贴到公开工单、截图或日志。若丢失或泄漏，请撤销后重新创建。</p></div></section>`;
}
function createSubscription(defaultHealthy,ctx) {
  const dialog = modal('创建私密订阅','创建后仅返回一次 Token。请自行保存链接，不会自动复制或发送。',`<form><div class="form-grid"><div class="field full"><label for="subscription-name">订阅名称</label><input id="subscription-name" name="name" required maxlength="100" placeholder="用于识别这份访问授权"></div><label class="check-field field full"><input type="checkbox" name="require_healthy" ${defaultHealthy ? 'checked' : ''}><span>仅包含健康节点<small>开启后，待检测和未知状态不会输出。检测器尚未接入时，这份订阅可能为空。</small></span></label><div class="field full"><label for="subscription-countries">国家过滤 <small>可选 · 两位国家代码</small></label><input id="subscription-countries" name="country_codes" placeholder="逗号分隔，例如 JP, SG" autocomplete="off"><span class="field-hint">留空包含所有国家。可多选常用代码，也可直接输入其他两位代码。</span><div class="country-chips">${[['CN','中国'],['HK','香港'],['TW','台湾'],['JP','日本'],['SG','新加坡'],['US','美国'],['DE','德国'],['GB','英国']].map(([code,label]) => `<label class="country-chip"><input type="checkbox" data-country="${code}">${label} ${code}</label>`).join('')}</div></div></div>${notice('只输出节点与出口均启用、允许进入订阅的 SOCKS5。不会输出 VPS 本机直出或 VPN Gate OpenVPN 候选。','private')}<div class="form-error" role="alert" hidden></div><div class="form-actions"><button type="button" class="btn" data-close>取消</button><button type="submit" class="btn primary">${icon('plus')}创建并显示一次性链接</button></div></form>`,{wide:true});
  const form = dialog.panel.querySelector('form');const save = form.querySelector('[type="submit"]');const countryInput = form.elements.country_codes;
  const parseCodes = () => [...new Set(countryInput.value.toUpperCase().split(/[,，;；\s]+/).filter(Boolean))];
  form.querySelectorAll('[data-country]').forEach(input => input.addEventListener('change',() => {
    const codes = new Set(parseCodes());
    if(input.checked) codes.add(input.dataset.country);else codes.delete(input.dataset.country);
    countryInput.value = [...codes].join(', ');
  }));
  countryInput.addEventListener('input',() => {
    const codes = parseCodes();form.querySelectorAll('[data-country]').forEach(input => input.checked = codes.includes(input.dataset.country));
  });
  form.addEventListener('submit',async event => {
    event.preventDefault();if(save.disabled) return;form.querySelector('.form-error').hidden = true;
    const codes = parseCodes();
    if(codes.some(code => !/^[A-Z]{2}$/.test(code))) {formError(form,'国家代码必须是两位英文字母；多个国家请用逗号分隔。');return;}
    const data = new FormData(form);busy(save,true,'正在生成私密授权…');save.dataset.submitting = 'true';
    const requestCSRF = getSession()?.csrf_token;
    try {
      const result = await api('/api/subscriptions',{method:'POST',body:{name:String(data.get('name')).trim(),require_healthy:data.has('require_healthy'),country_codes:codes}});
      if (!storePrivateReceipt(result, requestCSRF, dialog.panel.isConnected)) return;
      dialog.close();toast('订阅已创建，Token 仅这一次显示，请私密保存链接');ctx.reload();
    } catch(error){formError(form,error.message);}finally{busy(save,false);delete save.dataset.submitting;}
  });
}
async function previewSubscription(item) {
  const dialog = modal('私密订阅预览',item.name,`${notice('预览可能包含 SOCKS5 账号和密码。内容由真实 API 生成，仅供管理员核对；不会自动复制、外发或调用第三方预览服务。','private')}<div class="preview-summary"><span data-preview-count>正在读取…</span><select style="width:175px" data-preview-format aria-label="选择预览格式">${formats()}</select></div><div data-preview-warnings></div><textarea class="preview-code mono" data-preview-code readonly spellcheck="false" aria-label="私密订阅配置内容" placeholder="正在读取真实订阅内容…"></textarea><p class="field-hint mt">V2Ray 预览显示解码后的多行 socks:// URI；真实订阅端点返回整体 Base64。Clash / Mihomo 为 YAML。格式兼容不等于所有客户端已实测。</p><div class="form-error" role="alert" hidden></div><div class="form-actions"><button type="button" class="btn" data-close>关闭</button><button class="btn" data-preview-retry hidden>${icon('refresh')}重新读取</button><button class="btn primary" data-preview-copy disabled>${icon('copy')}复制预览内容</button></div>`,{wide:true});
  const select = dialog.panel.querySelector('[data-preview-format]');
  const output = dialog.panel.querySelector('[data-preview-code]');
  const count = dialog.panel.querySelector('[data-preview-count]');
  const copy = dialog.panel.querySelector('[data-preview-copy]');
  const retry = dialog.panel.querySelector('[data-preview-retry]');
  const warnings = dialog.panel.querySelector('[data-preview-warnings]');
  let content = '';let sequence = 0;
  async function load() {
    const current = ++sequence;
    copy.disabled = true;retry.hidden = true;output.value = '';content = '';count.textContent = '正在读取真实内容…';warnings.replaceChildren();dialog.panel.querySelector('.form-error').hidden = true;
    try {
      const data = await api(`/api/subscriptions/${encodeURIComponent(item.id)}/preview?format=${encodeURIComponent(select.value)}`);
      if(current !== sequence || !dialog.panel.isConnected) return;
      content = data.content;output.value = content;count.textContent = `格式：${formatLabels[data.format] || data.format} · 输出 ${data.node_count} 个节点`;
      if(data.warnings?.length) {
        const list = document.createElement('ul');list.className = 'warn-list';
        for(const warning of data.warnings) {const entry = document.createElement('li');entry.textContent = warning;list.append(entry);}
        warnings.append(list);
      }
      copy.disabled = content.length === 0;
    } catch(error) {
      if(current !== sequence || !dialog.panel.isConnected) return;
      count.textContent = '读取失败';formError(dialog.panel,error.message);retry.hidden = false;
    }
  }
  select.addEventListener('change',load);retry.addEventListener('click',load);
  copy.addEventListener('click',async () => {if(copy.disabled) return;busy(copy,true,'正在复制…');try{await copyText(content,output);}finally{busy(copy,false);}});
  await load();
}
export async function subscriptionsPage(root,ctx) {
  loading(root);
  const [data,settings] = await Promise.all([api('/api/subscriptions'),api('/api/settings')]);
  root.innerHTML = `${heading('PRIVATE ACCESS / SUBSCRIPTIONS','私密订阅','把配置交给可信使用者，并保留随时撤销授权的能力。',`<button class="btn primary" data-create>${icon('plus')}创建订阅</button>`)}${receiptMarkup()}${notice('订阅链接就是访问凭据。Clash / Mihomo 与 SOCKS URI 可能包含代理密码；只在真实授权范围内分享，默认不包含未部署的本机直出。','private')}<section class="panel"><div class="panel-head"><div><h2>订阅授权</h2><p>列表不返回 Token，也不能恢复已创建的链接</p></div><select style="width:140px" data-subscription-filter aria-label="按授权状态筛选"><option value="all">全部授权</option><option value="active">有效授权</option><option value="revoked">已撤销 / 禁用</option></select></div><div data-subscription-list></div><div class="panel-footer">创建回执之外，只提供内容预览与撤销。不提供“恢复链接”；丢失 Token 请撤销旧授权后重新创建。</div></section><div class="two-columns mt"><section class="panel"><div class="panel-head"><h2>输出规则</h2><span class="tag">SOCKS5 ONLY</span></div><div class="panel-body small muted">节点与出口均启用，并允许进入订阅的 SOCKS5 才会输出。开启健康过滤时，还必须有真实 healthy 状态。未知、待检测、OpenVPN 候选和 VPS 本机直出不被当作可用链路。</div></section><section class="panel"><div class="panel-head"><h2>空订阅同样是真实结果</h2>${icon('info')}</div><div class="panel-body small muted">没有匹配节点时，Clash / Mihomo 使用 REJECT 组，而不是 DIRECT。V2Ray 输出为空。创建回执与预览中的节点数量均来自 API，不代表客户端链路已验证。</div></section></div>`;
  root.querySelector('[data-create]').addEventListener('click',() => {
    if(receipt) {
      confirmAction({title:'替换当前一次性回执',text:'创建新订阅后，这一份内存回执会被替换。确认已经安全保存当前链接？旧订阅仍保留在列表中，可随时撤销。',label:'已保存，继续创建',action:async () => {setTimeout(() => createSubscription(settings.subscription_require_healthy,ctx),0);}});
    } else createSubscription(settings.subscription_require_healthy,ctx);
  });
  if(receipt) {
    const select = root.querySelector('#receipt-format');const input = root.querySelector('#receipt-url');const copy = root.querySelector('[data-copy-receipt]');
    select.value = receiptFormat;
    select.addEventListener('change',() => {receiptFormat = select.value;input.value = subscriptionUrl(receiptFormat);});
    copy.addEventListener('click',async () => {if(copy.disabled) return;busy(copy,true,'正在复制…');try{await copyText(input.value,input);}finally{busy(copy,false);}});
    root.querySelector('[data-dismiss-receipt]').addEventListener('click',() => confirmAction({title:'清除一次性链接回执',text:'此回执清除后，现有订阅列表无法恢复链接。确认你已保存链接？订阅本身不会撤销。',label:'已保存，清除回执',action:async () => {clearReceipts();ctx.reload();}}));
  }
  const list = root.querySelector('[data-subscription-list]');const filter = root.querySelector('[data-subscription-filter]');
  function renderList() {
    const active = item => item.is_enabled && !item.revoked_at;
    const items = data.items.filter(item => filter.value === 'all' || (filter.value === 'active' ? active(item) : !active(item)));
    list.innerHTML = items.length ? `<div class="table-wrap"><table><thead><tr><th>名称 / 授权</th><th>输出节点</th><th>过滤范围</th><th>创建时间</th><th>最近使用</th><th>操作</th></tr></thead><tbody>${items.map(item => `<tr><td><div class="row-title">${esc(item.name)}</div><div class="row-sub">${active(item) ? '有效授权' : item.revoked_at ? '已撤销 · ' + esc(date(item.revoked_at)) : '已禁用'} · #${esc(item.id)}</div></td><td class="mono">${esc(item.node_count)}</td><td><span class="tag ${item.scope.require_healthy ? 'lime' : ''}">${item.scope.require_healthy ? '仅健康节点' : '包含未验证节点'}</span><div class="row-sub">${item.scope.country_codes.length ? esc(item.scope.country_codes.join(', ')) : '所有国家'}</div></td><td class="small muted">${esc(date(item.created_at))}</td><td class="small muted">${esc(date(item.last_used_at))}</td><td><div class="row-actions"><button class="btn slim" data-preview="${esc(item.id)}" ${!active(item) ? 'disabled title="已撤销或禁用的授权不能预览"' : ''}>预览</button>${active(item) ? `<button class="btn slim danger-outline" data-revoke="${esc(item.id)}">撤销</button>` : '<span class="tag">不可访问</span>'}</div></td></tr>`).join('')}</tbody></table></div>` : empty(data.items.length ? '没有符合条件的授权' : '为可信设备创建第一份订阅',data.items.length ? '可以选择其他授权状态查看真实记录。' : '没有预置 Token。你可以创建包含真实 SOCKS5 节点的私密授权；Token 只会在创建时显示一次。',data.items.length ? '' : '<button class="btn primary" data-create-empty>'+icon('plus')+'创建订阅</button>','link');
    list.querySelector('[data-create-empty]')?.addEventListener('click',() => root.querySelector('[data-create]').click());
    list.querySelectorAll('[data-preview]').forEach(button => button.addEventListener('click',() => previewSubscription(items.find(item => String(item.id) === button.dataset.preview))));
    list.querySelectorAll('[data-revoke]').forEach(button => button.addEventListener('click',() => {
      const item = items.find(value => String(value.id) === button.dataset.revoke);
      confirmAction({title:'撤销私密订阅',text:`确定撤销“${item.name}”？此 Token 将立即失效，所有已保存的格式链接均不可访问。已下载到客户端的配置不会自动删除。`,label:'确认撤销',action:async () => {
        await api(`/api/subscriptions/${encodeURIComponent(item.id)}`,{method:'DELETE'});
        if(receipt && String(receipt.id) === String(item.id)) clearReceipts();
        toast('订阅已撤销，原 Token 已失效');ctx.reload();
      }});
    }));
  }
  filter.addEventListener('change',renderList);renderList();
}
