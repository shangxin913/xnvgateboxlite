let session = null;

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

const fieldNames = {
  username: '账号', password: '密码', current_password: '当前密码', new_password: '新密码',
  display_name: '节点名称', name: '名称', host: '主机', port: '端口', country_code: '国家代码',
  country_codes: '国家过滤', city: '城市', notes: '备注', priority: '优先级',
  status: '状态筛选', protocol: '协议筛选', q: '搜索关键词', page: '页码', page_size: '分页数量',
  node_check_concurrency: '检测并发', node_check_timeout_seconds: '检测超时',
  source_refresh_interval_seconds: '刷新周期', interval_seconds: '计划周期',
};
function errorMessage(detail, status) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(item => {
    const field = (item.loc || []).filter(part => part !== 'body' && part !== 'query').map(part => fieldNames[part] || part).join(' / ');
    const type = item.type || '';
    let message = item.msg || '值不符合要求';
    if (type.includes('missing')) message = '请填写此项';
    if (type.includes('greater_than_equal')) message = `不得小于 ${item.ctx?.ge ?? '允许的最小值'}`;
    if (type.includes('less_than_equal')) message = `不得大于 ${item.ctx?.le ?? '允许的最大值'}`;
    if (type.includes('string_too_short')) message = `至少需要 ${item.ctx?.min_length ?? '指定数量'} 个字符`;
    if (type.includes('string_too_long')) message = `最多允许 ${item.ctx?.max_length ?? '指定数量'} 个字符`;
    if (type.includes('int_parsing')) message = '请输入整数';
    if (type.includes('literal_error')) message = '不支持此选项，请重新选择有效值';
    return `${field ? `${field}：` : ''}${message}`;
  }).join('；');
  return ({401: '会话已失效，请重新登录',403: '没有操作权限，或安全校验已失效，请重新登录',404: '资源不存在，可能已被删除',429: '请求过于频繁，请稍后重试',501: '此能力尚未接入，当前阶段不会执行此操作'}[status] || `请求失败（HTTP ${status}）`);
}
export function setSession(value) { session = value; }
export function getSession() { return session; }
export async function api(path, options = {}) {
  const method = options.method || 'GET';
  const headers = new Headers({'Accept': 'application/json'});
  if (options.body !== undefined) headers.set('Content-Type', 'application/json');
  if (method !== 'GET' && method !== 'HEAD' && path !== '/api/auth/login') {
    if (!session?.csrf_token) throw new ApiError('缺少安全令牌，请重新登录', 401);
    headers.set('X-CSRF-Token', session.csrf_token);
  }
  let response;
  try {
    response = await fetch(path, {
      method, headers, credentials: 'same-origin', cache: 'no-store',
      body: options.body === undefined ? undefined : JSON.stringify(options.body), signal: options.signal,
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError('无法连接管理 API，请检查网络或服务状态后重试', 0);
  }
  const contentType = response.headers.get('content-type') || '';
  let data = null;
  if (contentType.includes('application/json')) {
    try { data = await response.json(); } catch { /* invalid response handled below */ }
  }
  if (!response.ok) {
    if (response.status === 401 && path !== '/api/auth/login' && path !== '/api/auth/me') {
      window.dispatchEvent(new CustomEvent('gatebox:session-expired'));
    }
    if (response.status === 403 && typeof data?.detail === 'string' && data.detail.includes('修改初始密码')) {
      window.dispatchEvent(new CustomEvent('gatebox:password-required'));
    }
    throw new ApiError(errorMessage(data?.detail, response.status), response.status, data?.detail);
  }
  if (data === null) throw new ApiError('服务返回了非 JSON 内容，请检查 API 与静态路由配置', response.status);
  return data;
}
