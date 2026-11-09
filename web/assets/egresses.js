import {api} from './api.js';
import {icon,esc,status,heading,notice,loading,toggleButton,busy,modal,formError,toast,confirmAction,empty} from './ui.js';
function editEgress(item,ctx) {
  const local = item.kind === 'local';
  const dialog = modal('编辑出口配置',local ? '本机直出仅代表 VPS 上的路由意图，不是远程客户端代理。' : '出口关联真实 SOCKS5 节点；连接参数请在节点页编辑。',`<form><div class="form-grid"><div class="field full"><label for="egress-name">出口名称</label><input id="egress-name" name="name" required maxlength="100" value="${esc(item.name)}"></div><div class="field full"><label for="egress-priority">优先级 <small>0–1000</small></label><input class="mono" id="egress-priority" name="priority" type="number" required min="0" max="1000" step="1" value="${esc(item.priority)}"><span class="field-hint">保存供后续编排使用，当前不触发自动切换或系统路由变更。</span></div><label class="check-field field full"><input name="is_enabled" type="checkbox" ${item.is_enabled ? 'checked' : ''}><span>启用此出口配置<small>仅配置启停，不部署监听、隧道或执行器。</small></span></label>${local ? `<div class="field full">${notice('本机直出不支持远端订阅输出。当前没有 VPS 接入监听，不能把客户端 DIRECT 当作 VPS 出口。','warning')}</div>` : `<label class="check-field field full"><input name="include_in_subscription" type="checkbox" ${item.include_in_subscription ? 'checked' : ''}><span>允许进入订阅<small>节点与出口均启用后才会输出。授权订阅者可能获取 SOCKS5 账号和密码。</small></span></label>`}</div><div class="form-error" role="alert" hidden></div><div class="form-actions"><button class="btn" type="button" data-close>取消</button><button class="btn primary" type="submit">保存配置</button></div></form>`);
  const form = dialog.panel.querySelector('form');const save = form.querySelector('[type="submit"]');
  form.addEventListener('submit',async event => {
    event.preventDefault();if(save.disabled) return;busy(save,true);save.dataset.submitting = 'true';
    const data = new FormData(form);
    const body = {name:String(data.get('name')).trim(),priority:Number(data.get('priority')),is_enabled:data.has('is_enabled')};
    if(!local) body.include_in_subscription = data.has('include_in_subscription');
    try {await api(`/api/egresses/${encodeURIComponent(item.id)}`,{method:'PATCH',body});dialog.close();toast('出口配置已保存，未改变系统路由');ctx.reload();}
    catch(error){formError(form,error.message);}finally{busy(save,false);delete save.dataset.submitting;}
  });
}
export async function egressesPage(root,ctx) {
  loading(root);const data = await api('/api/egresses');
  const socks = data.items.filter(item => item.kind === 'socks5');
  const current = data.items.find(item => item.is_default);
  root.innerHTML = `${heading('ROUTING / EGRESS CONFIGURATION','出口配置','配置可用出口与默认编排策略；没有隐藏的系统路由操作。','<a class="btn primary" href="/nodes?create=1" data-nav>'+icon('plus')+'添加 SOCKS5 出口</a>')}${notice('“设为默认”只保存后续编排策略，不修改 VPS 系统路由，也不代表出口已部署或可用。只有启用的出口可以设为默认。','warning')}<section class="panel"><div class="panel-head"><div><h2>出口工作区</h2><p>${data.items.length} 条真实配置 · ${socks.length} 条 SOCKS5 关联</p></div><span class="tag ${current ? 'lime' : ''}">${current ? '默认配置：' + esc(current.name) : '尚未设置默认出口'}</span></div>${data.items.length ? `<div class="table-wrap"><table><thead><tr><th>出口 / 类型</th><th>连接信息</th><th>配置状态</th><th>优先级</th><th>订阅输出</th><th>启用</th><th>操作</th></tr></thead><tbody>${data.items.map(item => {
    const local = item.kind === 'local';
    return `<tr><td><div class="egress-kind">${icon(local ? 'route' : 'nodes')}<div><div class="row-title">${esc(item.name)}</div><div class="row-sub">${local ? '本机直出 / LOCAL' : 'SOCKS5 / 节点 #' + esc(item.node_id)}</div></div></div>${item.is_default ? '<span class="egress-default">默认策略</span>' : ''}</td><td>${local ? '<div class="small muted">VPS 路由意图</div><div class="row-sub">无远程接入监听</div>' : `<div class="mono">${esc(item.host)}:${esc(item.port)}</div><div class="row-sub">${esc(item.username || '无认证')}</div>`}</td><td>${status(item.status)}<div class="row-sub">${local ? '配置不代表部署' : '状态不代表当前流量已路由'}</div></td><td class="mono">${esc(item.priority)}</td><td><span class="small muted">${local ? '不支持' : item.include_in_subscription ? '允许' : '不包含'}</span></td><td>${toggleButton(item.is_enabled,`data-toggle="${esc(item.id)}"`)}</td><td><div class="row-actions"><button class="btn slim" data-edit="${esc(item.id)}">编辑</button>${item.is_default ? '<span class="tag lime">当前默认</span>' : `<button class="btn slim" data-default="${esc(item.id)}" ${!item.is_enabled ? 'disabled title="请先启用此出口配置"' : ''}>设为默认</button>`}</div></td></tr>`;
  }).join('')}</tbody></table></div>` : empty('服务端尚无出口配置','本机直出配置应由服务初始化创建。请检查初始化状态，或添加合法的 SOCKS5 节点。','','route')}<div class="panel-footer">本机直出不可删除。删除 SOCKS5 出口需在节点页删除关联节点；禁用或删除默认出口会清除默认策略。</div></section><div class="two-columns mt"><section class="panel"><div class="panel-head"><h2>本机直出 ≠ 客户端 DIRECT</h2><span class="tag">EXECUTION BOUNDARY</span></div><div class="panel-body small muted">本机直出是 VPS 路由配置意图。未部署 VPS 接入监听时，远程客户端无法通过它访问网络。因此它不会写入 SOCKS、Clash 或 Mihomo 订阅。</div></section><section class="panel"><div class="panel-head"><h2>新增 SOCKS5 出口</h2>${icon('nodes')}</div><div class="panel-body"><p class="small muted">在节点页保存合法 SOCKS5 连接，服务端将自动建立关联出口。端口、主机、账号与密码只在节点页维护。</p><a class="text-link mt" href="/nodes" data-nav>前往节点管理${icon('arrow')}</a></div></section></div>`;
  root.querySelectorAll('[data-edit]').forEach(button => button.addEventListener('click',() => editEgress(data.items.find(item => String(item.id) === button.dataset.edit),ctx)));
  root.querySelectorAll('[data-toggle]').forEach(button => button.addEventListener('click',async () => {
    if(button.disabled) return;button.disabled = true;
    const item = data.items.find(value => String(value.id) === button.dataset.toggle);
    try {await api(`/api/egresses/${encodeURIComponent(item.id)}`,{method:'PATCH',body:{is_enabled:!item.is_enabled}});toast(item.is_enabled ? '出口已禁用；若为默认，默认策略已清除' : '出口配置已启用，未改变系统路由');ctx.reload();}
    catch(error){toast(error.message,'error');button.disabled = false;}
  }));
  root.querySelectorAll('[data-default]').forEach(button => button.addEventListener('click',() => {
    if(button.disabled) return;const item = data.items.find(value => String(value.id) === button.dataset.default);
    confirmAction({title:'保存默认出口策略',text:`将“${item.name}”设为默认出口？这只保存未来编排使用的配置，不修改系统路由、不执行切换或链路检测。`,label:'保存默认策略',action:async () => {await api(`/api/egresses/${encodeURIComponent(item.id)}/default`,{method:'POST'});toast('默认出口策略已保存，系统路由未修改');ctx.reload();}});
  }));
}
