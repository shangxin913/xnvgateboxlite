import {api} from './api.js';
import {icon,esc,date,status,heading,empty,notice,loading,modal,formError,busy,toast,confirmAction,toggleButton} from './ui.js';

function queryPath(values) {
  const params = new URLSearchParams();
  for (const [key,value] of Object.entries(values)) if(value !== '' && value !== null && value !== undefined) params.set(key,String(value));
  const query = params.toString();return '/nodes' + (query ? '?' + query : '');
}
function nodeDialog(node,ctx) {
  const edit = Boolean(node);
  const dialog = modal(edit ? '编辑 SOCKS5 节点' : '添加 SOCKS5 节点',edit ? '修改连接参数会清除当前检测摘要，节点重新标记为待检测。' : '只添加你有权使用的真实节点；保存时不执行联网检测。',`<form id="node-form"><div class="form-grid"><div class="field full"><label for="node-name">节点名称 <small>必填 · 1–100 字符</small></label><input id="node-name" name="display_name" maxlength="100" required value="${esc(node?.display_name || '')}" placeholder="为这条连接取一个清晰的名称"></div><div class="field"><label for="node-host">主机 / IP <small>必填</small></label><input class="mono" id="node-host" name="host" required maxlength="253" value="${esc(node?.host || '')}" placeholder="域名、IPv4 或 IPv6" autocomplete="off"><span class="field-hint">不包含协议前缀、URL 路径；IPv6 可以不带方括号。</span></div><div class="field"><label for="node-port">端口 <small>1–65535</small></label><input class="mono" id="node-port" name="port" type="number" min="1" max="65535" step="1" required value="${esc(node?.port || '')}" placeholder="SOCKS5 服务端口"></div><div class="field"><label for="node-country">国家代码 <small>可选</small></label><input id="node-country" name="country_code" minlength="2" maxlength="2" pattern="[A-Za-z]{2}" value="${esc(node?.country_code || '')}" placeholder="两位国家代码，例如 CN"><span class="field-hint">ISO 两位字母，保存时转为大写；留空不设置。</span></div><div class="field"><label for="node-city">城市 <small>可选</small></label><input id="node-city" name="city" maxlength="100" value="${esc(node?.city || '')}" placeholder="填写真实节点位置"></div></div><div class="form-divider"></div><div class="form-grid"><div class="field"><label for="node-username">SOCKS5 用户名 <small>可选</small></label><input id="node-username" name="username" pattern="[^:]*" maxlength="128" value="${esc(node?.username || '')}" autocomplete="off" placeholder="无认证节点留空"><span class="field-hint">账号不能含冒号；账号与密码须同时提供。</span></div><div class="field"><label for="node-password">SOCKS5 密码 <small>${edit ? '留空保留原密码' : '可选'}</small></label><input id="node-password" name="password" type="password" maxlength="1024" autocomplete="new-password" placeholder="${edit && node.has_password ? '已有密码，留空保留' : '无认证节点留空'}"><span class="field-hint">服务端加密保存；列表与编辑接口不返回原密码。</span></div>${edit ? `<label class="check-field field full"><input type="checkbox" name="clear_auth"><span>清除 SOCKS5 认证<small>明确清空已有账号与密码，切换为无认证连接。</small></span></label>` : ''}<div class="field full"><label for="node-notes">备注 <small>最多 1000 字符</small></label><textarea id="node-notes" name="notes" maxlength="1000" placeholder="用途、维护信息或配置备注">${esc(node?.notes || '')}</textarea></div><label class="check-field field full"><input type="checkbox" name="is_enabled" ${edit ? node.is_enabled ? 'checked' : '' : 'checked'}><span>启用节点配置<small>${edit ? '只保存节点启用状态，出口开关在出口页独立维护。' : '会同时创建关联 SOCKS5 出口。'}启用不代表链路已检测或服务已运行。</small></span></label></div><div class="form-error" role="alert" hidden></div><div class="form-actions"><button class="btn" type="button" data-close>取消</button><button class="btn primary" type="submit">${icon('check')}${edit ? '保存修改' : '保存节点'}</button></div></form>`,{wide:true});
  const form = dialog.panel.querySelector('form');const save = form.querySelector('[type="submit"]');
  const username = form.elements.username;const password = form.elements.password;
  form.elements.clear_auth?.addEventListener('change',event => {
    username.disabled = event.target.checked;password.disabled = event.target.checked;
    if(event.target.checked) password.value = '';
  });
  form.addEventListener('submit',async event => {
    event.preventDefault();if(save.disabled) return;
    form.querySelector('.form-error').hidden = true;
    const data = new FormData(form);
    const clearAuth = data.has('clear_auth');
    const user = clearAuth ? null : String(data.get('username') || '') || null;
    const secret = clearAuth ? '' : String(data.get('password') || '');
    if(!clearAuth && ((!edit || !node.has_password) && Boolean(user) !== Boolean(secret))) {formError(form,'账号与密码必须同时提供，或均留空。');return;}
    if(edit && node.has_password && !clearAuth && !user) {formError(form,'已有认证不能只清空用户名。如需移除认证，请勾选“清除 SOCKS5 认证”。');return;}
    if(secret && !user) {formError(form,'提供密码时必须同时填写用户名。');return;}
    const body = {
      display_name:String(data.get('display_name')).trim(),host:String(data.get('host')).trim(),port:Number(data.get('port')),
      username:user,country_code:String(data.get('country_code') || '').trim().toUpperCase() || null,
      city:String(data.get('city') || '').trim() || null,notes:String(data.get('notes') || '').trim() || null,is_enabled:data.has('is_enabled'),
    };
    if(edit) {body.clear_auth = clearAuth;if(secret) body.password = secret;}
    else body.password = secret || null;
    busy(save,true);save.dataset.submitting = 'true';
    try {
      await api(edit ? `/api/nodes/${encodeURIComponent(node.id)}` : '/api/nodes',{method:edit ? 'PATCH' : 'POST',body});
      password.value = '';dialog.close();toast(edit ? '节点配置已更新；连接参数变化时需重新检测' : '节点和关联出口已创建，尚未执行链路检测');ctx.reload();
    } catch(error) {formError(form,error.message);}finally{busy(save,false);delete save.dataset.submitting;}
  });
}
function nodeDetails(node) {
  modal('节点详情',node.display_name,`<dl class="definition-list"><div><dt>来源 / 协议</dt><dd>${esc(node.source_type)} / ${esc(node.protocol)}</dd></div><div><dt>主机</dt><dd class="mono wrap">${esc(node.host)}</dd></div><div><dt>端口</dt><dd class="mono">${esc(node.port)}</dd></div><div><dt>认证用户名</dt><dd>${esc(node.username || '未设置')}</dd></div><div><dt>认证密码</dt><dd>${node.has_password ? '已加密保存 · 不返回原值' : '未设置'}</dd></div><div><dt>地区</dt><dd>${esc([node.country_code,node.city].filter(Boolean).join(' · ') || '未填写')}</dd></div><div><dt>当前状态</dt><dd>${status(node.status)}</dd></div><div><dt>延迟</dt><dd class="mono">${node.latency_ms === null || node.latency_ms === undefined ? '尚无检测结果' : esc(node.latency_ms) + ' ms'}</dd></div><div><dt>首次发现</dt><dd>${esc(date(node.first_seen_at))}</dd></div><div><dt>最近检测</dt><dd>${esc(date(node.last_check_at))}</dd></div><div><dt>最近成功</dt><dd>${esc(date(node.last_success_at))}</dd></div></dl><p class="small muted mt wrap">备注：${esc(node.notes || '未填写')}</p><div class="form-actions"><button class="btn" data-close>关闭</button></div>`);
}
export async function nodesPage(root,ctx) {
  loading(root);
  const params = new URLSearchParams(location.search);
  const parsedPage = Number(params.get('page'));
  const values = {q:params.get('q') || '',protocol:params.get('protocol') || '',status:params.get('status') || '',page:Number.isInteger(parsedPage) && parsedPage > 0 ? parsedPage : 1,page_size:20};
  const apiQuery = new URLSearchParams(values).toString();
  const data = await api('/api/nodes?' + apiQuery);
  const filters = Boolean(values.q || values.protocol || values.status);
  root.innerHTML = `${heading('CONNECTIONS / NODES','节点管理','管理真实连接信息。创建 SOCKS5 节点时会同步创建关联出口。',`<button class="btn" disabled title="链路检测器尚未接入">${icon('shield')}检测 · 后续接入</button><button class="btn primary" data-add>${icon('plus')}添加节点</button>`)}${notice('待检测 ≠ 健康。修改连接参数会重置检测摘要；启停只保存配置，不执行路由或联网检测。')}<section class="panel"><form class="toolbar" id="node-filters"><div class="search-field">${icon('search')}<input name="q" maxlength="100" aria-label="搜索节点" placeholder="搜索节点名称、主机或备注" value="${esc(values.q)}"></div><button type="submit" class="btn">搜索</button><select name="protocol" aria-label="按协议筛选"><option value="">全部协议</option><option value="socks5" ${values.protocol === 'socks5' ? 'selected' : ''}>SOCKS5</option><option value="openvpn" ${values.protocol === 'openvpn' ? 'selected' : ''}>OpenVPN</option></select><select name="status" aria-label="按检测状态筛选"><option value="">全部检测状态</option>${[['new','待检测'],['queued','排队中'],['checking','检测中'],['healthy','健康'],['unhealthy','不健康'],['blocked','已阻止'],['expired','已过期']].map(([value,label]) => `<option value="${value}" ${values.status === value ? 'selected' : ''}>${label}</option>`).join('')}</select>${filters ? '<button type="button" class="btn slim" data-reset>清除筛选</button>' : ''}<span class="toolbar-tail">${esc(data.total)} 个匹配节点</span></form>${data.items.length ? `<div class="table-wrap"><table><thead><tr><th>节点 / 来源</th><th>主机 / 端口</th><th>协议</th><th>认证</th><th>地区</th><th>状态 / 延迟</th><th>启用</th><th>操作</th></tr></thead><tbody>${data.items.map(node => `<tr><td><button class="icon-btn row-title" style="padding:0;text-align:left" data-detail="${esc(node.id)}">${esc(node.display_name)}</button><div class="row-sub">${node.source_type === 'manual' ? '手动添加' : 'VPN Gate 候选'} · #${esc(node.id)}</div></td><td><div class="mono">${esc(node.host)}</div><div class="row-sub mono">PORT ${esc(node.port)}</div></td><td><span class="tag">${esc(node.protocol.toUpperCase())}</span></td><td><div class="small">${esc(node.username || '无认证')}</div><div class="row-sub">${node.has_password ? '密码已加密' : '无密码'}</div></td><td><div class="small">${esc(node.country_code || '—')}</div><div class="row-sub">${esc(node.city || '未填写')}</div></td><td>${status(node.status)}<div class="row-sub mono">${node.latency_ms === null || node.latency_ms === undefined ? '未检测' : esc(node.latency_ms) + ' ms'}</div></td><td>${toggleButton(node.is_enabled,`data-toggle="${esc(node.id)}"`)}</td><td><div class="row-actions">${node.protocol === 'socks5' ? `<button class="icon-btn" data-edit="${esc(node.id)}" title="编辑节点" aria-label="编辑 ${esc(node.display_name)}">${icon('edit')}</button>` : `<button class="icon-btn" data-detail="${esc(node.id)}" title="查看候选详情">${icon('info')}</button>`}<button class="icon-btn" data-delete="${esc(node.id)}" title="删除节点" aria-label="删除 ${esc(node.display_name)}">${icon('trash')}</button></div></td></tr>`).join('')}</tbody></table></div>` : empty(filters ? '没有符合条件的节点' : '节点工作区，等待第一条连接',filters ? '试试其他关键词或清除筛选。筛选只读取真实 API，不会填充演示数据。' : '没有预置节点，没有演示 IP。添加你有权使用的 SOCKS5 连接，开始建立自己的出口配置。',filters ? '<button class="btn" data-reset>清除筛选</button>' : '<button class="btn primary" data-add>'+icon('plus')+'添加第一个节点</button>')}<div class="pagination"><span>共 ${esc(data.total)} 条 · 每页 ${esc(data.page_size)} 条</span><div class="pagination-actions"><button class="btn slim" data-prev ${data.page <= 1 ? 'disabled' : ''}>上一页</button><span class="mono">${esc(data.page)} / ${Math.max(1,Math.ceil(data.total / data.page_size))}</span><button class="btn slim" data-next ${data.page * data.page_size >= data.total ? 'disabled' : ''}>下一页</button></div></div></section>`;
  root.querySelectorAll('[data-add]').forEach(button => button.addEventListener('click',() => nodeDialog(null,ctx)));
  root.querySelectorAll('[data-reset]').forEach(button => button.addEventListener('click',() => ctx.navigate('/nodes')));
  const filtersForm = root.querySelector('#node-filters');
  const apply = () => {
    const data = new FormData(filtersForm);ctx.navigate(queryPath({q:String(data.get('q')).trim(),protocol:data.get('protocol'),status:data.get('status'),page:1}));
  };
  filtersForm.addEventListener('submit',event => {event.preventDefault();apply();});
  filtersForm.querySelectorAll('select').forEach(select => select.addEventListener('change',apply));
  root.querySelector('[data-prev]').addEventListener('click',() => ctx.navigate(queryPath({...values,page:data.page - 1})));
  root.querySelector('[data-next]').addEventListener('click',() => ctx.navigate(queryPath({...values,page:data.page + 1})));
  root.querySelectorAll('[data-detail]').forEach(button => button.addEventListener('click',() => nodeDetails(data.items.find(node => String(node.id) === button.dataset.detail))));
  root.querySelectorAll('[data-edit]').forEach(button => button.addEventListener('click',() => nodeDialog(data.items.find(node => String(node.id) === button.dataset.edit),ctx)));
  root.querySelectorAll('[data-toggle]').forEach(button => button.addEventListener('click',async () => {
    if(button.disabled) return;button.disabled = true;
    const node = data.items.find(item => String(item.id) === button.dataset.toggle);
    try {await api(`/api/nodes/${encodeURIComponent(node.id)}`,{method:'PATCH',body:{is_enabled:!node.is_enabled}});toast(node.is_enabled ? '节点已禁用；相关默认出口可能已清除' : '节点配置已启用，尚未执行检测');ctx.reload();}
    catch(error){toast(error.message,'error');button.disabled = false;}
  }));
  root.querySelectorAll('[data-delete]').forEach(button => button.addEventListener('click',() => {
    const node = data.items.find(item => String(item.id) === button.dataset.delete);
    confirmAction({title:'删除节点',text:`确定删除“${node.display_name}”？关联出口与加密凭据也会删除，相关订阅将不再输出此节点。此操作无法撤销。`,action:async () => {
      await api(`/api/nodes/${encodeURIComponent(node.id)}`,{method:'DELETE'});toast('节点与关联出口已删除');
      if(data.items.length === 1 && data.page > 1) ctx.navigate(queryPath({...values,page:data.page - 1})); else ctx.reload();
    }});
  }));
  if(params.get('create') === '1' && root.isConnected) {
    params.delete('create');history.replaceState({},'', '/nodes' + (params.toString() ? '?' + params.toString() : ''));
    nodeDialog(null,ctx);
  }
}
