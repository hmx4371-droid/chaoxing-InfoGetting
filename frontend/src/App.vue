<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from './api'

const overview = ref(null)
const health = ref(null)
const account = ref(null)
const syncing = ref(false)
const refreshing = ref(false)
const now = ref(Date.now())

// 登录弹窗
const loginVisible = ref(false)
const loggingIn = ref(false)
const loginForm = ref({ phone: '', password: '', remember: true })

let tickTimer = null
let pollTimer = null
let autoTimer = null

// 页面自己会定时拉数据：否则挂着不动看到的永远是打开那一刻的旧快照
const AUTO_REFRESH_MS = 20000

const homework = computed(() => overview.value?.homework ?? [])
const schedule = computed(() => overview.value?.schedule ?? [])
const exams = computed(() => overview.value?.exams ?? [])
const notices = computed(() => overview.value?.notices ?? [])
const lastSync = computed(() => overview.value?.lastSync ?? null)
const collectorOnline = computed(() => health.value?.collectorOnline === true)

// ---------------------------------------------------------------- 数据加载

async function refresh() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    const [ov, hl, ac] = await Promise.all([api.overview(), api.health(), api.account()])
    overview.value = ov
    health.value = hl
    account.value = ac
  } catch (e) {
    ElMessage.error('读取数据失败：' + e.message + '（后端 8080 起来了吗？）')
  } finally {
    refreshing.value = false
  }
}

// ---------------------------------------------------------------- 登录 / 账号

function openLogin() {
  loginForm.value = {
    phone: '',
    // 只回填"记住"标记，手机号/密码一律不回填也不回显
    password: '',
    remember: account.value?.remember ?? true,
  }
  loginVisible.value = true
}

async function doLogin() {
  const { phone, password, remember } = loginForm.value
  if (!phone.trim() || !password) {
    ElMessage.warning('手机号和密码都要填')
    return
  }
  loggingIn.value = true
  try {
    const res = await api.login({ phone: phone.trim(), password, remember })
    if (!res.ok) {
      ElMessage.error('登录失败：' + (res.msg || '账号或密码不正确'))
      return
    }
    loginForm.value.password = '' // 用完立刻清掉，不留内存
    loginVisible.value = false
    ElMessage.success('登录成功：' + ((res.account?.name || '') + ' ' + (res.account?.phoneMasked || '')).trim())
    await refresh()
    doSync() // 登录完自动同步一次
  } catch (e) {
    ElMessage.error('登录请求失败：' + e.message)
  } finally {
    loggingIn.value = false
  }
}

async function doLogout() {
  try {
    await api.logout()
    ElMessage.success('已退出登录，cookie 与保存的密码都清掉了')
  } catch (e) {
    ElMessage.error('退出失败：' + e.message)
  }
  await refresh()
}

/** 页面上显示的账号和库里数据的账号不一致时提示（换号后还没同步）。 */
const accountMismatch = computed(() => {
  const last = overview.value?.lastSync
  const acc = account.value
  if (!last?.accountName || !acc?.name) return false
  return last.accountName !== acc.name
})

async function doSync() {
  if (syncing.value) return
  syncing.value = true
  try {
    await api.sync()
  } catch (e) {
    if (e.status !== 409) {
      syncing.value = false
      ElMessage.error('触发同步失败：' + e.message)
      return
    }
    ElMessage.warning('已经有一轮同步在进行中')
  }
  startPolling()
}

function startPolling() {
  syncing.value = true
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(checkStatus, 2000)
  checkStatus()
}

async function checkStatus() {
  try {
    const st = await api.syncStatus()
    if (st.running) return
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    syncing.value = false
    await refresh()
    const last = st.last
    if (last?.status === 'SUCCESS') {
      const n = last.homeworkCount + last.scheduleCount + last.examCount + last.noticeCount
      ElMessage.success(`同步完成：作业 ${last.homeworkCount} · 课表 ${last.scheduleCount} · 考试 ${last.examCount} · 通知 ${last.noticeCount}（共 ${n} 条）`)
    } else if (last?.status === 'FAILED') {
      ElMessage.error('同步失败：' + (last.message || '未知错误'))
    }
  } catch {
    // 后端可能正在重启，下一轮再试
  }
}

function handleVisibility() {
  if (!document.hidden && !syncing.value) refresh()
}

onMounted(async () => {
  await refresh()
  if (overview.value?.syncing) startPolling()
  tickTimer = setInterval(() => (now.value = Date.now()), 30000)
  autoTimer = setInterval(() => {
    if (!syncing.value && !document.hidden) refresh()
  }, AUTO_REFRESH_MS)
  document.addEventListener('visibilitychange', handleVisibility)
  // 支持 ?login=1 直接打开登录框（也方便截图/排查）
  if (new URLSearchParams(location.search).get('login') === '1') openLogin()
})

onUnmounted(() => {
  if (tickTimer) clearInterval(tickTimer)
  if (pollTimer) clearInterval(pollTimer)
  if (autoTimer) clearInterval(autoTimer)
  document.removeEventListener('visibilitychange', handleVisibility)
})

// ---------------------------------------------------------------- 时间工具

function toDate(s) {
  if (!s) return null
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? null : d
}

function pad(n) {
  return String(n).padStart(2, '0')
}

function fmtDateTime(s) {
  const d = toDate(s)
  return d ? `${d.getMonth() + 1}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}` : '—'
}

function fmtClock(s) {
  const d = toDate(s)
  return d ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : '—'
}

function fmtDay(s) {
  const d = toDate(s)
  if (!d) return '时间待定'
  const week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()]
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日 ${week}`
}

function isToday(s) {
  const d = toDate(s)
  if (!d) return false
  const t = new Date()
  return d.getFullYear() === t.getFullYear() && d.getMonth() === t.getMonth() && d.getDate() === t.getDate()
}

/** 作业倒计时：过期 / 1 天内 / 更远 三档，颜色由前端决定。 */
function countdown(item) {
  if (!item.pending) return { text: '已完成', cls: 'gray' }
  const d = toDate(item.deadline)
  if (!d) return { text: '无截止时间', cls: 'gray' }
  const ms = d.getTime() - now.value
  const day = 86400000
  if (ms < 0) {
    const days = Math.floor(-ms / day)
    return days >= 1
      ? { text: `已过期 ${days} 天`, cls: 'red' }
      : { text: `已过期 ${Math.max(1, Math.floor(-ms / 3600000))} 小时`, cls: 'red' }
  }
  const days = Math.floor(ms / day)
  const hours = Math.floor((ms % day) / 3600000)
  const mins = Math.floor((ms % 3600000) / 60000)
  let text
  if (days >= 1) text = `剩 ${days} 天 ${hours} 小时`
  else if (hours >= 1) text = `剩 ${hours} 小时 ${mins} 分`
  else text = `剩 ${mins} 分钟`
  return { text, cls: ms < day ? 'orange' : '' }
}

function examHint(item) {
  const d = toDate(item.startTime)
  if (!d) return ''
  const ms = d.getTime() - now.value
  if (ms < 0) return '已结束'
  const days = Math.floor(ms / 86400000)
  return days >= 1 ? `${days} 天后` : '今天'
}

// ---------------------------------------------------------------- 统计 / 分组

const stats = computed(() => {
  const todayLessons = schedule.value.filter((l) => isToday(l.startTime)).length
  const upcomingExams = exams.value.filter((e) => {
    const d = toDate(e.endTime) || toDate(e.startTime)
    return d && d.getTime() >= now.value
  }).length
  return {
    pendingHomework: overview.value?.pendingHomework ?? 0,
    todayLessons,
    upcomingExams,
    unreadNotices: overview.value?.unreadNotices ?? 0,
  }
})

/** 课表按天分组（后端已按开始时间升序）。 */
const dayGroups = computed(() => {
  const groups = []
  let current = null
  for (const lesson of schedule.value) {
    const key = lesson.startTime ? lesson.startTime.slice(0, 10) : 'unknown'
    if (!current || current.key !== key) {
      current = { key, date: lesson.startTime, lessons: [] }
      groups.push(current)
    }
    current.lessons.push(lesson)
  }
  return groups
})

function lessonClass(lesson) {
  const d = toDate(lesson.endTime)
  if (d && d.getTime() < now.value) return 'done'
  if (lesson.status === '上课中') return 'now'
  return ''
}

const hasAnyData = computed(() => {
  const v = overview.value
  return !!v && (v.homework.length + v.schedule.length + v.exams.length + v.notices.length > 0)
})

/** 同步确实成功了，但学习通里这三类就是空的 —— 要在页面上说清楚，别让人以为是没同步。 */
const emptyBySource = computed(() => {
  const v = overview.value
  if (!v || !v.lastSync || v.lastSync.status !== 'SUCCESS' || v.lastSync.mock) return false
  return v.homework.length === 0 && v.schedule.length === 0 && v.exams.length === 0
})
</script>

<template>
  <div class="page">
    <!-- 顶栏 -->
    <header class="topbar">
      <div class="brand">
        <div class="logo">学</div>
        <div>
          <h1>通知整合系统</h1>
          <p class="sub">学习通 · 作业 DDL / 课表 / 考试 / 通知</p>
        </div>
      </div>
      <div class="actions">
        <span class="dot" :class="collectorOnline ? 'ok' : 'bad'" />
        <span class="muted">{{ collectorOnline ? '采集服务在线' : '采集服务未启动' }}</span>
        <el-button v-if="!syncing" size="default" @click="openLogin">
          {{ account?.loggedIn ? '切换账号' : '登录学习通' }}
        </el-button>
        <el-button type="primary" :loading="syncing" @click="doSync">
          {{ syncing ? '同步中…' : '立即同步' }}
        </el-button>
      </div>
    </header>

    <!-- 同步信息 -->
    <div class="meta">
      <span v-if="account" class="account">
        <template v-if="account.loggedIn">
          账号：{{ account.name || '已登录' }}<template v-if="account.school">@{{ account.school }}</template>
          <template v-if="account.phoneMasked"> · {{ account.phoneMasked }}</template>
        </template>
        <template v-else>未登录学习通</template>
      </span>
      <span v-if="account?.remember" class="badge mock">已记住密码</span>
      <span v-if="accountMismatch" class="badge err">
        下图数据属于 {{ overview.lastSync.accountName }}，点「立即同步」按当前账号重拉
      </span>
      <template v-if="lastSync">
        <span>上次同步：{{ fmtDateTime(lastSync.finishedAt || lastSync.startedAt) }}</span>
        <span class="badge">{{ lastSync.status === 'SUCCESS' ? '成功' : lastSync.status === 'RUNNING' ? '进行中' : '失败' }}</span>
        <span v-if="lastSync.mock" class="badge mock">假数据</span>
        <span v-if="lastSync.status === 'FAILED' && lastSync.message" class="badge err">{{ lastSync.message }}</span>
      </template>
      <span v-else>还没有同步过，点右上角「立即同步」拉一次学习通数据</span>
      <span class="auto-tip">自动刷新 20s · 只有「立即同步」才会去学习通拉新数据</span>
      <el-button size="small" text :loading="refreshing" @click="refresh">重新读取</el-button>
    </div>

    <!-- 没登录就先登录 -->
    <div v-if="account && account.loggedIn === false && !account.mock" class="banner warn">
      还没登录学习通，采集不了数据。
      <el-button link type="primary" @click="openLogin">点这里登录</el-button>
      （密码只发给本机采集服务，不会存明文）
    </div>

    <!-- 同步成功但学习通里没内容时，把原因直接写在页面上 -->
    <div v-if="emptyBySource" class="banner">
      <strong>这次同步是成功的</strong>，登录、课程、通知都拿到了，但学习通里
      <b>作业、课表、考试都是空的</b>（通知 {{ notices.length }} 条）。
      这不是没同步 —— 是该账号在这几个模块里确实没有数据：课表可能在学校教务系统、
      作业可能走别的平台。想知道原始响应长什么样，在 <code>demo\collector</code> 下跑
      <code>python probe.py</code>。
    </div>

    <!-- 统计 -->
    <section class="stats">
      <div class="stat" :class="{ warn: stats.pendingHomework > 0 }">
        <div class="label">待办作业</div>
        <div class="value">{{ stats.pendingHomework }}<span class="unit">份</span></div>
      </div>
      <div class="stat">
        <div class="label">今天课程</div>
        <div class="value">{{ stats.todayLessons }}<span class="unit">节</span></div>
      </div>
      <div class="stat">
        <div class="label">待考考试</div>
        <div class="value">{{ stats.upcomingExams }}<span class="unit">场</span></div>
      </div>
      <div class="stat" :class="{ warn: stats.unreadNotices > 0 }">
        <div class="label">未读通知</div>
        <div class="value">{{ stats.unreadNotices }}<span class="unit">条</span></div>
      </div>
    </section>

    <!-- 主区域 -->
    <section class="grid">
      <!-- 作业 DDL -->
      <el-card shadow="never" class="panel">
        <div class="card-head">
          <h2>作业 DDL</h2>
          <span class="hint">临期在前，已完成沉底</span>
        </div>
        <div v-if="homework.length === 0" class="empty">学习通里暂无作业</div>
        <div v-for="h in homework" :key="h.id" class="row">
          <div class="row-main">
            <div class="row-title" :class="{ dim: !h.pending }">{{ h.title }}</div>
            <div class="row-sub">
              <span v-if="h.course">{{ h.course }}</span>
              <span>{{ h.status }}</span>
              <span v-if="h.deadline">{{ fmtDateTime(h.deadline) }} 截止</span>
            </div>
          </div>
          <div class="row-right">
            <div class="countdown" :class="countdown(h).cls">{{ countdown(h).text }}</div>
            <a v-if="h.url" class="link" :href="h.url" target="_blank" rel="noreferrer">打开作业</a>
          </div>
        </div>
      </el-card>

      <div class="col">
        <!-- 考试 -->
        <el-card shadow="never" class="panel">
          <div class="card-head">
            <h2>考试</h2>
            <span class="hint">待考在前</span>
          </div>
          <div v-if="exams.length === 0" class="empty">学习通里暂无考试安排</div>
          <div v-for="e in exams" :key="e.id" class="row">
            <div class="row-main">
              <div class="row-title">{{ e.title }}</div>
              <div class="row-sub">
                <span>{{ fmtDateTime(e.startTime) }}</span>
                <span>{{ e.status }}</span>
              </div>
            </div>
            <div class="row-right">
              <div class="countdown" :class="examHint(e) === '已结束' ? 'gray' : 'orange'">{{ examHint(e) }}</div>
            </div>
          </div>
        </el-card>

        <!-- 通知 -->
        <el-card shadow="never" class="panel">
          <div class="card-head">
            <h2>通知</h2>
            <span class="hint">最新在前</span>
          </div>
          <div v-if="notices.length === 0" class="empty">学习通里暂无通知</div>
          <div v-for="n in notices" :key="n.id" class="notice" :class="{ unread: n.pending }">
            <span class="flag" />
            <div>
              <div class="title">{{ n.title }}</div>
              <div class="meta2">
                <span v-if="n.teacher">{{ n.teacher }} · </span>{{ fmtDateTime(n.startTime) }}
              </div>
            </div>
          </div>
        </el-card>
      </div>
    </section>

    <!-- 本周课表 -->
    <el-card shadow="never" class="panel schedule-panel">
      <div class="card-head">
        <h2>本周课表</h2>
        <span class="hint">当前周，数据来自学习通课表接口</span>
      </div>
      <div v-if="schedule.length === 0" class="empty">学习通里没有本周课表数据</div>
      <div v-for="g in dayGroups" :key="g.key" class="day-block">
        <div class="day-title">
          {{ fmtDay(g.date) }}
          <span v-if="isToday(g.date)" class="today">今天</span>
        </div>
        <div v-for="l in g.lessons" :key="l.id" class="lesson" :class="lessonClass(l)">
          <div class="time">{{ fmtClock(l.startTime) }}–{{ fmtClock(l.endTime) }}</div>
          <div>
            <div class="name">{{ l.title }}</div>
            <div class="where">
              <span v-if="l.location">{{ l.location }}</span>
              <span v-if="l.teacher"> · {{ l.teacher }}</span>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 登录弹窗 -->
    <el-dialog v-model="loginVisible" title="登录学习通" width="420px" :close-on-click-modal="!loggingIn">
      <el-form label-position="top" @submit.prevent="doLogin">
        <el-form-item label="手机号">
          <el-input
            v-model="loginForm.phone"
            placeholder="学习通手机号"
            autocomplete="username"
            clearable
            @keyup.enter="doLogin"
          />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="loginForm.password"
            type="password"
            show-password
            placeholder="学习通密码"
            autocomplete="current-password"
            @keyup.enter="doLogin"
          />
        </el-form-item>
        <el-checkbox v-model="loginForm.remember">记住密码</el-checkbox>
        <p class="dialog-tip">
          密码只发给本机采集服务（127.0.0.1:8801），不经过浏览器之外的地方；
          勾选「记住密码」才会用本机密钥 <code>secret.key</code> 做 AES-256-GCM 加密后存盘，
          否则只留在内存里，重启就没了。
        </p>
      </el-form>
      <template #footer>
        <el-button v-if="account?.loggedIn" @click="doLogout">退出登录</el-button>
        <el-button @click="loginVisible = false">取消</el-button>
        <el-button type="primary" :loading="loggingIn" @click="doLogin">登录并同步</el-button>
      </template>
    </el-dialog>

    <p v-if="!hasAnyData && lastSync" class="footer-tip">
      这次同步没拿到任何数据。可能是学习通里确实没有（在 demo\collector 目录跑
      <code>python probe.py</code> 可以看原始响应确认），也可能是登录态失效或页面结构变了。
    </p>
    <p class="footer-tip">
      demo 只做「学习通 → 数据库 → 页面」这一条链路；知到 / QQ / 微信 / 雨课堂 与 agent 在后续阶段接入。
    </p>
  </div>
</template>

<style scoped>
.panel {
  border-radius: 12px;
  border: 1px solid #e8eaed;
}

.panel :deep(.el-card__body) {
  padding: 14px 16px 16px;
}

.schedule-panel {
  margin-top: 16px;
}

.footer-tip {
  margin: 18px 0 0;
  font-size: 12px;
  color: #9aa0a6;
  text-align: center;
}

.footer-tip code {
  background: #eef1f5;
  border-radius: 4px;
  padding: 1px 5px;
  color: #4b5563;
}
</style>
