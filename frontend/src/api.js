// 后端 API 封装：应用 token（独立头）+ SSE 流式解析 + 可取消流
const TOKEN_KEY = 't2s_token'
const LAST_USER_KEY = 't2s_last_user'
const ROLE_KEY = 't2s_role'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setToken(t) {
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}
export function getLastUser() { return localStorage.getItem(LAST_USER_KEY) || '' }
export function setLastUser(u) {
  if (u) localStorage.setItem(LAST_USER_KEY, u)
  else localStorage.removeItem(LAST_USER_KEY)
}
export function getRole() { return localStorage.getItem(ROLE_KEY) || '' }
export function setRole(r) {
  if (r) localStorage.setItem(ROLE_KEY, r)
  else localStorage.removeItem(ROLE_KEY)
}

function authHeaders() {
  const h = { 'Content-Type': 'application/json' }
  // 应用 token 走独立头，Authorization 留给可选的 nginx Basic
  const t = getToken()
  if (t) h['X-App-Token'] = t
  return h
}

function unauthorized() {
  setToken('')
  setRole('')
  window.dispatchEvent(new CustomEvent('t2s-unauthorized'))
}

async function request(path, options = {}) {
  const res = await fetch(path, { ...options, headers: { ...authHeaders(), ...(options.headers || {}) } })
  if (res.status === 401) {
    unauthorized()
    throw new Error('登录已失效，请重新登录')
  }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try {
      const data = await res.json()
      msg = data.detail || data.message || msg
    } catch (_) { /* ignore */ }
    throw new Error(msg)
  }
  return res.json()
}

export const api = {
  health: () => fetch('/api/health').then(r => r.json()),
  status: () => request('/api/status'),
  login: (username, password) => request('/api/login', {
    method: 'POST', body: JSON.stringify({ username, password }),
  }).then(d => {
    setToken(d.token || '')
    setLastUser(username)
    setRole(d.role || '')
    return d
  }),
  logout: () => request('/api/logout', { method: 'POST' }).catch(() => ({})),
  config: () => request('/api/config').then(d => {
    if (d.role) setRole(d.role)
    if (d.user) setLastUser(d.user)
    return d
  }),
  meta: () => request('/api/meta'),
  table: (name) => request(`/api/tables/${encodeURIComponent(name)}`),
  sessions: () => request('/api/sessions'),
  history: (sid) => request(`/api/history?session_id=${encodeURIComponent(sid)}`),
  deleteSession: (sid) => request(`/api/sessions/${encodeURIComponent(sid)}`, { method: 'DELETE' }),
  runSql: (sql, session_id, message_id) => request('/api/sql', {
    method: 'POST', body: JSON.stringify({ sql, session_id, message_id }),
  }),
  explain: (payload) => request('/api/explain', { method: 'POST', body: JSON.stringify(payload) }),
  rebuildIndex: () => request('/api/index/rebuild', { method: 'POST' }),
  adminOverview: () => request('/api/admin/overview'),
  adminKnowledge: () => request('/api/admin/knowledge'),
  adminAddSql: (payload) => request('/api/admin/knowledge/sql', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  adminFromMessage: (payload) => request('/api/admin/knowledge/from-message', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  adminDeleteSql: (id) => request(`/api/admin/knowledge/sql/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  adminAddRule: (payload) => request('/api/admin/knowledge/rules', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  adminDeleteRule: (id) => request(`/api/admin/knowledge/rules/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  adminSessions: () => request('/api/admin/sessions'),
  adminHistory: (sid) => request(`/api/admin/history?session_id=${encodeURIComponent(sid)}`),
  adminDeleteSession: (sid) => request(`/api/admin/sessions/${encodeURIComponent(sid)}`, { method: 'DELETE' }),
  adminTraces: () => request('/api/admin/traces'),
  adminUsers: () => request('/api/admin/users'),
  semantic: () => request('/api/semantic'),
}

/** SSE 流式提问；onEvent 逐条收到后端事件对象。
 *  opts.signal 可由外部 abort（停止生成 / 切换会话）；内置超时防止永久挂起。
 *  按 SSE 规范合并多行 data:、支持 event:、循环结束 flush 尾部残帧。
 */
export async function streamQuery(payload, onEvent, opts = {}) {
  const { signal, timeoutMs = 240000 } = opts
  const ctrl = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => { timedOut = true; ctrl.abort() }, timeoutMs)
  const onAbort = () => ctrl.abort()
  if (signal) {
    if (signal.aborted) ctrl.abort()
    else signal.addEventListener('abort', onAbort, { once: true })
  }
  try {
    const res = await fetch('/api/query', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify(payload),
      signal: ctrl.signal,
    })
    if (res.status === 401) {
      unauthorized()
      throw new Error('登录已失效，请重新登录')
    }
    if (!res.ok || !res.body) throw new Error(`查询请求失败：HTTP ${res.status}`)

    const reader = res.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    const handleFrame = frame => {
      let data = ''
      let evType = ''
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith('data:')) data += (data ? '\n' : '') + line.slice(5).trimStart()
        else if (line.startsWith('event:')) evType = line.slice(6).trim()
        else if (line.startsWith(':')) return   // 心跳 / 注释帧
      }
      if (!data) return
      try {
        const ev = JSON.parse(data)
        if (evType && !ev.type) ev.type = evType
        onEvent(ev)
      } catch (_) {
        console.warn('[SSE] 忽略坏帧：', data.slice(0, 120))
      }
    }
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop() || ''
      for (const f of frames) handleFrame(f)
    }
    buffer += decoder.decode()      // 冲掉跨 chunk 的残字节
    if (buffer.trim()) handleFrame(buffer)
  } finally {
    clearTimeout(timer)
    if (signal) signal.removeEventListener('abort', onAbort)
    if (timedOut) onEvent({ type: 'error', message: '生成超时，已停止。请重试或换一种问法。' })
  }
}
