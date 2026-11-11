<template>
  <div class="app-shell">
    <header class="topbar">
      <button class="menu-btn" aria-label="打开菜单" @click="menuOpen = !menuOpen; showSchema = false">
        <span></span><span></span><span></span>
      </button>
      <div class="brand">
        <div class="logo">S</div>
        <div>Text-to-SQL Agent<small>电商数据自然语言问答 · {{ meta?.total || 50 }} 张表</small></div>
      </div>
      <div class="view-tabs">
        <button class="tbtn" :class="{ active: view === 'chat' }" @click="switchView('chat')">问答</button>
        <button v-if="isAdmin" class="tbtn" :class="{ active: view === 'admin' }"
                @click="switchView('admin')">管理</button>
      </div>
      <div class="badges">
        <span class="badge">{{ status?.llm_model || 'LLM 加载中' }}</span>
        <span class="badge">{{ status?.emb_model || 'Embedding' }}</span>
        <span class="badge" :class="status?.llm_ready ? 'ok' : 'warn'">LLM {{ status?.llm_ready ? '就绪' : '未配置' }}</span>
        <span class="badge" :class="status?.index_mode === 'vector' ? 'ok' : 'warn'">
          选表 {{ status?.index_mode === 'vector' ? '向量' : '关键词' }}
        </span>
        <span class="badge warn" v-if="status?.mock_mode">Mock 模式</span>
      </div>
      <div class="spacer"></div>
      <button v-if="view === 'chat'" class="tbtn hide-mobile" @click="shareSession" :disabled="!sid">复制会话链接</button>
      <button v-if="view === 'chat'" class="tbtn hide-mobile" @click="rebuildIndex" :disabled="busy || rebuilding">
        {{ rebuilding ? '重建中…' : '重建向量索引' }}</button>
      <button v-if="view === 'chat'" class="tbtn" :class="{ active: showSchema }" @click="showSchema = !showSchema; menuOpen = false">表结构</button>
      <button class="tbtn hide-mobile" v-if="health?.auth_enabled && !basicMode" @click="logout">退出</button>
    </header>

    <div class="body" v-if="view === 'chat'">
      <aside class="sidebar" :class="{ open: menuOpen }">
        <button class="drawer-close" aria-label="关闭菜单" @click="menuOpen = false">×</button>
        <button class="new-chat" @click="newSession">+ 新会话</button>
        <div class="side-title">会话（支持多轮追问）</div>
        <div class="session-item" v-for="s in sessions" :key="s.session_id"
             :class="{ active: sid === s.session_id }" @click="loadSession(s.session_id)">
          <span>{{ s.title }}</span>
          <span class="del" role="button" tabindex="0" aria-label="删除会话"
                @click.stop="removeSession(s.session_id)"
                @keydown.enter.stop="removeSession(s.session_id)">×</span>
        </div>
        <div class="side-title">快捷提问</div>
        <div class="quick-item" v-for="q in quicks" :key="q" @click="ask(q)">{{ q }}</div>

        <div class="side-title mobile-only">运行状态</div>
        <div class="mobile-status mobile-only">
          <div>LLM：{{ status?.llm_ready ? '就绪' : '未配置' }}</div>
          <div>{{ status?.llm_model }}</div>
          <div>选表：{{ status?.index_mode === 'vector' ? '向量' : '关键词' }}</div>
          <div>{{ status?.emb_model }}</div>
        </div>
        <div class="side-title mobile-only">更多</div>
        <div class="quick-item mobile-only" v-if="isAdmin && view === 'chat'"
             @click="switchView('admin'); menuOpen = false">管理后台</div>
        <div class="quick-item mobile-only" @click="shareSession(); menuOpen = false">复制会话链接</div>
        <div class="quick-item mobile-only" @click="rebuildIndex(); menuOpen = false">重建向量索引</div>
        <div class="quick-item mobile-only" v-if="health?.auth_enabled && !basicMode"
             @click="logout(); menuOpen = false">退出登录</div>
      </aside>

      <section class="chat">
        <div class="messages" ref="msgBox">
          <div v-if="!messages.length" class="empty" style="padding-top: 70px">
            用中文问一个业务问题，例如「近 12 个月每月销售额趋势」<br />
            支持追问：那按月份呢 / 只看广东 / 换成柱状图
          </div>

          <div class="msg" v-for="(m, i) in messages" :key="m.id" :class="m.role === 'user' ? 'msg-user' : ''">
            <template v-if="m.role === 'user'">
              <div class="bubble">{{ m.content }}</div>
              <button class="edit-btn" title="回填到输入框修改后重问" @click="editQuestion(i)">编辑重问</button>
            </template>
            <div v-else class="assistant-card">
              <div class="card-section" v-if="!m.guidance && !m.noStage && (m.stage || m.stageLog.length)">
                <div class="stage" :class="{ done: m.done }">
                  <span class="dot"></span>
                  {{ m.done ? '已完成：' + (m.stageLog.join(' → ') || '处理') : m.stage }}
                </div>
                <div class="stage-log" v-if="!m.done">
                  <span v-for="(s, j) in m.stageLog" :key="j">✓ {{ s }}</span>
                </div>
              </div>

              <div class="card-section" v-if="m.guidance">
                <div class="guidance-box">
                  <div class="guidance-label">
                    {{ m.guidance.kind === 'refuse' ? '无法回答' : '需要补充信息' }}
                  </div>
                  <div class="guidance-text">{{ m.guidance.reason }}</div>
                  <div class="followups" v-if="m.guidance.suggestions && m.guidance.suggestions.length">
                    <span class="followups-label">可以这样问</span>
                    <button v-for="(q, j) in m.guidance.suggestions" :key="j" class="followup-chip"
                            @click="ask(q)">{{ q }}</button>
                  </div>
                </div>
              </div>

              <div class="card-section" v-if="m.tables.length">
                <div class="section-label">检索命中的数据表（Top {{ m.tables.length }}）</div>
                <div class="chips">
                  <span class="chip" v-for="t in m.tables" :key="t.name">
                    <b>{{ t.cn }}</b> {{ t.name }}<i>{{ t.score }}</i>
                  </span>
                </div>
              </div>

              <div class="card-section" v-if="m.sql">
                <SqlBlock :sql="m.sql" :attempt="m.attempt" @rerun="sql => rerun(m, sql)" />
                <div class="retry-note" v-for="(r, j) in m.retries" :key="j">自动纠错：{{ r }}</div>
              </div>

              <div class="card-section" v-if="m.steps && m.steps.length">
                <details class="agent-trace">
                  <summary>Agent 轨迹（{{ m.steps.length }} 步）
                    <span class="trace-id" v-if="m.traceId">trace {{ m.traceId }}</span>
                  </summary>
                  <div class="trace-row" v-for="(s, j) in m.steps" :key="j">
                    <span class="trace-dot" :class="{ fail: !s.ok }"></span>
                    <b>{{ s.tool }}</b>
                    <span class="trace-ms">{{ Math.round(s.ms) }}ms</span>
                    <span class="trace-args" v-if="s.args && Object.keys(s.args).length">{{ formatArgs(s.args) }}</span>
                    <span class="trace-err" v-if="s.error">{{ s.error }}</span>
                  </div>
                </details>
              </div>

              <div class="card-section" v-if="m.result">
                <ResultPanel :result="m.result" :question="userQuestionOf(i)" :insight="m.insight"
                             @followup="ask" @refresh-insight="ins => m.insight = ins" />
              </div>

              <div class="card-section" v-if="m.restoreFailed">
                <div class="err">历史结果恢复失败
                  <button class="inline-btn" @click="restoreResult(m)">重新恢复</button>
                </div>
              </div>
              <div class="card-section" v-if="m.notice"><div class="explain">{{ m.notice }}</div></div>
              <div class="card-section" v-if="m.error">
                <div class="err">{{ m.error }}
                  <button class="inline-btn" v-if="userQuestionOf(i)" @click="ask(userQuestionOf(i))">重试本问题</button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="composer">
          <div class="composer-inner">
            <textarea ref="inputBox" v-model="input" :disabled="busy"
                      placeholder="输入业务问题，回车发送"
                      @keydown.enter.exact.prevent="ask(input)"></textarea>
            <button v-if="busy" class="send stop" @click="stopGenerating">停止生成</button>
            <button v-else class="send" @click="ask(input)" :disabled="!input.trim()">发送</button>
          </div>
          <div class="hint">
            SQL 只读执行、禁止写操作 · 报错自动纠错 · 单次最多 {{ cfg?.max_rows || 500 }} 行
          </div>
        </div>
      </section>

      <SchemaPanel v-if="showSchema" :tables="meta?.tables || []" @close="showSchema = false" />
    </div>

    <AdminPanel v-else :status="status" :health="health" @toast="showToast" @open-chat="switchView('chat')" />

    <div class="drawer-mask" v-if="menuOpen || showSchema" @click="closeDrawers"></div>
    <div class="toast" v-if="toastText">{{ toastText }}</div>

    <div class="login-mask" v-if="needLogin">
      <div class="login-card">
        <h2>登录</h2>
        <p>请输入访问密码，登录后 24 小时内免输</p>
        <input v-model="loginUser" placeholder="用户名" @keyup.enter="doLogin" />
        <input v-model="loginPass" type="password" placeholder="密码" @keyup.enter="doLogin" />
        <button @click="doLogin">登录</button>
        <div class="err" v-if="loginErr">{{ loginErr }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api, getLastUser, getRole, getToken, setRole, setToken, streamQuery } from './api'
import SqlBlock from './components/SqlBlock.vue'
import ResultPanel from './components/ResultPanel.vue'
import SchemaPanel from './components/SchemaPanel.vue'
import AdminPanel from './components/AdminPanel.vue'

const health = ref(null)
const status = ref(null)
const cfg = ref(null)
const meta = ref(null)
const needLogin = ref(false)
const loginUser = ref(getLastUser())
const loginPass = ref('')
const loginErr = ref('')
const sessions = ref([])
const sid = ref('')
const messages = ref([])
const input = ref('')
const busy = ref(false)
const rebuilding = ref(false)
const showSchema = ref(false)
const menuOpen = ref(false)
const msgBox = ref(null)
const inputBox = ref(null)
const basicMode = ref(false)
const role = ref(getRole())
const view = ref('chat')
const isAdmin = computed(() => role.value === 'admin')
const toastText = ref('')
const pending = ref('')
const streamGen = ref(0)
const currentController = ref(null)
let msgSeq = 0
let toastTimer = null

const quicks = [
  '近 12 个月每月销售额趋势',
  '销量最高的 10 个商品',
  '各品类销售额排名',
  '库存低于安全库存的商品',
  '各省份客户数分布',
  '退款原因分布',
  '平均评分最高的商品',
]

function newId() { return `m${++msgSeq}-${Date.now()}` }
function showToast(t) {
  toastText.value = t
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toastText.value = '' }, 2600)
}
function onUnauthorized() {
  abortActive()
  setToken('')
  setRole('')
  role.value = ''
  view.value = 'chat'
  needLogin.value = true
}
function switchView(v) {
  view.value = v
  menuOpen.value = false
  showSchema.value = false
}
function onKey(e) {
  if (e.key === 'Escape' && !e.target?.classList?.contains('schema-search')) closeDrawers()
}
function closeDrawers() { menuOpen.value = false; showSchema.value = false }
function scroll() {
  nextTick(() => { if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight })
}
function syncUrl(id) {
  try {
    const u = new URL(location.href)
    if (id) u.searchParams.set('s', id)
    else u.searchParams.delete('s')
    history.replaceState(null, '', u.pathname + (u.search || ''))
  } catch (_) { /* 忽略 */ }
}
function abortActive() {
  streamGen.value++
  if (currentController.value) {
    try { currentController.value.abort() } catch (_) { /* 忽略 */ }
    currentController.value = null
  }
  busy.value = false
  pending.value = ''
}
function stopGenerating() { abortActive(); showToast('已停止生成') }

onMounted(async () => {
  window.addEventListener('t2s-unauthorized', onUnauthorized)
  window.addEventListener('keydown', onKey)
  try { health.value = await api.health() } catch (_) { /* 后端未起 */ }
  try {
    await api.config()
    basicMode.value = !getToken()
    await bootstrap()
  } catch (_) {
    needLogin.value = true
  }
})
onBeforeUnmount(() => {
  window.removeEventListener('t2s-unauthorized', onUnauthorized)
  window.removeEventListener('keydown', onKey)
  clearTimeout(toastTimer)
  abortActive()
})

async function bootstrap() {
  try {
    cfg.value = await api.config()
    role.value = cfg.value.role || getRole()
    meta.value = await api.meta()
    health.value = await api.health()
    status.value = await api.status()
    await loadSessions()
    const urlSid = new URLSearchParams(location.search).get('s')
    if (urlSid && !messages.value.length) await loadSession(urlSid)
  } catch (e) {
    if (String(e.message).includes('登录')) needLogin.value = true
  }
}

async function doLogin() {
  loginErr.value = ''
  try {
    const login = await api.login(loginUser.value, loginPass.value)
    role.value = login.role || getRole()
    needLogin.value = false
    basicMode.value = false
    loginPass.value = ''
    resetState()
    await bootstrap()
  } catch (e) { loginErr.value = e.message }
}

function resetState() {
  abortActive()
  messages.value = []
  sessions.value = []
  sid.value = ''
  input.value = ''
  syncUrl('')
}
async function logout() {
  await api.logout()
  setToken('')
  setRole('')
  role.value = ''
  view.value = 'chat'
  menuOpen.value = false
  needLogin.value = true
  resetState()
}
function shareSession() {
  if (!sid.value) { showToast('当前还没有会话'); return }
  const url = `${location.origin}${location.pathname}?s=${encodeURIComponent(sid.value)}`
  copyText(url, '会话链接已复制')
}
function copyText(text, okMsg) {
  const fallback = () => {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    try { document.execCommand('copy'); showToast(okMsg) } catch (_) { showToast('复制失败，请手动复制') }
    document.body.removeChild(ta)
  }
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(() => showToast(okMsg)).catch(fallback)
  } else fallback()
}

async function loadSessions() {
  try { sessions.value = (await api.sessions()).sessions } catch (_) { /* 忽略 */ }
}
function newSession() {
  abortActive()
  sid.value = ''
  messages.value = []
  input.value = ''
  menuOpen.value = false
  syncUrl('')
}

async function loadSession(id) {
  abortActive()
  const gen = streamGen.value
  sid.value = id
  menuOpen.value = false
  syncUrl(id)
  try {
    const d = await api.history(id)
    if (gen !== streamGen.value) return
    const restored = d.history.map(h => {
      if (h.role === 'user') return reactive({ id: newId(), role: 'user', content: h.content })
      const legacy = h.content && !h.content.startsWith('已生成并执行 SQL') ? h.content : ''
      const insight = h.insight || (legacy ? { summary: legacy, followups: [] } : null)
      const stageLog = h.guidance ? [] : ['检索表', '生成 SQL', '执行查询']
      if (insight && !h.guidance) stageLog.push('生成结论')
      const names = Array.isArray(h.tables) ? h.tables : []
      const detail = Array.isArray(h.tables_detail) ? h.tables_detail : []
      return reactive({
        id: newId(), messageId: 0, role: 'assistant', stage: '', stageLog,
        noStage: !!h.guidance,
        tables: detail.length ? detail : names.map(n => ({ name: n, cn: n, score: '' })),
        sql: h.sql || '', attempt: 1,
        steps: Array.isArray(h.steps) ? h.steps : [], traceId: h.trace_id || '',
        result: h.result || null, insight,
        notice: h.non_chinese ? '该会话原回答为非中文，已隐藏；可点「AI 解读」生成中文结论。'
          : (h.result?.auto_insight === false ? '自动结论已关闭，可点「AI 解读」手动生成。' : ''),
        guidance: h.guidance || null,
        restoreFailed: false, error: '', retries: [], done: true,
      })
    })
    messages.value = restored
    // 兼容旧会话：最多并发恢复 3 条，失败给「重新恢复」按钮，不再每次打开都重复执行
    const stale = restored.filter(m => m.role === 'assistant' && m.sql && !m.result).slice(0, 3)
    await Promise.all(stale.map(m => restoreResult(m, gen)))
  } catch (_) { messages.value = [] }
  scroll()
}

async function restoreResult(m, gen = streamGen.value) {
  m.restoreFailed = false
  try {
    const r = await api.runSql(m.sql)
    if (gen === streamGen.value) m.result = r
  } catch (_) {
    if (gen === streamGen.value) m.restoreFailed = true
  }
}

async function removeSession(id) {
  if (!window.confirm(`删除会话「${(sessions.value.find(s => s.session_id === id) || {}).title || id}」？此操作不可恢复。`)) return
  try { await api.deleteSession(id) } catch (_) { /* 忽略 */ }
  if (sid.value === id) newSession()
  await loadSessions()
}

function formatArgs(args) {
  const parts = Object.entries(args).map(([k, v]) => `${k}=${String(v).slice(0, 60)}`)
  return parts.join(' · ')
}
function userQuestionOf(i) {
  for (let j = i - 1; j >= 0; j--) if (messages.value[j].role === 'user') return messages.value[j].content
  return ''
}
function editQuestion(i) {
  input.value = messages.value[i].content || ''
  showToast('已回填到输入框，修改后回车即可重问')
  nextTick(() => inputBox.value?.focus())
}

async function ask(q) {
  const question = (q || '').trim()
  if (!question) return
  if (busy.value) {
    pending.value = question
    showToast('正在生成，已排队；可点「停止生成」立即切换')
    return
  }
  menuOpen.value = false
  input.value = ''
  messages.value.push({ id: newId(), role: 'user', content: question })
  const m = reactive({
    id: newId(), messageId: 0,
    role: 'assistant', stage: '准备中…', stageLog: [], tables: [], sql: '',
    attempt: 1, result: null, insight: null, guidance: null, notice: '',
    noStage: false, restoreFailed: false, error: '', retries: [], done: false,
    steps: [], traceId: '',
  })
  messages.value.push(m)
  busy.value = true
  const gen = ++streamGen.value
  const controller = new AbortController()
  currentController.value = controller
  scroll()

  try {
    await streamQuery({ question, session_id: sid.value || null }, ev => {
      if (gen !== streamGen.value) return
      switch (ev.type) {
        case 'session':
          sid.value = ev.session_id
          m.traceId = ev.trace_id || ''
          syncUrl(ev.session_id)
          break
        case 'stage': m.stage = ev.label; break
        case 'tables': m.tables = ev.tables; m.stageLog.push('检索表'); break
        case 'sql':
          m.sql = ev.sql; m.attempt = ev.attempt
          if (!m.stageLog.includes('生成 SQL')) m.stageLog.push('生成 SQL')
          break
        case 'retry': m.retries.push(ev.error); break
        case 'step':
          m.steps.push({ tool: ev.tool, ok: ev.ok, ms: ev.ms || 0, args: ev.args || {}, error: ev.error || '' })
          break
        case 'guidance':
          m.guidance = ev; m.stage = ''; m.stageLog = []; m.noStage = true
          break
        case 'result':
          m.result = ev; m.messageId = ev.message_id || 0
          if (!m.stageLog.includes('执行查询')) m.stageLog.push('执行查询')
          break
        case 'insight':
          if (ev.summary) {
            m.insight = { summary: ev.summary, text: ev.text, followups: ev.followups || [] }
            if (!m.stageLog.includes('生成结论')) m.stageLog.push('生成结论')
          }
          break
        case 'insight_warning': m.retries.push(ev.message); break
        case 'insight_disabled': m.notice = ev.message; break
        case 'notice': m.notice = ev.message || ev.text; break
        case 'error': m.error = ev.message; if (ev.sql) m.sql = ev.sql; break
        case 'done':
          m.done = true
          m.stage = ''
          m.traceId = ev.trace_id || m.traceId
          break
      }
      scroll()
    }, { signal: controller.signal })
  } catch (e) {
    if (gen === streamGen.value && !controller.signal.aborted) m.error = e.message
  } finally {
    if (gen === streamGen.value) {
      busy.value = false
      m.done = true
      m.stage = ''
      currentController.value = null
      await loadSessions()
      scroll()
      if (pending.value) {
        const p = pending.value
        pending.value = ''
        ask(p)
      }
    }
  }
}

async function rerun(m, sql) {
  try {
    const r = await api.runSql(sql, sid.value || null, m.messageId || null)
    m.result = r
    m.sql = r.sql || sql
    m.insight = null              // 数据变了，旧结论必须失效
    m.error = ''
    m.notice = 'SQL 已重跑，结论需点「AI 解读」重新生成。'
    showToast('重跑成功，结果已保存到会话')
  } catch (e) { m.error = e.message }
}

async function rebuildIndex() {
  if (rebuilding.value) return
  rebuilding.value = true
  try {
    const r = await api.rebuildIndex()
    window.alert(`索引已重建：${r.table_count} 张表（${r.mock ? '本地伪向量' : '硅基流动真实向量'}）`)
    status.value = await api.status()
  } catch (e) { window.alert('重建失败：' + e.message) }
  finally { rebuilding.value = false }
}
</script>
