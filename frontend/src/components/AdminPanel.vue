<template>
  <div class="adm-shell">
    <aside class="adm-sider">
      <template v-for="g in navGroups" :key="g.title">
        <div class="adm-sider-title" :class="{ mt: g.mt }">{{ g.title }}</div>
        <button v-for="n in g.items" :key="n.key" class="adm-nav"
                :class="{ active: tab === n.key }" @click="switchTab(n.key)">
          <span class="dot"></span>
          <span>{{ n.label }}</span>
          <span class="cnt" v-if="n.count">{{ n.count }}</span>
        </button>
      </template>
    </aside>

    <section class="adm-main">
      <!-- ============ 运行总览 ============ -->
      <div class="adm-screen" :class="{ on: tab === 'overview' }">
        <div class="adm-page-head">
          <div>
            <h1>运行总览</h1>
            <p>平台管理，仅管理员可达；所有变更留痕在 knowledge/ 与 git</p>
          </div>
          <div class="right">
            <span class="adm-badge teal">内核 v{{ overview?.version || 'dev' }}</span>
            <span class="adm-badge" :class="chainBadges">{{ chainLabel }}</span>
          </div>
        </div>

        <div class="adm-grid adm-g4" style="margin-bottom:14px">
          <div class="adm-card adm-pad adm-kpi">
            <div class="n">{{ overview?.sessions ?? 0 }}</div><div class="l">会话总数（本实例）</div>
          </div>
          <div class="adm-card adm-pad adm-kpi">
            <div class="n">{{ pct(overview?.metrics?.success_rate) }}</div><div class="l">成功率（近 {{ overview?.metrics?.traces ?? 0 }} 条 trace）</div>
          </div>
          <div class="adm-card adm-pad adm-kpi">
            <div class="n">{{ ms(overview?.metrics?.latency_ms?.p50) }}</div><div class="l">P50（单轮问答端到端）</div>
          </div>
          <div class="adm-card adm-pad adm-kpi">
            <div class="n">{{ ms(overview?.metrics?.latency_ms?.p95) }}</div><div class="l">P95（单轮问答端到端）</div>
          </div>
        </div>

        <div class="adm-grid" style="grid-template-columns:1.55fr 1fr;margin-bottom:14px;align-items:start">
          <div class="adm-card adm-pad">
            <div class="adm-between" style="margin-bottom:14px">
              <div class="adm-h2" style="margin:0">组件健康</div>
              <span class="adm-tiny adm-muted">实时</span>
            </div>
            <div class="adm-hbar">
              <div class="adm-hrow">
                <span class="grow">模型网关：主模型</span>
                <b class="adm-mono">{{ overview?.llm_chain?.[0]?.model || '未配置' }}</b>
                <span class="adm-badge" :class="overview?.llm_chain?.[0]?.ready ? 'teal' : 'amber'">
                  {{ overview?.llm_chain?.[0]?.ready ? '就绪' : '缺 key' }}</span>
              </div>
              <div class="adm-track"><i :style="bar(overview?.llm_chain?.[0]?.ready ? 92 : 12, overview?.llm_chain?.[0]?.ready)"></i></div>
            </div>
            <div class="adm-hbar">
              <div class="adm-hrow">
                <span class="grow">模型网关：兜底</span>
                <b class="adm-mono">{{ overview?.llm_chain?.[1]?.model || '未配置' }}</b>
                <span class="adm-badge" :class="overview?.llm_chain?.[1]?.ready ? 'teal' : 'amber'">
                  {{ overview?.llm_chain?.[1]?.ready ? '就绪' : '未配置' }}</span>
              </div>
              <div class="adm-track"><i :style="bar(overview?.llm_chain?.[1]?.ready ? 60 : 6, overview?.llm_chain?.[1]?.ready)"></i></div>
            </div>
            <div class="adm-hbar">
              <div class="adm-hrow">
                <span class="grow">向量索引</span>
                <b>{{ overview?.status?.indexed_tables ?? 0 }} / {{ overview?.status?.table_count ?? 0 }} 表</b>
                <span class="adm-badge" :class="overview?.status?.index_mode === 'vector' ? 'teal' : 'amber'">
                  {{ overview?.status?.index_mode === 'vector' ? '向量' : '关键词' }}</span>
              </div>
              <div class="adm-track"><i :style="bar(indexPct, overview?.status?.index_mode === 'vector')"></i></div>
            </div>
            <div class="adm-hbar">
              <div class="adm-hrow">
                <span class="grow">语义指标层</span>
                <b>{{ overview?.status?.semantic_metrics ?? 0 }} 个指标</b>
                <span class="adm-badge" :class="overview?.status?.semantic_error ? 'rose' : 'teal'">
                  {{ overview?.status?.semantic_error ? '异常' : '正常' }}</span>
              </div>
              <div class="adm-track"><i :style="bar(overview?.status?.semantic_metrics ? 88 : 8, !overview?.status?.semantic_error)"></i></div>
            </div>
            <div class="adm-hbar" style="margin-bottom:0">
              <div class="adm-hrow">
                <span class="grow">文件知识库</span>
                <b>{{ overview?.knowledge?.sql ?? 0 }} 个样例，{{ overview?.knowledge?.rules ?? 0 }} 条规则</b>
                <span class="adm-badge" :class="overview?.knowledge?.sql ? 'teal' : 'amber'">
                  {{ overview?.knowledge?.sql ? '已沉淀' : '待沉淀' }}</span>
              </div>
              <div class="adm-track"><i :style="bar(overview?.knowledge?.sql ? 60 : 10, !!overview?.knowledge?.sql)"></i></div>
            </div>
          </div>

          <div class="adm-card adm-pad">
            <div class="adm-between" style="margin-bottom:12px">
              <div class="adm-h2" style="margin:0">待办与告警</div>
              <span class="adm-tiny adm-muted">{{ alerts.length }} 项</span>
            </div>
            <div v-for="(a, i) in alerts" :key="i" class="adm-alert" :class="a.level">
              <b>{{ a.tag }}</b><span>{{ a.text }}</span>
            </div>
            <div v-if="!alerts.length" class="adm-alert teal"><b>正常</b><span>模型链路、索引、语义层与知识库均无异常</span></div>
          </div>
        </div>

        <div class="adm-grid" style="grid-template-columns:1fr 1fr 1fr;margin-bottom:14px;align-items:start">
          <div class="adm-card adm-pad">
            <div class="adm-between" style="margin-bottom:8px">
              <div class="adm-h2" style="margin:0">最近 Trace</div>
              <span class="adm-tiny adm-muted">{{ overview?.metrics?.traces ?? 0 }} 条</span>
            </div>
            <div v-for="t in overview?.recent_traces || []" :key="t.trace_id" class="adm-rec">
              <span class="adm-dot-s" :style="t.status === 'ok' ? 'background:#0f9d58' : 'background:#d97706'"></span>
              <span>{{ t.trace_id }}</span>
              <span class="t">{{ ms(t.duration_ms) }}</span>
            </div>
            <div v-if="!(overview?.recent_traces || []).length" class="adm-empty">
              <div class="t">还没有 trace</div>
              <div class="s">服务重启后，新一轮提问会在这里留下完整工具轨迹</div>
            </div>
          </div>

          <div class="adm-card adm-pad">
            <div class="adm-h2">生效配置快照</div>
            <dl class="adm-kv">
              <dt>Agent</dt><dd>{{ overview?.status?.agent_mode }}（最多 {{ overview?.status?.max_llm_calls }} 次 LLM）</dd>
              <dt>数据库</dt><dd>{{ overview?.status?.db_dialect }}（只读）</dd>
              <dt>Embedding</dt><dd>{{ overview?.status?.emb_model }}</dd>
              <dt>知识库路径</dt><dd class="adm-mono">{{ overview?.knowledge?.path }}</dd>
              <dt>结果上限</dt><dd>{{ overview?.status?.max_rows }} 行</dd>
            </dl>
            <div class="adm-divider"></div>
            <div class="adm-hint">配置写在 .env，改动后重启服务；知识与规则改动即时生效。</div>
          </div>

          <div class="adm-card adm-pad">
            <div class="adm-between" style="margin-bottom:6px">
              <div class="adm-h2" style="margin:0">账号与角色</div>
              <span class="adm-tiny adm-muted">{{ (overview?.users || []).length }} 个</span>
            </div>
            <div v-for="u in overview?.users || []" :key="u.username" class="adm-list-card" style="border-top:1px solid var(--border)">
              <span class="adm-pill">{{ u.username }}</span>
              <span class="grow"></span>
              <span class="adm-badge" :class="u.role === 'admin' ? 'teal' : 'sky'">{{ u.role }}</span>
            </div>
            <div class="adm-hint" style="margin-top:10px">账号在 .env 的 AUTH_USERS 中配置；普通用户看不到本页。</div>
          </div>
        </div>

        <div class="adm-grid" style="grid-template-columns:1fr 380px;align-items:start">
          <div class="adm-card">
            <div class="adm-pad adm-between">
              <div class="adm-h2" style="margin:0">最近查询明细</div>
              <span class="adm-tiny adm-muted">Trace 包含每一步工具调用与 token</span>
            </div>
            <div class="adm-table">
              <table>
                <thead><tr><th>Trace</th><th>状态</th><th>耗时</th><th>LLM 调用</th><th>Token</th><th>开始时间</th></tr></thead>
                <tbody>
                  <tr v-for="t in overview?.recent_traces || []" :key="t.trace_id">
                    <td class="adm-mono">{{ t.trace_id }}</td>
                    <td><span class="adm-badge" :class="t.status === 'ok' ? 'teal' : 'amber'">{{ t.status }}</span></td>
                    <td class="n">{{ ms(t.duration_ms) }}</td>
                    <td class="n">{{ t.llm_calls }}</td>
                    <td class="n">{{ t.prompt_tokens || 0 }} / {{ t.completion_tokens || 0 }}</td>
                    <td>{{ time(t.started_at) }}</td>
                  </tr>
                  <tr v-if="!(overview?.recent_traces || []).length"><td colspan="6" class="adm-hint">暂无记录</td></tr>
                </tbody>
              </table>
            </div>
          </div>

          <div class="adm-card adm-pad">
            <div class="adm-h2">本轮可做的事</div>
            <div class="adm-alert teal" style="flex-direction:column;gap:4px">
              <b>知识沉淀</b>
              <span>在「会话回放」把验证过的回答收录为 knowledge/sql 样例，下一轮自动作为 few-shot 召回。</span>
            </div>
            <div class="adm-alert teal" style="flex-direction:column;gap:4px">
              <b>口径治理</b>
              <span>业务规则写进 knowledge/rules，优先级高于 semantic/metrics.yaml 的默认口径。</span>
            </div>
            <div class="adm-divider"></div>
            <div class="adm-hint">管理端改动只写文件，不改数据库；回滚用 git revert 或删除对应 md。</div>
          </div>
        </div>
      </div>

      <!-- ============ 模型网关 ============ -->
      <div class="adm-screen" :class="{ on: tab === 'model' }">
        <div class="adm-page-head">
          <div>
            <h1>模型网关</h1>
            <p>主模型优先，失败自动切兜底；trace 记录实际命中的 provider</p>
          </div>
          <div class="right">
            <button class="adm-btn sm" :disabled="rebuilding" @click="rebuild">
              {{ rebuilding ? '重建中…' : '重建向量索引' }}</button>
          </div>
        </div>

        <div class="adm-card adm-pad" style="margin-bottom:14px">
          <div class="adm-h2">模型链路</div>
          <div class="adm-table">
            <table>
              <thead><tr><th>顺序</th><th>角色</th><th>Provider</th><th>模型</th><th>Base URL</th><th>状态</th></tr></thead>
              <tbody>
                <tr v-for="(p, i) in overview?.llm_chain || []" :key="p.provider + p.model">
                  <td class="adm-mono">{{ i + 1 }}</td>
                  <td><span class="adm-badge" :class="i === 0 ? 'teal' : 'sky'">{{ i === 0 ? '主模型' : '兜底' }}</span></td>
                  <td>{{ p.provider }}</td>
                  <td class="adm-mono">{{ p.model }}</td>
                  <td class="adm-mono">{{ p.base_url }}</td>
                  <td><span class="adm-badge" :class="p.ready ? 'teal' : 'amber'">{{ p.ready ? '就绪' : '缺 key' }}</span></td>
                </tr>
                <tr v-if="!(overview?.llm_chain || []).length"><td colspan="6" class="adm-hint">未配置模型链路</td></tr>
              </tbody>
            </table>
          </div>
          <div class="adm-hint" style="margin-top:10px">
            兜底模型只允许使用 OpenRouter 的 :free 模型；主模型 429 / 超时 / 空返回时自动切换，两次都失败才会提示用户稍后重试。
          </div>
        </div>

        <div class="adm-grid adm-g2">
          <div class="adm-card adm-pad">
            <div class="adm-h2">Agent 参数</div>
            <dl class="adm-kv">
              <dt>运行模式</dt><dd>{{ overview?.status?.agent_mode }}（toolloop / workflow 自动降级）</dd>
              <dt>LLM 预算</dt><dd>单轮最多 {{ overview?.status?.max_llm_calls }} 次（含 1 次洞察）</dd>
              <dt>护栏</dt><dd>{{ overview?.status?.guard_enabled ? '开启（拒答 + 引导）' : '关闭' }}</dd>
              <dt>自动结论</dt><dd>{{ overview?.status?.auto_insight ? '开启' : '关闭' }}，追问 {{ overview?.status?.followup_count }} 条</dd>
              <dt>空结果重试</dt><dd>{{ overview?.status?.empty_result_retry ? '开启' : '关闭' }}</dd>
              <dt>记忆</dt><dd>{{ overview?.status?.memory_enabled ? '开启' : '关闭' }}</dd>
            </dl>
          </div>
          <div class="adm-card adm-pad">
            <div class="adm-h2">数据与索引</div>
            <dl class="adm-kv">
              <dt>数据源</dt><dd>{{ overview?.status?.db_dialect }}（只读闸门 + 超时）</dd>
              <dt>表数量</dt><dd>{{ overview?.status?.table_count }} 张</dd>
              <dt>索引模式</dt><dd>{{ overview?.status?.index_mode }}（{{ overview?.status?.indexed_tables }} 条向量）</dd>
              <dt>Embedding</dt><dd>{{ overview?.status?.emb_model }}</dd>
              <dt>索引错误</dt><dd>{{ overview?.status?.index_error || '无' }}</dd>
              <dt>工具</dt><dd class="adm-mono">{{ (overview?.status?.tools || []).join(' / ') }}</dd>
            </dl>
          </div>
        </div>
      </div>

      <!-- ============ 知识库 ============ -->
      <div class="adm-screen" :class="{ on: tab === 'knowledge' }">
        <div class="adm-page-head">
          <div>
            <h1>知识库</h1>
            <p>markdown 是唯一真相：knowledge/sql 存确认过的样例，knowledge/rules 存业务规则</p>
          </div>
          <div class="right">
            <span class="adm-badge teal">{{ knowledge?.stats?.sql ?? 0 }} 样例</span>
            <span class="adm-badge sky">{{ knowledge?.stats?.rules ?? 0 }} 规则</span>
          </div>
        </div>

        <div class="adm-grid adm-g2" style="margin-bottom:14px;align-items:start">
          <div class="adm-card adm-pad">
            <div class="adm-h2">收录一条 NL → SQL 样例</div>
            <div class="adm-field">
              <label>自然语言问题</label>
              <input v-model="sqlForm.question" class="adm-input" placeholder="近 12 个月每月销售额趋势" />
            </div>
            <div class="adm-field">
              <label>SQL（只允许只读查询）</label>
              <textarea v-model="sqlForm.sql" class="adm-area" rows="5"
                        placeholder="SELECT ... FROM orders GROUP BY ..."></textarea>
            </div>
            <div class="adm-field">
              <label>涉及表（逗号分隔，可留空）</label>
              <input v-model="sqlForm.tables" class="adm-input" placeholder="orders, order_items" />
            </div>
            <div class="adm-field">
              <label>备注 / 口径说明</label>
              <input v-model="sqlForm.notes" class="adm-input" placeholder="为什么这样写（可选）" />
            </div>
            <button class="adm-btn primary" :disabled="saving || !sqlForm.question.trim() || !sqlForm.sql.trim()" @click="saveSql">
              {{ saving ? '保存中…' : '保存为正式样例' }}
            </button>
            <div class="adm-hint" style="margin-top:8px">保存后写入 knowledge/sql/*.md，可提交 Git、可 review、可回滚。</div>
          </div>

          <div class="adm-card adm-pad">
            <div class="adm-h2">新增业务规则</div>
            <div class="adm-field">
              <label>规则标题</label>
              <input v-model="ruleForm.title" class="adm-input" placeholder="有效成交口径" />
            </div>
            <div class="adm-field">
              <label>规则内容</label>
              <textarea v-model="ruleForm.text" class="adm-area" rows="5"
                        placeholder="统计有效成交时排除 cancelled / refunded 订单"></textarea>
            </div>
            <button class="adm-btn primary" :disabled="saving || !ruleForm.text.trim()" @click="saveRule">
              {{ saving ? '保存中…' : '保存规则' }}
            </button>
            <div class="adm-hint" style="margin-top:8px">规则每轮注入 system prompt，优先级高于 semantic/metrics.yaml 的默认口径。</div>
          </div>
        </div>

        <div class="adm-card" style="margin-bottom:14px">
          <div class="adm-pad adm-between">
            <div class="adm-h2" style="margin:0">正式样例</div>
            <span class="adm-tiny adm-muted">召回时优先于自动 few-shot</span>
          </div>
          <div class="adm-table">
            <table>
              <thead><tr><th>问题</th><th>SQL</th><th>涉及表</th><th>来源</th><th></th></tr></thead>
              <tbody>
                <tr v-for="item in knowledge?.sql || []" :key="item.id">
                  <td>{{ item.question }}</td>
                  <td class="sql adm-mono">{{ item.sql }}</td>
                  <td class="adm-mono">{{ (item.tables || []).join(', ') || '—' }}</td>
                  <td><span class="adm-pill">{{ item.source || 'admin' }}</span></td>
                  <td><button class="adm-btn sm" @click="removeSql(item)">删除</button></td>
                </tr>
                <tr v-if="!(knowledge?.sql || []).length">
                  <td colspan="5">
                    <div class="adm-empty">
                      <div class="t">还没有正式样例</div>
                      <div class="s">在「会话回放」把一条验证过的回答收录进来，或在左侧手写一条</div>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="adm-card">
          <div class="adm-pad adm-between">
            <div class="adm-h2" style="margin:0">业务规则</div>
            <span class="adm-tiny adm-muted">knowledge/rules/*.md</span>
          </div>
          <div v-for="item in knowledge?.rules || []" :key="item.id" class="adm-list-card">
            <div class="grow">
              <b>{{ item.title }}</b>
              <div class="adm-tiny adm-muted" style="margin-top:4px;white-space:pre-wrap">{{ item.text }}</div>
              <div class="adm-tiny adm-muted adm-mono" style="margin-top:4px">{{ item.id }}　{{ item.created }}</div>
            </div>
            <button class="adm-btn sm" @click="removeRule(item)">删除</button>
          </div>
          <div v-if="!(knowledge?.rules || []).length" class="adm-empty">
            <div class="t">还没有自定义规则</div>
            <div class="s">模型目前只用 semantic/metrics.yaml 里的默认口径</div>
          </div>
        </div>
      </div>

      <!-- ============ 语义规则 ============ -->
      <div class="adm-screen" :class="{ on: tab === 'semantic' }">
        <div class="adm-page-head">
          <div>
            <h1>语义指标</h1>
            <p>受治理指标层（MDL）：口径、标准 JOIN、方言日期函数</p>
          </div>
          <div class="right">
            <span class="adm-badge teal">{{ (semantic?.metrics || []).length }} 个指标</span>
            <span class="adm-badge sky">{{ (semantic?.joins || []).length }} 条 JOIN</span>
          </div>
        </div>

        <div class="adm-card adm-pad" style="margin-bottom:14px">
          <div class="adm-h2">业务口径规则</div>
          <ul style="margin:0;padding-left:18px;font-size:12.5px;line-height:2;color:var(--muted)">
            <li v-for="(r, i) in semantic?.business_rules || []" :key="i">{{ r }}</li>
          </ul>
          <div v-if="!(semantic?.business_rules || []).length" class="adm-hint">未配置业务规则</div>
        </div>

        <div class="adm-card" style="margin-bottom:14px">
          <div class="adm-pad adm-between">
            <div class="adm-h2" style="margin:0">受治理指标</div>
            <span class="adm-tiny adm-muted">来源：backend/semantic/metrics.yaml</span>
          </div>
          <div class="adm-table">
            <table>
              <thead><tr><th>指标</th><th>表达式</th><th>有效过滤</th><th>单位</th></tr></thead>
              <tbody>
                <tr v-for="m in semantic?.metrics || []" :key="m.id">
                  <td><b>{{ m.name }}</b><div class="adm-mono adm-tiny adm-muted">{{ m.id }}</div></td>
                  <td class="adm-mono">{{ m.expr }}</td>
                  <td class="adm-mono">{{ m.valid_filter || '—' }}</td>
                  <td>{{ m.unit || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="adm-card adm-pad">
          <div class="adm-h2">标准 JOIN</div>
          <div v-for="(j, i) in semantic?.joins || []" :key="i" class="adm-mono adm-tiny"
               style="padding:6px 0;border-bottom:1px solid #f1f5f9">{{ j.on }}</div>
          <div v-if="!(semantic?.joins || []).length" class="adm-hint">未配置</div>
        </div>
      </div>

      <!-- ============ 会话回放 ============ -->
      <div class="adm-screen" :class="{ on: tab === 'sessions' }">
        <div class="adm-page-head">
          <div>
            <h1>会话回放</h1>
            <p>全部 owner 的会话与回答；验证过的回答可一键收录进知识库</p>
          </div>
          <div class="right">
            <span class="adm-badge teal">{{ sessions.length }} 个会话</span>
          </div>
        </div>

        <div class="adm-grid" style="grid-template-columns:300px 1fr;align-items:start">
          <div class="adm-card adm-scroll" style="max-height:70vh">
            <div v-for="s in sessions" :key="s.session_id" class="adm-list-card"
                 style="cursor:pointer" @click="openSession(s.session_id)">
              <div class="grow">
                <b class="adm-truncate">{{ s.title || '新会话' }}</b>
                <div class="adm-tiny adm-muted">{{ s.owner || '未归属' }}　{{ s.updated_at }}</div>
              </div>
              <span class="adm-row-arrow">›</span>
            </div>
            <div v-if="!sessions.length" class="adm-empty">
              <div class="t">暂无会话</div>
              <div class="s">用户在问答端提问后，这里会记录 owner、时间与最终 SQL</div>
            </div>
          </div>

          <div class="adm-card adm-pad" style="min-height:320px">
            <div class="adm-between" style="margin-bottom:12px">
              <div class="adm-h2" style="margin:0">会话详情</div>
              <span class="adm-tiny adm-muted">{{ selectedSid || '未选择' }}</span>
            </div>
            <div v-if="!selectedSid" class="adm-empty">
              <div class="t">选择左侧会话</div>
              <div class="s">可以查看消息、SQL，并把验证过的回答收录进知识库</div>
            </div>
            <div v-for="h in history" :key="h.id" style="padding:11px 0;border-bottom:1px solid #f1f5f9">
              <div class="adm-between">
                <span class="adm-badge" :class="h.role === 'user' ? 'sky' : 'teal'">
                  {{ h.role === 'user' ? '用户' : 'Agent' }}</span>
                <span class="adm-tiny adm-muted adm-mono">#{{ h.id }}　{{ h.created_at }}</span>
              </div>
              <div style="margin:8px 0;font-size:13px;line-height:1.7;white-space:pre-wrap">{{ h.content || '（无正文）' }}</div>
              <pre v-if="h.sql" class="adm-pre">{{ h.sql }}</pre>
              <div v-if="h.role === 'assistant' && h.sql" style="margin-top:8px">
                <button class="adm-btn sm" :disabled="saving" @click="saveFromMessage(h)">收录为知识样例</button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ============ 权限账号 ============ -->
      <div class="adm-screen" :class="{ on: tab === 'access' }">
        <div class="adm-page-head">
          <div>
            <h1>权限与账号</h1>
            <p>两级角色：admin 可进管理端，user 只做问答</p>
          </div>
          <div class="right">
            <span class="adm-badge teal">{{ (overview?.users || []).length }} 个账号</span>
          </div>
        </div>

        <div class="adm-card" style="margin-bottom:14px">
          <div class="adm-pad adm-between">
            <div class="adm-h2" style="margin:0">账号列表</div>
            <span class="adm-tiny adm-muted">配置来源：.env 的 AUTH_USERS（user:pass:role）</span>
          </div>
          <div class="adm-table">
            <table>
              <thead><tr><th>用户名</th><th>角色</th><th>可访问</th></tr></thead>
              <tbody>
                <tr v-for="u in overview?.users || []" :key="u.username">
                  <td class="adm-mono">{{ u.username }}</td>
                  <td><span class="adm-badge" :class="u.role === 'admin' ? 'teal' : 'sky'">{{ u.role }}</span></td>
                  <td class="adm-muted">{{ u.role === 'admin' ? '问答 + 管理后台 + 知识库写入' : '仅问答；管理端 API 返回 403' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="adm-grid adm-g2">
          <div class="adm-card adm-pad">
            <div class="adm-h2">权限矩阵</div>
            <div class="adm-table">
              <table>
                <thead><tr><th>能力</th><th>admin</th><th>user</th></tr></thead>
                <tbody>
                  <tr v-for="c in capability" :key="c.name">
                    <td>{{ c.name }}</td>
                    <td><span class="adm-badge teal">允许</span></td>
                    <td><span class="adm-badge" :class="c.user ? 'teal' : 'rose'">{{ c.user ? '允许' : '禁止' }}</span></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div class="adm-card adm-pad">
            <div class="adm-h2">登录安全</div>
            <div class="adm-alert teal" style="flex-direction:column;gap:4px">
              <b>登录失败按 IP 限流</b>
              <span>1 分钟内失败 8 次即封禁，Basic 与 token 两个入口共用同一计数。</span>
            </div>
            <div class="adm-alert teal" style="flex-direction:column;gap:4px">
              <b>token 绑定账号表版本</b>
              <span>改密码、增删账号或轮换 SECRET_KEY 后，已签发的旧 token 立即失效。</span>
            </div>
            <div class="adm-alert amber" style="flex-direction:column;gap:4px">
              <b>密码写在 .env</b>
              <span>密码不要含逗号；生产请用强密码，.env 权限 600 且不进 Git。</span>
            </div>
          </div>
        </div>
      </div>

      <div class="adm-foot">Text-to-SQL Agent 管理后台，变更留痕在 knowledge/ 与 git</div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api'

const emit = defineEmits(['toast', 'open-chat'])

const overview = ref(null)
const knowledge = ref(null)
const semantic = ref(null)
const sessions = ref([])
const history = ref([])
const selectedSid = ref('')
const tab = ref('overview')
const saving = ref(false)
const rebuilding = ref(false)
const error = ref('')
const sqlForm = reactive({ question: '', sql: '', tables: '', notes: '' })
const ruleForm = reactive({ title: '', text: '' })

const capability = [
  { name: '问答 / SSE 流式查询', user: true },
  { name: '查看自己的会话与结果', user: true },
  { name: '查看全部用户会话', user: false },
  { name: '写入知识库（样例 / 规则）', user: false },
  { name: '查看语义指标与 Trace', user: false },
  { name: '重建向量索引', user: false },
]

const navGroups = computed(() => [
  {
    title: '概览', items: [
      { key: 'overview', label: '运行总览' },
      { key: 'model', label: '模型网关', count: (overview?.value?.llm_chain || []).length || '' },
    ],
  },
  {
    title: '知识与口径', mt: true, items: [
      { key: 'knowledge', label: '知识库', count: overview?.value?.knowledge?.sql || '' },
      { key: 'semantic', label: '语义指标', count: overview?.value?.status?.semantic_metrics || '' },
    ],
  },
  {
    title: '运营与治理', mt: true, items: [
      { key: 'sessions', label: '会话回放', count: sessions.value.length || '' },
      { key: 'access', label: '权限与账号', count: (overview?.value?.users || []).length || '' },
    ],
  },
])

const indexPct = computed(() => {
  const s = overview.value?.status
  if (!s || !s.table_count) return 0
  return Math.round((s.indexed_tables / s.table_count) * 100)
})

const chainLabel = computed(() => {
  const c = overview.value?.llm_chain || []
  if (!c.length) return '未配置模型'
  if (!c[0]?.ready) return '主模型缺 key'
  return c.length > 1 ? '主备就绪' : '仅主模型'
})
const chainBadges = computed(() => {
  const c = overview.value?.llm_chain || []
  if (!c.length || !c[0]?.ready) return 'amber'
  return c.length > 1 ? 'teal' : 'sky'
})

const alerts = computed(() => {
  const out = []
  const st = overview.value?.status || {}
  const chain = overview.value?.llm_chain || []
  if (!chain.length) out.push({ level: 'rose', tag: '模型', text: '未配置任何文本模型，服务会拒绝启动' })
  else if (!chain[0]?.ready) out.push({ level: 'rose', tag: '模型', text: '主模型缺 key，提问会直接失败' })
  if (chain.length < 2) out.push({ level: 'amber', tag: '兜底', text: '未配置兜底模型，主模型故障时无可用降级' })
  if (st.index_error) out.push({ level: 'rose', tag: '索引', text: st.index_error })
  if (st.index_mode !== 'vector') out.push({ level: 'amber', tag: '索引', text: '当前按关键词选表，向量索引未就绪' })
  if (st.semantic_error) out.push({ level: 'rose', tag: '语义', text: st.semantic_error })
  if (!overview.value?.knowledge?.sql) out.push({ level: 'amber', tag: '知识', text: '知识库还没有正式样例，few-shot 只靠自动积累' })
  return out
})

function notify(msg) { emit('toast', msg) }
function pct(v) { return v == null ? 'n/a' : `${Math.round(Number(v) * 1000) / 10}%` }
function ms(v) { return v == null ? 'n/a' : `${Math.round(Number(v))} ms` }
function time(ts) {
  if (!ts) return 'n/a'
  const d = new Date(Number(ts) * 1000)
  return Number.isNaN(d.getTime()) ? 'n/a' : d.toLocaleString()
}
function bar(pctValue, ok) {
  return { width: `${Math.max(4, Math.min(100, pctValue || 0))}%`, background: ok ? '#0f9d58' : '#d97706' }
}
function csv(s) { return String(s || '').split(',').map(x => x.trim()).filter(Boolean) }

async function loadOverview() { overview.value = await api.adminOverview() }
async function loadKnowledge() { knowledge.value = await api.adminKnowledge() }
async function loadSemantic() { semantic.value = await api.semantic() }
async function loadSessions() { sessions.value = (await api.adminSessions()).sessions || [] }

async function refresh() {
  error.value = ''
  try {
    await Promise.all([loadOverview(), loadKnowledge(), loadSemantic()])
  } catch (e) { error.value = e.message }
}

function switchTab(key) {
  tab.value = key
  error.value = ''
  if (key === 'sessions' && !sessions.value.length) {
    loadSessions().catch(e => { error.value = e.message })
  }
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

watch(tab, () => { if (tab.value === 'sessions' && !sessions.value.length) loadSessions().catch(() => {}) })
onMounted(refresh)
</script>
