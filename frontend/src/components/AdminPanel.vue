<template>
  <div class="admin-shell">
    <aside class="admin-nav">
      <div class="admin-nav-title">管理后台</div>
      <button v-for="t in tabs" :key="t.key" class="admin-nav-item"
              :class="{ active: tab === t.key }" @click="tab = t.key">
        <span>{{ t.label }}</span>
        <small v-if="t.hint">{{ t.hint }}</small>
      </button>
      <div class="admin-nav-foot">
        <button class="tbtn" @click="$emit('open-chat')">← 返回问答</button>
      </div>
    </aside>

    <section class="admin-main">
      <div class="admin-head">
        <div>
          <h2>{{ currentTab.label }}</h2>
          <p>{{ currentTab.desc }}</p>
        </div>
        <div class="spacer"></div>
        <button class="tbtn" :disabled="loading" @click="refresh">{{ loading ? '加载中…' : '刷新' }}</button>
      </div>

      <div v-if="error" class="err admin-alert">{{ error }}</div>

      <!-- 概览 -->
      <template v-if="tab === 'overview'">
        <div class="admin-cards">
          <div class="admin-card"><span>会话总数</span><b>{{ overview?.sessions ?? '-' }}</b></div>
          <div class="admin-card"><span>知识样例</span><b>{{ overview?.knowledge?.sql ?? '-' }}</b></div>
          <div class="admin-card"><span>业务规则</span><b>{{ overview?.knowledge?.rules ?? '-' }}</b></div>
          <div class="admin-card"><span>成功率</span><b>{{ pct(overview?.metrics?.success_rate) }}</b></div>
          <div class="admin-card"><span>P50 / P95</span><b>{{ ms(overview?.metrics?.latency_ms?.p50) }} / {{ ms(overview?.metrics?.latency_ms?.p95) }}</b></div>
          <div class="admin-card"><span>Trace 数</span><b>{{ overview?.metrics?.traces ?? '-' }}</b></div>
        </div>

        <div class="admin-grid2">
          <div class="admin-panel">
            <div class="section-label">模型链路（主模型 → 兜底）</div>
            <div v-for="(p, i) in overview?.llm_chain || []" :key="p.provider + p.model" class="admin-row">
              <span class="admin-index">{{ i + 1 }}</span>
              <div class="admin-row-main">
                <b>{{ p.provider || 'custom' }}</b>
                <span class="mono">{{ p.model }}</span>
                <small>{{ p.base_url }}</small>
              </div>
              <span class="badge" :class="p.ready ? 'ok' : 'warn'">{{ p.ready ? '就绪' : '缺 key' }}</span>
            </div>
            <div v-if="!(overview?.llm_chain || []).length" class="hint">未配置模型链路</div>
          </div>

          <div class="admin-panel">
            <div class="section-label">运行状态</div>
            <div class="admin-kv"><span>选表模式</span><b>{{ overview?.status?.index_mode }}（{{ overview?.status?.indexed_tables }} / {{ overview?.status?.table_count }} 表）</b></div>
            <div class="admin-kv"><span>Agent</span><b>{{ overview?.status?.agent_mode }} · 最多 {{ overview?.status?.max_llm_calls }} 次 LLM</b></div>
            <div class="admin-kv"><span>数据库</span><b>{{ overview?.status?.db_dialect }}</b></div>
            <div class="admin-kv"><span>Embedding</span><b>{{ overview?.status?.emb_model }}</b></div>
            <div class="admin-kv"><span>知识库路径</span><b class="mono">{{ overview?.knowledge?.path }}</b></div>
            <div class="admin-kv"><span>版本</span><b>{{ overview?.version }}</b></div>
          </div>
        </div>

        <div class="admin-panel">
          <div class="section-label">最近 Trace</div>
          <div class="table-wrap admin-table">
            <table>
              <thead><tr><th>Trace</th><th>状态</th><th>耗时</th><th>LLM 调用</th><th>开始时间</th></tr></thead>
              <tbody>
                <tr v-for="t in overview?.recent_traces || []" :key="t.trace_id">
                  <td class="mono">{{ t.trace_id }}</td>
                  <td><span class="badge" :class="t.status === 'ok' ? 'ok' : 'warn'">{{ t.status }}</span></td>
                  <td>{{ ms(t.duration_ms) }}</td>
                  <td>{{ t.llm_calls }}</td>
                  <td>{{ time(t.started_at) }}</td>
                </tr>
                <tr v-if="!(overview?.recent_traces || []).length"><td colspan="5" class="hint">暂无 trace</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>

      <!-- 知识库 -->
      <template v-else-if="tab === 'knowledge'">
        <div class="admin-grid2">
          <div class="admin-panel">
            <div class="section-label">收录一条 NL → SQL 样例</div>
            <input v-model="sqlForm.question" class="admin-input" placeholder="自然语言问题，例如：近 12 个月每月销售额趋势" />
            <textarea v-model="sqlForm.sql" class="admin-textarea mono" rows="6" placeholder="SELECT ...（只允许只读 SQL）"></textarea>
            <input v-model="sqlForm.tables" class="admin-input" placeholder="涉及表，逗号分隔（可留空自动推断）" />
            <input v-model="sqlForm.notes" class="admin-input" placeholder="备注 / 口径说明（可选）" />
            <button class="admin-primary" :disabled="saving || !sqlForm.question.trim() || !sqlForm.sql.trim()" @click="saveSql">
              {{ saving ? '保存中…' : '保存为正式样例' }}
            </button>
          </div>

          <div class="admin-panel">
            <div class="section-label">新增业务规则</div>
            <input v-model="ruleForm.title" class="admin-input" placeholder="规则标题（可选）" />
            <textarea v-model="ruleForm.text" class="admin-textarea" rows="6" placeholder="例如：统计有效成交时排除 cancelled / refunded 订单"></textarea>
            <button class="admin-primary" :disabled="saving || !ruleForm.text.trim()" @click="saveRule">
              {{ saving ? '保存中…' : '保存规则' }}
            </button>
          </div>
        </div>

        <div class="admin-panel">
          <div class="section-label">正式样例（{{ knowledge?.stats?.sql || 0 }}）</div>
          <div v-for="item in knowledge?.sql || []" :key="item.id" class="admin-knowledge">
            <div class="admin-row">
              <div class="admin-row-main">
                <b>{{ item.question }}</b>
                <small class="mono">{{ item.id }} · {{ item.source || 'admin' }} · {{ item.created }}</small>
              </div>
              <button class="tbtn danger" @click="removeSql(item)">删除</button>
            </div>
            <pre class="admin-pre">{{ item.sql }}</pre>
            <div v-if="item.notes" class="hint">{{ item.notes }}</div>
          </div>
          <div v-if="!(knowledge?.sql || []).length" class="hint">还没有正式样例。可在「会话轨迹」里把一条验证过的回答收录进来。</div>
        </div>

        <div class="admin-panel">
          <div class="section-label">业务规则（{{ knowledge?.stats?.rules || 0 }}）</div>
          <div v-for="item in knowledge?.rules || []" :key="item.id" class="admin-knowledge">
            <div class="admin-row">
              <div class="admin-row-main">
                <b>{{ item.title }}</b>
                <small class="mono">{{ item.id }} · {{ item.created }}</small>
              </div>
              <button class="tbtn danger" @click="removeRule(item)">删除</button>
            </div>
            <div class="admin-rule-text">{{ item.text }}</div>
          </div>
          <div v-if="!(knowledge?.rules || []).length" class="hint">还没有自定义规则，模型只使用 semantic/metrics.yaml 的默认口径。</div>
        </div>
      </template>

      <!-- 语义层 -->
      <template v-else-if="tab === 'semantic'">
        <div class="admin-panel">
          <div class="section-label">业务口径规则</div>
          <ul class="admin-list">
            <li v-for="(r, i) in semantic?.business_rules || []" :key="i">{{ r }}</li>
          </ul>
        </div>
        <div class="admin-panel">
          <div class="section-label">受治理指标（{{ (semantic?.metrics || []).length }}）</div>
          <div class="table-wrap admin-table">
            <table>
              <thead><tr><th>指标</th><th>表达式</th><th>有效过滤</th><th>单位</th></tr></thead>
              <tbody>
                <tr v-for="m in semantic?.metrics || []" :key="m.id">
                  <td><b>{{ m.name }}</b><br><small class="mono">{{ m.id }}</small></td>
                  <td class="mono">{{ m.expr }}</td>
                  <td class="mono">{{ m.valid_filter || '-' }}</td>
                  <td>{{ m.unit || '-' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div class="admin-panel">
          <div class="section-label">标准 JOIN</div>
          <div v-for="(j, i) in semantic?.joins || []" :key="i" class="admin-join mono">{{ j.on }}</div>
          <div v-if="!(semantic?.joins || []).length" class="hint">未配置</div>
        </div>
      </template>

      <!-- 会话轨迹 -->
      <template v-else-if="tab === 'sessions'">
        <div class="admin-split">
          <div class="admin-panel admin-session-list">
            <div class="section-label">全部会话（{{ sessions.length }}）</div>
            <button v-for="s in sessions" :key="s.session_id" class="admin-session"
                    :class="{ active: selectedSid === s.session_id }"
                    @click="openSession(s.session_id)">
              <b>{{ s.title || '新会话' }}</b>
              <small>{{ s.owner || '未归属' }} · {{ s.updated_at }}</small>
            </button>
            <div v-if="!sessions.length" class="hint">暂无会话</div>
          </div>
          <div class="admin-panel admin-history">
            <div class="section-label">会话详情</div>
            <div v-if="!selectedSid" class="hint">选择左侧会话查看消息，并可把已验证的回答收录进知识库。</div>
            <div v-for="h in history" :key="h.id" class="admin-msg" :class="h.role">
              <div class="admin-msg-role">{{ h.role === 'user' ? '用户' : 'Agent' }} <small>#{{ h.id }}</small></div>
              <div class="admin-msg-text">{{ h.content || '（无正文）' }}</div>
              <pre v-if="h.sql" class="admin-pre">{{ h.sql }}</pre>
              <div v-if="h.role === 'assistant' && h.sql" class="admin-msg-actions">
                <button class="tbtn" :disabled="saving" @click="saveFromMessage(h)">收录为知识样例</button>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- 系统 -->
      <template v-else>
        <div class="admin-grid2">
          <div class="admin-panel">
            <div class="section-label">账号与角色</div>
            <div v-for="u in users" :key="u.username" class="admin-kv">
              <span>{{ u.username }}</span>
              <span class="badge" :class="u.role === 'admin' ? 'ok' : ''">{{ u.role }}</span>
            </div>
            <div class="hint">账号在 .env 的 AUTH_USERS 中配置；普通用户看不到本页。</div>
          </div>
          <div class="admin-panel">
            <div class="section-label">运维操作</div>
            <button class="admin-primary" :disabled="rebuilding" @click="rebuild">
              {{ rebuilding ? '重建中…' : '重建向量索引' }}
            </button>
            <div class="hint">重建会调用一次 SiliconFlow embedding；已带冷却与原子写。</div>
            <div class="admin-kv"><span>GitHub</span><a href="https://github.com/standbyme626/text2sql-agent" target="_blank" rel="noopener">standbyme626/text2sql-agent</a></div>
          </div>
        </div>
        <div class="admin-panel">
          <div class="section-label">环境状态</div>
          <pre class="admin-pre">{{ JSON.stringify(status || {}, null, 2) }}</pre>
        </div>
      </template>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api'

const props = defineProps({
  status: { type: Object, default: null },
  health: { type: Object, default: null },
})
const emit = defineEmits(['toast', 'open-chat'])

const tabs = [
  { key: 'overview', label: '概览', desc: '运行状态、模型链路与最近 trace', hint: '总览' },
  { key: 'knowledge', label: '知识库', desc: '确认过的 NL→SQL 样例与业务规则', hint: '可审计' },
  { key: 'semantic', label: '语义指标', desc: '受治理指标、口径规则与标准 JOIN', hint: 'MDL' },
  { key: 'sessions', label: '会话轨迹', desc: '全部用户会话与回答收录', hint: '巡检' },
  { key: 'system', label: '系统', desc: '账号角色与运维操作', hint: '运维' },
]

const tab = ref('overview')
const overview = ref(null)
const knowledge = ref(null)
const semantic = ref(null)
const sessions = ref([])
const history = ref([])
const users = ref([])
const selectedSid = ref('')
const loading = ref(false)
const saving = ref(false)
const rebuilding = ref(false)
const error = ref('')
const sqlForm = reactive({ question: '', sql: '', tables: '', notes: '' })
const ruleForm = reactive({ title: '', text: '' })

const currentTab = computed(() => tabs.find(t => t.key === tab.value) || tabs[0])

function notify(msg) { emit('toast', msg) }
function pct(v) { return v == null ? '-' : `${Math.round(Number(v) * 1000) / 10}%` }
function ms(v) { return v == null ? '-' : `${Math.round(Number(v))} ms` }
function time(ts) {
  if (!ts) return '-'
  const d = new Date(Number(ts) * 1000)
  return Number.isNaN(d.getTime()) ? '-' : d.toLocaleString()
}
function csv(s) { return String(s || '').split(',').map(x => x.trim()).filter(Boolean) }

async function loadOverview() { overview.value = await api.adminOverview() }
async function loadKnowledge() { knowledge.value = await api.adminKnowledge() }
async function loadSemantic() { semantic.value = await api.semantic() }
async function loadUsers() { users.value = (await api.adminUsers()).users || [] }
async function loadSessions() { sessions.value = (await api.adminSessions()).sessions || [] }

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    await Promise.all([loadOverview(), loadKnowledge(), loadSemantic(), loadUsers()])
    if (tab.value === 'sessions') await loadSessions()
  } catch (e) { error.value = e.message } finally { loading.value = false }
}

async function saveSql() {
  saving.value = true
  error.value = ''
  try {
    await api.adminAddSql({
      question: sqlForm.question.trim(),
      sql: sqlForm.sql.trim(),
      tables: csv(sqlForm.tables),
      notes: sqlForm.notes.trim(),
    })
    sqlForm.question = ''; sqlForm.sql = ''; sqlForm.tables = ''; sqlForm.notes = ''
    await loadKnowledge(); await loadOverview()
    notify('已收录为正式样例')
  } catch (e) { error.value = e.message } finally { saving.value = false }
}

async function saveRule() {
  saving.value = true
  error.value = ''
  try {
    await api.adminAddRule({ title: ruleForm.title.trim(), text: ruleForm.text.trim() })
    ruleForm.title = ''; ruleForm.text = ''
    await loadKnowledge(); await loadOverview()
    notify('规则已保存')
  } catch (e) { error.value = e.message } finally { saving.value = false }
}

async function removeSql(item) {
  if (!window.confirm(`删除知识样例「${item.question}」？`)) return
  try {
    await api.adminDeleteSql(item.id)
    await loadKnowledge(); await loadOverview()
    notify('已删除')
  } catch (e) { error.value = e.message }
}

async function removeRule(item) {
  if (!window.confirm(`删除规则「${item.title}」？`)) return
  try {
    await api.adminDeleteRule(item.id)
    await loadKnowledge(); await loadOverview()
    notify('已删除')
  } catch (e) { error.value = e.message }
}

async function openSession(sid) {
  selectedSid.value = sid
  error.value = ''
  try {
    history.value = (await api.adminHistory(sid)).history || []
  } catch (e) { error.value = e.message }
}

async function saveFromMessage(h) {
  saving.value = true
  error.value = ''
  try {
    await api.adminFromMessage({ message_id: h.id })
    await loadKnowledge(); await loadOverview()
    notify('已从会话收录到知识库')
  } catch (e) { error.value = e.message } finally { saving.value = false }
}

async function rebuild() {
  rebuilding.value = true
  error.value = ''
  try {
    await api.rebuildIndex()
    await loadOverview()
    notify('向量索引已重建')
  } catch (e) { error.value = e.message } finally { rebuilding.value = false }
}

watch(tab, async (v) => {
  error.value = ''
  if (v === 'sessions' && !sessions.value.length) {
    try { await loadSessions() } catch (e) { error.value = e.message }
  }
})

onMounted(refresh)
</script>
