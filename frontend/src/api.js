// 后端接口封装：只用原生 fetch，不引 axios。
//   /api/*        → Java 后端 :8080（业务数据）
//   /collector/*  → Python 采集服务 :8801（登录 / 账号 / 同步）
// 两者都走 vite 代理，浏览器同源；密码只走 /collector 这条，不经过 Java。

/**
 * 后端 JSON 用 snake_case（item_type / start_time），这里统一深转成 camelCase，
 * 让页面里的代码保持 JS 习惯；后端改命名策略也不影响页面。
 */
function toCamel(value) {
  if (Array.isArray(value)) return value.map(toCamel)
  if (value && typeof value === 'object') {
    const out = {}
    for (const [k, v] of Object.entries(value)) {
      out[k.replace(/_([a-z0-9])/g, (_, c) => c.toUpperCase())] = toCamel(v)
    }
    return out
  }
  return value
}

async function request(path, options = {}) {
  const res = await fetch(path, options)
  const text = await res.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = { raw: text }
  }
  if (!res.ok) {
    const err = new Error(data?.message || data?.detail || `请求失败（HTTP ${res.status}）`)
    err.status = res.status
    err.data = data
    throw err
  }
  return toCamel(data)
}

const jsonPost = (body) => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  // ---- Java 后端
  health: () => request('/api/health'),
  overview: () => request('/api/overview'),
  sync: () => request('/api/sync', { method: 'POST' }),
  syncStatus: () => request('/api/sync/status'),

  // ---- 采集服务（凭据相关）
  account: () => request('/collector/api/account'),
  collectorSyncStatus: () => request('/collector/api/sync/status'),
  login: ({ phone, password, remember }) =>
    request('/collector/api/login', jsonPost({ phone, password, remember })),
  logout: () => request('/collector/api/logout', { method: 'POST' }),
}
