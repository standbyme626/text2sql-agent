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
      <!-- ================= 运行总览 ================= -->
      <div class="adm-screen" :class="{ on: tab === 'overview' }">
        <div class="adm-page-head">
          <div>
            <h1>运行总览</h1>
            <p>平台管理，仅管理员可达；所有配置变更留痕在 knowledge/ 与 git</p>
          </div>
          <div class="right">
            <span class="adm-badge teal">内核 v{{ overview?.version || '—' }}</span>
            <span class="adm-badge" :class="chainBadges">{{ chainLabel }}</span>
          </div>
        </div>

        <div class="adm-grid adm-g4" style="margin-bottom:14px">
          <div class="adm-card adm-pad adm-kpi">
            <div class="n">{{ overview?.sessions ?? 0 }}</div><div class="l">会话总数（本实例）</div>
          </div>
          <div class="adm-card adm-pad adm-kpi">
            <div class="n">{{ pct(overview?.metrics?.success_rate) }}</div>
            <div class="l">成功率（近 {{ overview?.metrics?.traces ?? 0 }} 条 trace）</div>
          </div>
          <div class="adm-card adm-pad adm-kpi">
            <div class="n">{{ ms(overview?.metrics?.latency_ms?.p50) }}</div><div class="l">P50 延迟</div>
          </div>
          <div class="adm-card adm-pad adm-kpi">
            <div class="n">{{ ms(overview?.metrics?.latency_ms?.p95) }}</div><div class="l">P95 延迟</div>
          </div>
        </div>

        <div class="adm-grid adm-cols-main">
          <div class="adm-card adm-pad">
            <div class="adm-between" style="margin-bottom:12px">
              <div class="adm-h2" style="margin:0">近 14 天调用趋势</div>
              <span class="adm-tiny adm-muted">单位：次 / 毫秒</span>
            </div>
            <TrendChart :points="trendPoints" />
            <div class="adm-row" style="gap:20px;margin-top:8px">
              <span class="adm-tiny adm-muted">成功 {{ sumOf('ok') }} 次</span>
              <span class="adm-tiny adm-muted">失败 {{ sumOf('failed') }} 次</span>
              <span class="adm-tiny adm-muted">拒答 {{ sumOf('refused') }} 次</span>
              <span class="adm-tiny adm-muted">Token {{ sumOf('prompt_tokens') + sumOf('completion_tokens') }}</span>
            </div>
          </div>

          <div class="adm-card adm-pad">
            <div class="adm-between" style="margin-bottom:12px">
              <div class="adm-h2" style="margin:0">告警与 SLO</div>
              <span class="adm-tiny adm-muted">{{ (overview?.alerts || []).length }} 条告警</span>
            </div>
            <div v-for="(a, i) in overview?.alerts || []" :key="i" class="adm-alert" :class="a.level">
              <b>{{ a.name }}</b>
              <span>{{ a.value }} {{ a.op }} {{ a.threshold }} · {{ a.desc }}</span>
            </div>
            <div v-if="!(overview?.alerts || []).length" class="adm-alert teal">
              <b>正常</b><span>所有告警规则均未命中</span>
            </div>
            <div class="adm-divider"></div>
            <dl class="adm-kv">
              <dt>可用性</dt>
              <dd>{{ slo?.availability == null ? '暂无样本' : slo.availability + '%' }}（目标 {{ slo?.availability_target }}%）</dd>
              <dt>P95</dt><dd>{{ ms(slo?.latency_p95_ms) }}（目标 {{ ms(slo?.latency_target_ms) }}）</dd>
              <dt>错误预算</dt>
              <dd>已用 {{ slo?.error_budget_used_pct }}%，剩余 {{ slo?.error_budget_remaining_pct }}%</dd>
            </dl>
          </div>
        </div>

        <div class="adm-grid adm-cols-3">
          <div class="adm-card adm-pad">
            <div class="adm-between" style="margin-bottom:8px">
              <div class="adm-h2" style="margin:0">模型用量与成本</div>
              <span class="adm-tiny adm-muted">${{ overview?.usage?.totals?.cost_usd ?? 0 }}</span>
            </div>
            <div v-for="u in overview?.usage?.providers || []" :key="u.target" class="adm-dist">
              <span class="nm adm-truncate">{{ u.target }}</span>
              <div class="tr"><i :style="{ width: barWidth(u.calls, overview?.usage?.totals?.calls), background: '#2563eb' }"></i></div>
              <b>{{ u.calls }}</b>
            </div>
            <div v-if="!(overview?.usage?.providers || []).length" class="adm-hint">暂无用量数据</div>
            <div class="adm-hint" style="margin-top:8px">
              输入 {{ overview?.usage?.totals?.prompt_tokens ?? 0 }} / 输出 {{ overview?.usage?.totals?.completion_tokens ?? 0 }} token
            </div>
          </div>

          <div class="adm-card adm-pad">
            <div class="adm-h2">失败分布</div>
            <div v-for="(v, k) in overview?.failures?.status || {}" :key="k" class="adm-dist">
              <span class="nm">{{ k }}</span>
              <div class="tr"><i :style="{ width: barWidth(v, overview?.metrics?.traces), background: k === 'ok' ? '#0f9d58' : '#dc2626' }"></i></div>
              <b>{{ v }}</b>
            </div>
            <div class="adm-divider"></div>
            <div class="adm-tiny adm-muted">工具失败原因</div>
            <div v-for="(v, k) in overview?.failures?.tool_errors || {}" :key="k" class="adm-tiny adm-muted"
                 style="padding:3px 0">· {{ k }}：{{ v }} 次</div>
            <div v-if="!(overview?.failures?.tool_errors || {}).length" class="adm-hint">无工具失败</div>
          </div>

          <div class="adm-card adm-pad">
            <div class="adm-between" style="margin-bottom:6px">
              <div class="adm-h2" style="margin:0">索引与知识</div>
              <span class="adm-tiny adm-muted">vector / keyword</span>
            </div>
            <dl class="adm-kv">
              <dt>选表模式</dt><dd>{{ overview?.status?.index_mode }}</dd>
              <dt>向量表数</dt><dd>{{ overview?.status?.indexed_tables }} / {{ overview?.status?.table_count }}</dd>
              <dt>索引文件</dt><dd class="adm-mono">{{ overview?.index?.detail?.size_kb ?? 'n/a' }} KB</dd>
              <dt>重建时间</dt><dd>{{ overview?.index?.detail?.built_at || 'n/a' }}</dd>
              <dt>Embedding</dt><dd>{{ overview?.status?.emb_model }}</dd>
              <dt>知识样例</dt><dd>{{ overview?.knowledge?.sql ?? 0 }} 个 / {{ overview?.knowledge?.rules ?? 0 }} 条规则</dd>
              <dt>审计条目</dt><dd>{{ overview?.audit_count ?? 0 }}</dd>
            </dl>
          </div>
        </div>
      </div>

      <!-- ================= 告警与 SLO ================= -->
      <div class="adm-screen" :class="{ on: tab === 'alerts' }">
        <div class="adm-page-head">
          <div>
            <h1>告警与 SLO</h1>
            <p>规则写在 backend/app/alerts.yaml，可在线改；阈值变更立即生效</p>
          </div>
          <div class="right">
            <span class="adm-badge" :class="alertsData?.fired?.length ? 'amber' : 'teal'">
              {{ alertsData?.fired?.length || 0 }} 条命中</span>
            <button class="adm-btn sm primary" :disabled="saving" @click="saveAlerts">保存规则</button>
          </div>
        </div>

        <div class="adm-grid adm-g2" style="margin-bottom:14px;align-items:start">
          <div class="adm-card adm-pad">
            <div class="adm-h2">服务等级目标</div>
            <dl class="adm-kv">
              <dt>可用性</dt>
              <dd>{{ alertsData?.slo?.availability == null ? '暂无样本' : alertsData.slo.availability + '%' }}
                / 目标 {{ alertsData?.slo?.availability_target }}%</dd>
              <dt>P95 延迟</dt>
              <dd>{{ ms(alertsData?.slo?.latency_p95_ms) }} / 目标 {{ ms(alertsData?.slo?.latency_target_ms) }}</dd>
              <dt>错误预算</dt>
              <dd>配额 {{ alertsData?.slo?.error_budget_pct }}%，已用 {{ alertsData?.slo?.error_budget_used_pct }}%</dd>
              <dt>样本量</dt><dd>{{ alertsData?.slo?.traces ?? 0 }} 条 trace</dd>
            </dl>
          </div>
          <div class="adm-card adm-pad">
            <div class="adm-h2">当前命中</div>
            <div v-for="(a, i) in alertsData?.fired || []" :key="i" class="adm-alert" :class="a.level">
              <b>{{ a.name }}</b><span>{{ a.metric }} {{ a.value }} {{ a.op }} {{ a.threshold }}</span>
            </div>
            <div v-if="!(alertsData?.fired || []).length" class="adm-alert teal">
              <b>正常</b><span>没有规则被触发</span>
            </div>
          </div>
        </div>

        <div class="adm-card">
          <div class="adm-pad adm-between">
            <div class="adm-h2" style="margin:0">规则</div>
            <span class="adm-tiny adm-muted">指标 / 比较符 / 阈值 / 级别 / 启用</span>
          </div>
          <div class="adm-table">
            <table>
              <thead><tr><th>名称</th><th>指标</th><th>比较</th><th>阈值</th><th>级别</th><th>启用</th></tr></thead>
              <tbody>
                <tr v-for="(r, i) in alertRules" :key="i">
                  <td><b>{{ r.name }}</b><div class="adm-tiny adm-muted">{{ r.desc }}</div></td>
                  <td class="adm-mono">{{ r.metric }}</td>
                  <td class="adm-mono">{{ r.op }}</td>
                  <td class="n"><input class="adm-input adm-num" type="number" v-model.number="r.threshold" /></td>
                  <td>
                    <select class="adm-input adm-num" v-model="r.level">
                      <option value="rose">rose</option><option value="amber">amber</option><option value="info">info</option>
                    </select>
                  </td>
                  <td><label class="adm-check"><input type="checkbox" v-model="r.enabled" /><span class="sr-only">启用 {{ r.name }}</span></label></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- ================= 未命中问题 ================= -->
      <div class="adm-screen" :class="{ on: tab === 'unmatched' }">
        <div class="adm-page-head">
          <div>
            <h1>未命中问题</h1>
            <p>护栏拒答、0 行、SQL 报错、未完成的提问；确认后收录进知识库</p>
          </div>
          <div class="right">
            <span class="adm-badge amber">{{ unmatched?.items?.length || 0 }} 条待处理</span>
            <button class="adm-btn sm" @click="loadUnmatched">刷新</button>
          </div>
        </div>

        <div class="adm-card">
          <div class="adm-table">
            <table>
              <thead><tr><th>问题</th><th>原因</th><th>时间</th><th>已有知识</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="it in unmatched?.items || []" :key="it.message_id">
                  <td>{{ it.question || '（无问题文本）' }}</td>
                  <td><span class="adm-badge" :class="reasonBadge(it.reason)">{{ reasonText(it.reason) }}</span></td>
                  <td class="adm-tiny adm-muted">{{ it.created_at }}</td>
                  <td class="adm-tiny adm-muted">
                    {{ (it.knowledge || []).map(k => k.question).join('；') || '无' }}
                  </td>
                  <td>
                    <button class="adm-btn sm" @click="promote(it)">收录为知识</button>
                  </td>
                </tr>
                <tr v-if="!(unmatched?.items || []).length">
                  <td colspan="5">
                    <div class="adm-empty">
                      <div class="t">没有被判定为未命中的问题</div>
                      <div class="s">拒答、0 行与执行失败都会出现在这里</div>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- ================= 检索调试 ================= -->
      <div class="adm-screen" :class="{ on: tab === 'debug' }">
        <div class="adm-page-head">
          <div>
            <h1>检索调试</h1>
            <p>单条问句的选表打分明细、指标编译计划与知识召回</p>
          </div>
        </div>

        <div class="adm-card adm-pad" style="margin-bottom:14px">
          <div class="adm-row" style="gap:10px">
            <input v-model="debugQuestion" class="adm-input" style="flex:1"
                   placeholder="输入问题，例如：近 12 个月每月销售额趋势" @keyup.enter="runDebug" />
            <button class="adm-btn primary" :disabled="debugging || !debugQuestion.trim()" @click="runDebug">
              {{ debugging ? '检索中…' : '检索' }}</button>
          </div>
        </div>

        <template v-if="debugResult">
          <div class="adm-grid adm-g2" style="margin-bottom:14px;align-items:start">
            <div class="adm-card adm-pad">
              <div class="adm-h2">指标编译计划</div>
              <div v-if="debugResult.plan?.matched" class="adm-alert teal" style="flex-direction:column;gap:4px">
                <b>命中指标：{{ debugResult.plan.name }}（{{ debugResult.plan.id }}）</b>
                <span class="adm-mono">{{ debugResult.plan.expr }}</span>
                <span v-if="debugResult.plan.valid_filter" class="adm-mono">过滤：{{ debugResult.plan.valid_filter }}</span>
                <span>涉及表：{{ (debugResult.plan.tables || []).join(', ') }}</span>
              </div>
              <div v-else class="adm-alert amber">
                <b>未命中</b><span>{{ debugResult.plan?.reason }}</span>
              </div>
            </div>
            <div class="adm-card adm-pad">
              <div class="adm-h2">知识召回</div>
              <div v-for="k in debugResult.knowledge_recall || []" :key="k.id" class="adm-knowledge">
                <b>{{ k.question }}</b>
                <pre class="adm-pre">{{ k.sql }}</pre>
                <span class="adm-badge sky">得分 {{ k.score }}</span>
              </div>
              <div v-if="!(debugResult.knowledge_recall || []).length" class="adm-hint">没有召回任何正式样例</div>
            </div>
          </div>

          <div class="adm-card">
            <div class="adm-pad adm-between">
              <div class="adm-h2" style="margin:0">选表打分（Top {{ (debugResult.tables || []).length }}）</div>
              <span class="adm-tiny adm-muted">索引模式：{{ debugResult.index_mode }}</span>
            </div>
            <div class="adm-table">
              <table>
                <thead><tr><th>表</th><th>中文名</th><th>业务域</th><th>总分</th><th>向量分</th><th>关键词分</th><th>命中列</th></tr></thead>
                <tbody>
                  <tr v-for="t in debugResult.tables || []" :key="t.name">
                    <td class="adm-mono">{{ t.name }}<span v-if="t.fk_added" class="adm-badge sky" style="margin-left:6px">外键补全</span></td>
                    <td>{{ t.cn }}</td>
                    <td class="adm-muted">{{ t.domain }}</td>
                    <td class="n">{{ t.score }}</td>
                    <td class="n">{{ t.vector_score }}</td>
                    <td class="n">{{ t.keyword_score }}</td>
                    <td class="adm-tiny adm-muted">
                      {{ (debugResult.matched_columns?.[t.name] || []).map(c => c.cn || c.name).join('、') || '—' }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>
        <div v-else class="adm-card adm-pad adm-empty">
          <div class="t">还没有检索记录</div>
          <div class="s">输入问题后可以看到每张表的向量分、关键词分与列级命中</div>
        </div>
      </div>

      <!-- ================= 质量评测 ================= -->
      <div class="adm-screen" :class="{ on: tab === 'eval' }">
        <div class="adm-page-head">
          <div>
            <h1>质量评测</h1>
            <p>golden 集执行准确率、失败分类与两次评测的 A/B 对比</p>
          </div>
          <div class="right">
            <select class="adm-input adm-num" v-model="evalMode">
              <option value="mock">mock（零额度）</option>
              <option value="real">real（真实模型）</option>
            </select>
            <input v-model="evalLabel" class="adm-input" style="width:160px" placeholder="本次标签" />
            <button class="adm-btn primary" :disabled="evalBusy" @click="runEval">
              {{ evalBusy ? '已启动' : '开始评测' }}</button>
          </div>
        </div>

        <div class="adm-card adm-pad" style="margin-bottom:14px" v-if="evalJob">
          <div class="adm-between">
            <b>任务 {{ evalJob.state }}</b>
            <span class="adm-tiny adm-muted">{{ evalJob.mode }} · {{ evalJob.label || '未命名' }}</span>
          </div>
          <div v-if="evalJob.result" class="adm-tiny adm-muted" style="margin-top:8px">
            用例 {{ evalJob.result.total }}，正确 {{ evalJob.result.correct }}，
            EA {{ pct(evalJob.result.exec_accuracy) }}，失败分类
            {{ Object.entries(evalJob.result.taxonomy || {}).map(([k, v]) => k + ':' + v).join('，') || '无' }}
          </div>
          <div v-if="evalJob.error" class="adm-alert rose" style="margin-top:8px"><b>失败</b><span>{{ evalJob.error }}</span></div>
        </div>

        <div class="adm-card" style="margin-bottom:14px">
          <div class="adm-pad adm-between">
            <div class="adm-h2" style="margin:0">历史评测</div>
            <span class="adm-tiny adm-muted">勾选两条做对比</span>
          </div>
          <div class="adm-table">
            <table>
              <thead><tr><th>对比</th><th>时间</th><th>标签</th><th>模式</th><th>用例</th><th>正确</th><th>EA</th><th>失败分类</th></tr></thead>
              <tbody>
                <tr v-for="r in evalRuns" :key="r.id">
                  <td><input type="checkbox" :value="r.id" v-model="evalCompare" /></td>
                  <td class="adm-tiny adm-muted">{{ r.ts }}</td>
                  <td>{{ r.label }}</td>
                  <td><span class="adm-badge" :class="r.mode === 'mock' ? 'sky' : 'amber'">{{ r.mode }}</span></td>
                  <td class="n">{{ r.total }}</td>
                  <td class="n">{{ r.correct }}</td>
                  <td class="n">{{ pct(r.exec_accuracy) }}</td>
                  <td class="adm-tiny adm-muted">
                    {{ Object.entries(r.taxonomy || {}).map(([k, v]) => k + ':' + v).join('，') || '—' }}
                  </td>
                </tr>
                <tr v-if="!evalRuns.length">
                  <td colspan="8">
                    <div class="adm-empty">
                      <div class="t">还没有评测记录</div>
                      <div class="s">选 mock 模式跑一次，零模型消耗</div>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="adm-card adm-pad" v-if="compareResult">
          <div class="adm-h2">A/B 对比</div>
          <dl class="adm-kv">
            <dt>基线</dt><dd>#{{ compareResult.a.id }} {{ compareResult.a.label }} · EA {{ pct(compareResult.a.exec_accuracy) }}</dd>
            <dt>对照</dt><dd>#{{ compareResult.b.id }} {{ compareResult.b.label }} · EA {{ pct(compareResult.b.exec_accuracy) }}</dd>
            <dt>差值</dt>
            <dd :style="{ color: compareResult.delta_accuracy >= 0 ? '#0f9d58' : '#dc2626' }">
              {{ (compareResult.delta_accuracy * 100).toFixed(1) }} 个百分点</dd>
          </dl>
          <div class="adm-tiny adm-muted" style="margin-top:8px">
            失败分类变化：{{ Object.entries(compareResult.failure_diff || {})
              .map(([k, v]) => k + ' ' + (v > 0 ? '+' : '') + v).join('，') || '无差异' }}
          </div>
        </div>
      </div>

      <!-- ================= 会话回放 ================= -->
      <div class="adm-screen" :class="{ on: tab === 'sessions' }">
        <div class="adm-page-head">
          <div>
            <h1>会话回放</h1>
            <p>全部 owner 的会话与回答；可下钻到 trace span，也可收录进知识库</p>
          </div>
          <div class="right">
            <span class="adm-badge teal">{{ sessions.length }} 个会话</span>
            <button class="adm-btn sm" @click="loadSessions">刷新</button>
          </div>
        </div>

        <div class="adm-grid adm-cols-split">
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
                <button class="adm-btn sm" style="margin-left:8px" v-if="h.trace_id"
                        @click="openTrace(h.trace_id)">查看 trace</button>
              </div>
              <div v-if="traceDetail && traceDetail.trace_id === h.trace_id" class="adm-card adm-pad" style="margin-top:8px">
                <div class="adm-h2">Trace {{ h.trace_id }}</div>
                <div class="adm-table">
                  <table>
                    <thead><tr><th>span</th><th>开始(ms)</th><th>耗时(ms)</th><th>状态</th></tr></thead>
                    <tbody>
                      <tr v-for="(sp, si) in traceDetail.spans || []" :key="si">
                        <td class="adm-mono">{{ sp.name }}<span v-if="sp.model" class="adm-muted"> · {{ sp.model }}</span></td>
                        <td class="n">{{ sp.start_ms }}</td>
                        <td class="n">{{ sp.duration_ms }}</td>
                        <td><span class="adm-badge" :class="sp.ok === false ? 'rose' : 'teal'">
                          {{ sp.ok === false ? 'fail' : (sp.ok === true ? 'ok' : '—') }}</span></td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ================= 运行配置 ================= -->
      <div class="adm-screen" :class="{ on: tab === 'config' }">
        <div class="adm-page-head">
          <div>
            <h1>运行配置</h1>
            <p>白名单化在线改 .env；写完即热生效，密钥类配置不可在线改</p>
          </div>
          <div class="right">
            <span class="adm-badge" :class="configDirty.length ? 'amber' : 'teal'">{{ configDirty.length }} 项待保存</span>
            <button class="adm-btn primary" :disabled="saving || !configDirty.length" @click="saveConfig">
              保存并生效</button>
          </div>
        </div>

        <div class="adm-card adm-pad" style="margin-bottom:14px" v-if="configResult">
          <div class="adm-alert" :class="configResult.effective ? 'teal' : 'amber'">
            <b>{{ configResult.effective ? '已生效' : '需重启' }}</b>
            <span>
              热生效 {{ (configResult.hot || []).length }} 项{{ (configResult.restart_required || []).length ? '，需重启：' + configResult.restart_required.join(', ') : '' }}
            </span>
          </div>
          <div class="adm-hint">改动已写入 {{ configResult.written?.length || 0 }} 行 .env，并记入审计。</div>
        </div>

        <div class="adm-grid adm-g2" style="align-items:start">
          <div class="adm-card adm-pad" v-for="g in configCatalog" :key="g.group">
            <div class="adm-h2">{{ g.group }}</div>
            <div v-for="it in g.items" :key="it.key" class="adm-field">
              <label>
                {{ it.label }}<span class="adm-mono adm-tiny adm-muted"> {{ it.key }}</span>
                <span v-if="it.restart" class="adm-badge amber" style="margin-left:6px">需重启</span>
              </label>
              <div class="adm-row" style="gap:8px">
                <label v-if="it.kind === 'bool'" class="adm-check">
                  <input type="checkbox" v-model="configDraft[it.key]" />
                </label>
                <select v-else-if="it.kind === 'enum'" class="adm-input" v-model="configDraft[it.key]">
                  <option v-for="o in it.options" :key="o" :value="o">{{ o }}</option>
                </select>
                <input v-else class="adm-input" :type="it.kind === 'int' || it.kind === 'float' ? 'number' : 'text'"
                       v-model="configDraft[it.key]" :placeholder="String(it.value)" />
              </div>
              <div class="adm-hint">{{ it.desc }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- ================= 提示词管理 ================= -->
      <div class="adm-screen" :class="{ on: tab === 'prompts' }">
        <div class="adm-page-head">
          <div>
            <h1>提示词管理</h1>
            <p>system_append 追加到系统提示词，insight 替换洞察提示词，guard 追加护栏规则</p>
          </div>
          <div class="right">
            <span class="adm-badge teal">{{ promptList?.length || 0 }} 个版本</span>
          </div>
        </div>

        <div class="adm-grid adm-g2" style="margin-bottom:14px;align-items:start">
          <div class="adm-card adm-pad">
            <div class="adm-h2">新建版本</div>
            <div class="adm-field">
              <label>类型</label>
              <select class="adm-input" v-model="promptForm.kind">
                <option value="system_append">system_append（追加到 system）</option>
                <option value="insight">insight（替换洞察提示词）</option>
                <option value="guard">guard（追加护栏规则）</option>
              </select>
            </div>
            <div class="adm-field">
              <label>名称</label>
              <input class="adm-input" v-model="promptForm.name" placeholder="口径优先版" />
            </div>
            <div class="adm-field">
              <label>内容</label>
              <textarea class="adm-area" rows="6" v-model="promptForm.body"
                        placeholder="【团队口径】统计有效成交时排除 cancelled / refunded 订单"></textarea>
            </div>
            <label class="adm-check adm-check-text adm-tiny adm-muted">
              <input type="checkbox" v-model="promptForm.activate" /> 保存后立即生效
            </label>
            <button class="adm-btn primary" :disabled="saving || promptForm.body.length < 5" @click="savePrompt">
              保存版本</button>
          </div>

          <div class="adm-card adm-pad">
            <div class="adm-h2">生效状态</div>
            <div v-for="k in promptKinds" :key="k" class="adm-row" style="padding:8px 0;border-bottom:1px solid #f1f5f9">
              <span class="grow adm-mono">{{ k }}</span>
              <span class="adm-badge" :class="activePrompt(k) ? 'teal' : 'amber'">
                {{ activePrompt(k) ? (activePrompt(k).name || activePrompt(k).id) : '使用默认' }}</span>
            </div>
            <div class="adm-hint" style="margin-top:10px">
              同类型互斥：激活一个版本会自动停用同类型其它版本；变更即时生效并留审计。
            </div>
          </div>
        </div>

        <div class="adm-card">
          <div class="adm-table">
            <table>
              <thead><tr><th>名称</th><th>类型</th><th>状态</th><th>创建时间</th><th>内容</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="p in promptList || []" :key="p.id">
                  <td>{{ p.name }}</td>
                  <td class="adm-mono">{{ p.kind }}</td>
                  <td><span class="adm-badge" :class="p.active ? 'teal' : ''">{{ p.active ? '生效中' : '未生效' }}</span></td>
                  <td class="adm-tiny adm-muted">{{ p.created }}</td>
                  <td class="adm-tiny adm-muted adm-truncate" style="max-width:260px">{{ p.body }}</td>
                  <td>
                    <button class="adm-btn sm" @click="activatePrompt(p)">激活</button>
                    <button class="adm-btn sm danger" style="margin-left:6px" @click="removePrompt(p)">删除</button>
                  </td>
                </tr>
                <tr v-if="!(promptList || []).length">
                  <td colspan="6">
                    <div class="adm-empty">
                      <div class="t">还没有提示词版本</div>
                      <div class="s">默认使用代码里的内置提示词</div>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- ================= 语义指标 ================= -->
      <div class="adm-screen" :class="{ on: tab === 'semantic' }">
        <div class="adm-page-head">
          <div>
            <h1>语义指标（MDL）</h1>
            <p>指标口径、标准 JOIN 与业务规则；改动写入 semantic/metrics.yaml，编译层随即可用</p>
          </div>
          <div class="right">
            <span class="adm-badge teal">{{ (semantic?.metrics || []).length }} 个指标</span>
            <button class="adm-btn primary" :disabled="saving" @click="saveSemantic">保存</button>
          </div>
        </div>

        <div class="adm-card adm-pad" style="margin-bottom:14px">
          <div class="adm-h2">编译结果预览</div>
          <input v-model="metricPreview" class="adm-input" placeholder="输入一个问题，预览会命中哪个指标"
                 @keyup.enter="previewMetric" />
          <div v-if="previewResult" class="adm-alert teal" style="margin-top:10px;flex-direction:column;gap:4px">
            <b>{{ previewResult.name }}（{{ previewResult.id }}）</b>
            <span class="adm-mono">{{ previewResult.expr }}</span>
            <span v-if="previewResult.valid_filter" class="adm-mono">过滤：{{ previewResult.valid_filter }}</span>
          </div>
          <div v-else-if="previewTried" class="adm-alert amber" style="margin-top:10px">
            <b>未命中</b><span>该问法没有匹配到受治理指标，模型会按自由口径生成</span>
          </div>
        </div>

        <div class="adm-card adm-pad" style="margin-bottom:14px">
          <div class="adm-h2">指标定义（JSON，可直接编辑）</div>
          <textarea class="adm-area" rows="16" v-model="semanticDraft"></textarea>
          <div class="adm-hint">保存前会校验结构：metrics 必须是带 id 的对象数组，joins 必须是对象数组。</div>
        </div>

        <div class="adm-card adm-pad">
          <div class="adm-h2">业务规则</div>
          <ul style="margin:0;padding-left:18px;font-size:12.5px;line-height:2;color:var(--muted)">
            <li v-for="(r, i) in semantic?.business_rules || []" :key="i">{{ r }}</li>
          </ul>
        </div>
      </div>

      <!-- ================= 知识库 ================= -->
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
              <textarea v-model="sqlForm.sql" class="adm-area" rows="4" placeholder="SELECT ... FROM orders"></textarea>
            </div>
            <div class="adm-field">
              <label>涉及表（逗号分隔）</label>
              <input v-model="sqlForm.tables" class="adm-input" placeholder="orders, order_items" />
            </div>
            <div class="adm-field">
              <label>备注</label>
              <input v-model="sqlForm.notes" class="adm-input" placeholder="为什么这样写（可选）" />
            </div>
            <button class="adm-btn primary" :disabled="saving || !sqlForm.question.trim() || !sqlForm.sql.trim()" @click="saveSql">
              保存为正式样例</button>
          </div>

          <div class="adm-card adm-pad">
            <div class="adm-h2">新增业务规则</div>
            <div class="adm-field">
              <label>规则标题</label>
              <input v-model="ruleForm.title" class="adm-input" placeholder="有效成交口径" />
            </div>
            <div class="adm-field">
              <label>规则内容</label>
              <textarea v-model="ruleForm.text" class="adm-area" rows="4"
                        placeholder="统计有效成交时排除 cancelled / refunded 订单"></textarea>
            </div>
            <button class="adm-btn primary" :disabled="saving || !ruleForm.text.trim()" @click="saveRule">
              保存规则</button>
            <div class="adm-hint" style="margin-top:8px">规则每轮注入 system prompt，优先级高于默认口径。</div>
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
                  <td class="sql adm-mono adm-truncate">{{ item.sql }}</td>
                  <td class="adm-mono">{{ (item.tables || []).join(', ') || '—' }}</td>
                  <td><span class="adm-pill">{{ item.source || 'admin' }}</span></td>
                  <td><button class="adm-btn sm" @click="removeSql(item)">删除</button></td>
                </tr>
                <tr v-if="!(knowledge?.sql || []).length">
                  <td colspan="5">
                    <div class="adm-empty">
                      <div class="t">还没有正式样例</div>
                      <div class="s">在「会话回放」或「未命中问题」里把一条验证过的回答收录进来</div>
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
            </div>
            <button class="adm-btn sm" @click="removeRule(item)">删除</button>
          </div>
          <div v-if="!(knowledge?.rules || []).length" class="adm-empty">
            <div class="t">还没有自定义规则</div>
            <div class="s">模型目前只用 semantic/metrics.yaml 里的默认口径</div>
          </div>
        </div>
      </div>

      <!-- ================= 只读策略 ================= -->
      <div class="adm-screen" :class="{ on: tab === 'policy' }">
        <div class="adm-page-head">
          <div>
            <h1>只读策略与合规</h1>
            <p>禁写词、敏感列脱敏、结果行数上限；写入 policy.yaml 并立即生效</p>
          </div>
          <div class="right">
            <button class="adm-btn primary" :disabled="saving" @click="savePolicy">保存策略</button>
          </div>
        </div>

        <div class="adm-grid adm-g2" style="align-items:start">
          <div class="adm-card adm-pad">
            <div class="adm-h2">禁写关键字</div>
            <div class="adm-hint" style="margin-bottom:8px">在原有黑名单之外追加；命中即拒绝执行该 SQL。</div>
            <input class="adm-input" v-model="policyDraft.forbidden" placeholder="vacuum, attach" />
            <div class="adm-h2" style="margin-top:16px">结果行数上限</div>
            <input class="adm-input adm-num" type="number" v-model.number="policyDraft.max_rows" />
          </div>
          <div class="adm-card adm-pad">
            <div class="adm-h2">敏感列（自动打码）</div>
            <div class="adm-hint" style="margin-bottom:8px">格式：表名:列名,列名；命中列名的结果会被替换为掩码。</div>
            <textarea class="adm-area" rows="6" v-model="policyDraft.denied"></textarea>
            <div class="adm-h2" style="margin-top:12px">掩码值</div>
            <input class="adm-input" v-model="policyDraft.mask_value" />
          </div>
        </div>
      </div>

      <!-- ================= 账号与权限 ================= -->
      <div class="adm-screen" :class="{ on: tab === 'accounts' }">
        <div class="adm-page-head">
          <div>
            <h1>账号与权限</h1>
            <p>账号写在 .env 的 AUTH_USERS；改动后已签发的旧 token 立即失效</p>
          </div>
          <div class="right">
            <button class="adm-btn primary" :disabled="saving" @click="saveAccounts">保存账号</button>
          </div>
        </div>

        <div class="adm-card" style="margin-bottom:14px">
          <div class="adm-table">
            <table>
              <thead><tr><th>用户名</th><th>角色</th><th>密码（留空表示不改）</th><th></th></tr></thead>
              <tbody>
                <tr v-for="(u, i) in accountRows" :key="i">
                  <td><input class="adm-input" v-model="u.username" /></td>
                  <td>
                    <select class="adm-input" v-model="u.role">
                      <option value="admin">admin</option>
                      <option value="user">user</option>
                    </select>
                  </td>
                  <td><input class="adm-input" type="password" v-model="u.password" placeholder="留空不改" /></td>
                  <td><button class="adm-btn sm danger" @click="accountRows.splice(i, 1)">删除</button></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="adm-pad"><button class="adm-btn sm" @click="accountRows.push({ username: '', role: 'user', password: '' })">+ 新增账号</button></div>
        </div>

        <div class="adm-grid adm-g2" style="align-items:start">
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
              <span>失败次数超过阈值即封禁，Basic 与 token 两个入口共用同一计数。</span>
            </div>
            <div class="adm-alert teal" style="flex-direction:column;gap:4px">
              <b>token 绑定账号表版本</b>
              <span>改密码、增删账号或轮换 SECRET_KEY 后，旧 token 立即失效。</span>
            </div>
            <div class="adm-alert amber" style="flex-direction:column;gap:4px">
              <b>密码写在 .env</b>
              <span>密码不能含逗号或冒号；.env 权限 600 且不进 Git。</span>
            </div>
          </div>
        </div>
      </div>

      <!-- ================= 配置审计 ================= -->
      <div class="adm-screen" :class="{ on: tab === 'audit' }">
        <div class="adm-page-head">
          <div>
            <h1>配置审计</h1>
            <p>所有管理端写操作：谁、何时、把什么改成了什么</p>
          </div>
          <div class="right">
            <span class="adm-badge teal">{{ audit?.count || 0 }} 条</span>
            <button class="adm-btn sm" @click="loadAudit">刷新</button>
          </div>
        </div>

        <div class="adm-card">
          <div class="adm-table">
            <table>
              <thead><tr><th>时间</th><th>操作者</th><th>动作</th><th>对象</th><th>变更</th><th>生效</th></tr></thead>
              <tbody>
                <tr v-for="a in audit?.items || []" :key="a.id">
                  <td class="adm-tiny adm-muted">{{ a.ts }}</td>
                  <td class="adm-mono">{{ a.actor }}</td>
                  <td><span class="adm-pill">{{ a.action }}</span></td>
                  <td class="adm-tiny adm-muted adm-truncate" style="max-width:180px">{{ a.target }}</td>
                  <td class="adm-tiny adm-mono adm-truncate" style="max-width:320px">
                    {{ diffText(a) }}
                  </td>
                  <td><span class="adm-badge" :class="a.effective ? 'teal' : 'amber'">{{ a.effective ? '已生效' : '需重启' }}</span></td>
                </tr>
                <tr v-if="!(audit?.items || []).length">
                  <td colspan="6">
                    <div class="adm-empty">
                      <div class="t">还没有审计记录</div>
                      <div class="s">改配置、加账号、写规则都会在这里留痕</div>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- ================= 索引与语料 ================= -->
      <div class="adm-screen" :class="{ on: tab === 'index' }">
        <div class="adm-page-head">
          <div>
            <h1>索引与语料</h1>
            <p>向量索引状态、重建记录与召回策略</p>
          </div>
          <div class="right">
            <button class="adm-btn primary" :disabled="rebuilding" @click="rebuild">
              {{ rebuilding ? '重建中…' : '重建向量索引' }}</button>
          </div>
        </div>

        <div class="adm-grid adm-g2" style="align-items:start">
          <div class="adm-card adm-pad">
            <div class="adm-h2">索引状态</div>
            <dl class="adm-kv">
              <dt>模式</dt><dd>{{ overview?.index?.mode || overview?.status?.index_mode }}</dd>
              <dt>向量表数</dt><dd>{{ overview?.status?.indexed_tables }} / {{ overview?.status?.table_count }}</dd>
              <dt>Embedding</dt><dd>{{ overview?.status?.emb_model }}</dd>
              <dt>维度</dt><dd>{{ overview?.index?.embedding_dim }}</dd>
              <dt>文件</dt><dd class="adm-mono adm-truncate">{{ overview?.index?.path }}</dd>
              <dt>大小</dt><dd>{{ overview?.index?.detail?.size_kb ?? 'n/a' }} KB</dd>
              <dt>重建时间</dt><dd>{{ overview?.index?.detail?.built_at || 'n/a' }}</dd>
              <dt>重建冷却</dt><dd>{{ overview?.index?.rebuild_cooldown ?? '-' }} 秒</dd>
              <dt>索引错误</dt><dd>{{ overview?.status?.index_error || '无' }}</dd>
            </dl>
          </div>
          <div class="adm-card adm-pad">
            <div class="adm-h2">召回策略</div>
            <dl class="adm-kv">
              <dt>few-shot 条数</dt><dd>{{ configValue('FEWSHOT_K') }}</dd>
              <dt>选表 Top-K</dt><dd>{{ configValue('TOP_K_TABLES') }}</dd>
              <dt>列级命中数</dt><dd>{{ configValue('COLUMN_LINK_TOPK') }}</dd>
              <dt>外键闭包</dt><dd>{{ configValue('FK_EXPAND_MAX') }} 张</dd>
              <dt>知识样例</dt><dd>{{ overview?.knowledge?.sql ?? 0 }} 个</dd>
              <dt>业务规则</dt><dd>{{ overview?.knowledge?.rules ?? 0 }} 条</dd>
            </dl>
            <div class="adm-hint" style="margin-top:10px">改这些参数到「运行配置」，保存后立即生效。</div>
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
import TrendChart from './TrendChart.vue'

const emit = defineEmits(['toast', 'open-chat', 'logout'])
const tab = ref('overview')

const overview = ref(null)
const alertsData = ref(null)
const alertRules = ref([])
const unmatched = ref(null)
const debugResult = ref(null)
const debugQuestion = ref('')
const debugging = ref(false)
const evalRuns = ref([])
const evalJob = ref(null)
const evalBusy = ref(false)
const evalMode = ref('mock')
const evalLabel = ref('')
const evalCompare = ref([])
const compareResult = ref(null)
const sessions = ref([])
const history = ref([])
const selectedSid = ref('')
const traceDetail = ref(null)
const configCatalog = ref([])
const configDraft = reactive({})
const configResult = ref(null)
const promptList = ref([])
const promptKinds = ['system_append', 'insight', 'guard']
const promptForm = reactive({ kind: 'system_append', name: '', body: '', activate: true })
const semantic = ref(null)
const semanticDraft = ref('')
const metricPreview = ref('')
const previewResult = ref(null)
const previewTried = ref(false)
const knowledge = ref(null)
const policyDraft = reactive({ forbidden: '', denied: '', max_rows: 500, mask_value: '***' })
const accountRows = ref([])
const audit = ref(null)
const saving = ref(false)
const rebuilding = ref(false)
const error = ref('')

const capability = [
  { name: '问答 / SSE 流式查询', user: true },
  { name: '查看自己的会话与结果', user: true },
  { name: '查看全部用户会话', user: false },
  { name: '写入知识库（样例 / 规则）', user: false },
  { name: '查看语义指标与 Trace', user: false },
  { name: '在线修改运行配置', user: false },
  { name: '重建向量索引', user: false },
]

const sqlForm = reactive({ question: '', sql: '', tables: '', notes: '' })
const ruleForm = reactive({ title: '', text: '' })

const navGroups = computed(() => [
  {
    title: '概览', items: [
      { key: 'overview', label: '运行总览' },
      { key: 'alerts', label: '告警与 SLO', count: (overview.value?.alerts || []).length || '' },
    ],
  },
  {
    title: '监控', mt: true, items: [
      { key: 'unmatched', label: '未命中问题', count: (unmatched.value?.items || []).length || '' },
      { key: 'debug', label: '检索调试' },
      { key: 'eval', label: '质量评测', count: evalRuns.value.length || '' },
      { key: 'sessions', label: '会话回放', count: sessions.value.length || '' },
    ],
  },
  {
    title: '配置', mt: true, items: [
      { key: 'config', label: '运行配置' },
      { key: 'prompts', label: '提示词管理', count: (promptList.value || []).length || '' },
      { key: 'semantic', label: '语义指标' },
      { key: 'knowledge', label: '知识库', count: overview.value?.knowledge?.sql || '' },
      { key: 'policy', label: '只读策略' },
      { key: 'accounts', label: '账号与权限' },
    ],
  },
  {
    title: '治理', mt: true, items: [
      { key: 'audit', label: '配置审计', count: overview.value?.audit_count || '' },
      { key: 'index', label: '索引与语料' },
    ],
  },
])

const trendPoints = computed(() => {
  const days = overview.value?.trends?.days || []
  return days.map(d => ({ label: d.date.slice(5), value: d.total, p50: d.p50, p95: d.p95 }))
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
const slo = computed(() => overview.value?.slo || null)

function sumOf(key) {
  return (overview.value?.trends?.days || []).reduce((a, d) => a + (d[key] || 0), 0)
}
function barWidth(v, total) {
  if (!total) return '4%'
  return `${Math.max(3, Math.min(100, (v / total) * 100))}%`
}
function pct(v) { return v == null ? 'n/a' : `${(Number(v) * 100).toFixed(1)}%` }
function ms(v) { return v == null ? 'n/a' : `${Math.round(Number(v))} ms` }
function csv(s) { return String(s || '').split(',').map(x => x.trim()).filter(Boolean) }
function notify(msg) { emit('toast', msg) }
function reasonText(r) {
  return { refused: '护栏拒答', zero_rows: '0 行', sql_error: 'SQL 报错', incomplete: '未完成' }[r] || r
}
function reasonBadge(r) {
  return { refused: 'violet', zero_rows: 'amber', sql_error: 'rose', incomplete: 'sky' }[r] || ''
}
function diffText(a) {
  const before = a.before && typeof a.before === 'object' ? JSON.stringify(a.before) : (a.before || '')
  const after = a.after && typeof a.after === 'object' ? JSON.stringify(a.after) : (a.after || '')
  if (!before && !after) return a.note || ''
  return `${before} → ${after}`
}
function configValue(key) {
  const v = configDraft[key]
  return v === undefined ? '—' : v
}
function activePrompt(kind) {
  return (promptList.value || []).find(p => p.kind === kind && p.active) || null
}

async function loadOverview() { overview.value = await api.adminOverview() }
async function loadAlerts() {
  alertsData.value = await api.adminAlerts()
  alertRules.value = JSON.parse(JSON.stringify(alertsData.value.rules || []))
}
async function loadUnmatched() { unmatched.value = await api.adminUnmatched() }
const configBaseline = ref({})
async function loadConfig() {
  const d = await api.adminConfig()
  configCatalog.value = d.catalog.groups || []
  Object.keys(configDraft).forEach(k => delete configDraft[k])
  Object.entries(d.current || {}).forEach(([k, v]) => { configDraft[k] = v })
  configBaseline.value = { ...d.current }
}
const configDirty = computed(() => Object.keys(configDraft).filter(
  k => String(configDraft[k]) !== String(configBaseline.value[k])))
async function loadPrompts() { promptList.value = (await api.adminPrompts()).prompts || [] }
async function loadSemanticAdmin() {
  semantic.value = await api.adminSemanticAdmin()
  semanticDraft.value = JSON.stringify({
    version: semantic.value.version,
    business_rules: semantic.value.business_rules,
    metrics: semantic.value.metrics,
    joins: semantic.value.joins,
    dialects: semantic.value.dialects,
  }, null, 2)
}
async function loadKnowledge() { knowledge.value = await api.adminKnowledge() }
async function loadPolicy() {
  const p = await api.adminPolicy()
  policyDraft.forbidden = (p.forbidden_keywords || []).join(', ')
  policyDraft.max_rows = p.max_rows
  policyDraft.mask_value = p.mask_value
  policyDraft.denied = Object.entries(p.denied_columns || {})
    .map(([k, v]) => `${k}:${(v || []).join(',')}`).join('\n')
}
async function loadAccounts() {
  const d = await api.adminAccounts()
  accountRows.value = (d.users || []).map(u => ({ username: u.username, role: u.role, password: '' }))
}
async function loadAudit() { audit.value = await api.adminAudit() }
async function loadSessions() { sessions.value = (await api.adminSessions()).sessions || [] }
async function loadEvalRuns() {
  const d = await api.adminEvalRuns()
  evalRuns.value = d.runs || []
}

function switchTab(key) {
  tab.value = key
  error.value = ''
  if (key === 'eval' && !evalRuns.value.length) loadEvalRuns().catch(() => {})
  if (key === 'sessions' && !sessions.value.length) loadSessions().catch(() => {})
  if (key === 'unmatched' && !unmatched.value) loadUnmatched().catch(() => {})
  if (key === 'prompts' && !promptList.value.length) loadPrompts().catch(() => {})
  if (key === 'knowledge' && !knowledge.value) loadKnowledge().catch(() => {})
  if (key === 'policy' && !policyDraft.forbidden) loadPolicy().catch(() => {})
  if (key === 'accounts' && !accountRows.value.length) loadAccounts().catch(() => {})
  if (key === 'audit' && !audit.value) loadAudit().catch(() => {})
  if (key === 'semantic' && !semantic.value) loadSemanticAdmin().catch(() => {})
}

async function refresh() {
  error.value = ''
  try {
    await loadOverview()
  } catch (e) { error.value = e.message }
}

async function saveAlerts() {
  saving.value = true
  try {
    alertsData.value = await api.adminSaveAlerts(alertRules.value)
    await loadOverview()
    notify('告警规则已保存')
  } catch (e) { error.value = e.message } finally { saving.value = false }
}

async function promote(it) {
  const sql = window.prompt('填写这条问题对应的只读 SQL（留空则跳过）', it.sql || 'SELECT ')
  if (!sql) return
  saving.value = true
  try {
    await api.adminPromoteUnmatched({ question: it.question, sql })
    await loadUnmatched(); await loadKnowledge(); await loadOverview()
    notify('已收录为正式样例')
  } catch (e) { error.value = e.message } finally { saving.value = false }
}

async function runDebug() {
  debugging.value = true
  error.value = ''
  try {
    debugResult.value = await api.adminDebugTables(debugQuestion.value)
  } catch (e) { error.value = e.message } finally { debugging.value = false }
}

async function runEval() {
  evalBusy.value = true
  try {
    const d = await api.adminEvalRun(evalLabel.value, evalMode.value)
    evalJob.value = d.job
    const jobId = d.job.job_id
    const timer = setInterval(async () => {
      try {
        const job = await api.adminEvalJob(jobId)
        evalJob.value = job
        if (job.state !== 'running') {
          clearInterval(timer)
          await loadEvalRuns()
          await loadOverview()
        }
      } catch (_) { clearInterval(timer) }
    }, 1500)
  } catch (e) { error.value = e.message } finally { evalBusy.value = false }
}

async function compareEval() {
  if (evalCompare.value.length !== 2) { notify('请勾选两条评测记录'); return }
  try {
    compareResult.value = await api.adminEvalCompare(evalCompare.value[0], evalCompare.value[1])
  } catch (e) { error.value = e.message }
}

async function openSession(sid) {
  selectedSid.value = sid
  traceDetail.value = null
  try {
    history.value = (await api.adminHistory(sid)).history || []
  } catch (e) { error.value = e.message }
}

async function openTrace(traceId) {
  try {
    const res = await fetch(`/api/traces/${traceId}`, { headers: { 'X-App-Token': localStorage.getItem('t2s_token') } })
    traceDetail.value = await res.json()
  } catch (e) { error.value = e.message }
}

async function saveFromMessage(h) {
  saving.value = true
  try {
    await api.adminFromMessage({ message_id: h.id })
    await loadKnowledge(); await loadOverview()
    notify('已从会话收录到知识库')
  } catch (e) { error.value = e.message } finally { saving.value = false }
}

async function saveConfig() {
  saving.value = true
  try {
    const changes = {}
    configDirty.value.forEach(k => { changes[k] = configDraft[k] })
    configResult.value = await api.adminApplyConfig(changes, '管理后台在线修改')
    configBaseline.value = { ...configResult.value.current }
    await loadOverview()
    notify(configResult.value.effective ? '配置已保存并生效' : '配置已保存，需重启服务生效')
  } catch (e) { error.value = e.message } finally { saving.value = false }
}

async function savePrompt() {
  saving.value = true
  try {
    await api.adminAddPrompt({ ...promptForm })
    promptForm.body = ''; promptForm.name = ''
    await loadPrompts(); await loadOverview()
    notify('提示词版本已保存')
  } catch (e) { error.value = e.message } finally { saving.value = false }
}

async function activatePrompt(p) {
  try {
    await api.adminActivatePrompt(p.id)
    await loadPrompts()
    notify('已切换生效版本')
  } catch (e) { error.value = e.message }
}

async function removePrompt(p) {
  if (!window.confirm(`删除提示词版本「${p.name}」？`)) return
  try {
    await api.adminDeletePrompt(p.id)
    await loadPrompts()
    notify('已删除')
  } catch (e) { error.value = e.message }
}

async function previewMetric() {
  previewTried.value = true
  try {
    const d = await api.adminDebugTables(metricPreview.value)
    previewResult.value = d.plan?.matched ? d.plan : null
  } catch (e) { error.value = e.message }
}

async function saveSemantic() {
  saving.value = true
  try {
    const data = JSON.parse(semanticDraft.value)
    const d = await api.adminSaveSemantic(data)
    semantic.value = d.catalog
    await loadOverview()
    notify('语义层已保存')
  } catch (e) { error.value = e.message } finally { saving.value = false }
}

async function saveSql() {
  saving.value = true
  try {
    await api.adminAddSql({
      question: sqlForm.question.trim(), sql: sqlForm.sql.trim(),
      tables: csv(sqlForm.tables), notes: sqlForm.notes.trim(),
    })
    sqlForm.question = ''; sqlForm.sql = ''; sqlForm.tables = ''; sqlForm.notes = ''
    await loadKnowledge(); await loadOverview()
    notify('已收录为正式样例')
  } catch (e) { error.value = e.message } finally { saving.value = false }
}

async function saveRule() {
  saving.value = true
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
  } catch (e) { error.value = e.message }
}

async function removeRule(item) {
  if (!window.confirm(`删除规则「${item.title}」？`)) return
  try {
    await api.adminDeleteRule(item.id)
    await loadKnowledge(); await loadOverview()
  } catch (e) { error.value = e.message }
}

async function savePolicy() {
  saving.value = true
  try {
    const denied = {}
    String(policyDraft.denied || '').split('\n').forEach(line => {
      const [t, cols] = line.split(':')
      if (t && t.trim()) denied[t.trim()] = csv(cols)
    })
    await api.adminSavePolicy({
      forbidden_keywords: csv(policyDraft.forbidden),
      denied_columns: denied,
      mask_value: policyDraft.mask_value,
      max_rows: Number(policyDraft.max_rows) || 500,
      audit_sql: true,
    })
    await loadPolicy(); await loadOverview()
    notify('只读策略已保存并生效')
  } catch (e) { error.value = e.message } finally { saving.value = false }
}

async function saveAccounts() {
  saving.value = true
  try {
    await api.adminSetAccounts(accountRows.value.filter(u => u.username.trim()))
    await loadAccounts(); await loadOverview()
    notify('账号已更新，旧 token 立即失效')
  } catch (e) { error.value = e.message } finally { saving.value = false }
}

async function rebuild() {
  rebuilding.value = true
  try {
    await api.rebuildIndex()
    await loadOverview()
    notify('向量索引已重建')
  } catch (e) { error.value = e.message } finally { rebuilding.value = false }
}

watch(evalCompare, () => { if (evalCompare.value.length === 2) compareEval() })

onMounted(async () => {
  await refresh()
  await loadConfig()
  await loadAlerts()
})
</script>
