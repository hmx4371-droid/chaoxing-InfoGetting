# 通知整合系统 · 学习通采集 demo（使用教程）

把学习通里的**作业 DDL / 课表 / 考试 / 通知**抓下来，存进数据库，用一个网页看。
这不是完整产品，只是整条链路的**最小可运行切片**：采集 → 统一 JSON → 入库 → 展示。

```
┌──────────────────┐   只读 HTTP   ┌────────────────────────┐
│ 浏览器 :5273      │  GET /api/*  │ Java 后端 :8080         │
│ (Vue3 + Element) │ ───────────▶ │ Spring Boot 4.1.2       │
└──────────────────┘              │ MyBatis-Plus → MySQL    │
                                  └───┬────────────────────┘
                        POST /api/sync │ 轮询状态 / GET /api/data
                                       ▼
                          ┌──────────────────────────┐
                          │ Python 采集服务 :8801      │
                          │ FastAPI + requests       │
                          └───┬──────────────────────┘
                              │ 登录 + 只读抓取
                              ▼
                          学习通（passport2 / kb / mooc1 / notice）
```

一句话记住分工：**采集层只管"抓成 JSON"，后端只管"存 + 查"，前端只管"看"。**
Java 侧不解析学习通 HTML，Python 侧不碰数据库——这样任何一边改坏了都不会牵连另一边。

---

## 目录结构

```
demo/
├─ collector/                  Python 采集服务（:8801）
│  ├─ main.py                  FastAPI 入口：健康检查 / 登录 / 触发同步 / 取数据
│  ├─ security.py              凭据保护：本机密钥 + AES-256-GCM 加密、脱敏、文件权限
│  ├─ probe.py                 诊断脚本：dump 学习通原始响应，判断"真没数据"还是"解析失败"
│  ├─ chaoxing/
│  │  ├─ client.py             协议层：AES 登录、cookie 持久化、四类接口（只读）
│  │  ├─ collect.py            把四类数据组装成统一 JSON（唯一"翻译层"）
│  │  └─ mock.py               假数据：没账号也能跑通全链路
│  ├─ config.example.json      配置模板（复制成 config.json 后填）
│  ├─ config.json              ← 你自己填，已在 .gitignore 里，不会进 git
│  ├─ secret.key               ← 本机加密密钥，首次记住密码时自动生成，不进 git
│  └─ session_cookies.json     ← 登录后自动生成，同样不进 git
├─ backend/                    Java 后端（:8080）
│  ├─ pom.xml                  Spring Boot 4.1.2 / Java 21 / MyBatis-Plus 3.5.18
│  └─ src/main/
│     ├─ java/com/example/notify/
│     │  ├─ collector/         调采集服务的 HTTP 客户端 + 报文 DTO
│     │  ├─ item/              统一事件表实体、Mapper、查询与幂等 upsert
│     │  ├─ sync/              同步编排、互斥锁、执行日志
│     │  ├─ web/               REST 接口
│     │  └─ agent/             预留包（下一阶段接 Spring AI，本次空实现）
│     └─ resources/
│        ├─ application.yml    默认连 MySQL
│        ├─ application-h2.yml 零配置试跑档（嵌入式库）
│        └─ db/schema.sql      建表语句（MySQL / H2 通用，可重复执行）
└─ frontend/                   Vue3 页面（:5273）
   ├─ vite.config.js           /api 反向代理到 8080，前端不用管 CORS
   └─ src/App.vue              单页：统计卡 + 作业 DDL + 考试 + 通知 + 本周课表
```

---

## 0. 环境要求

| 组件 | 要求 | 说明 |
|---|---|---|
| JDK | **21** | Spring Boot 4 最低要求 21，JDK 17 不行 |
| Maven | 3.9+ | 用于构建后端 |
| Node | 18+ | 建议 20 / 22 / 24 |
| Python | 3.10+ | 采集服务 |
| MySQL | 8.x（可选） | 不装也能先用 H2 试跑 |
| Redis | 可选 | 只用于同步锁，不装自动降级 |

> ⚠️ **本机默认 `JAVA_HOME` 指向 JDK 1.8**，每开一个新终端、跑后端之前都要先切：
>
> ```powershell
> $env:JAVA_HOME='C:\Program Files\Microsoft\jdk-21.0.7.6-hotspot'
> java -version   # 应该显示 21.x
> ```
>
> 忘了切会报 `invalid target release: 21` 或 `UnsupportedClassVersionError`。

---

## 1. 最快跑通（假数据 + 免装数据库）

准备三个终端窗口，全部在 `demo\` 所在的项目根目录下操作。

### 终端 1：启动采集服务

```powershell
cd demo\collector
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8801
```

看到 `Uvicorn running on http://127.0.0.1:8801` 即成功。

- 首次启动会自动生成 `config.json`，默认 `"mock": true`（假数据模式，不需要学习通账号）。
- 自检：浏览器打开 <http://127.0.0.1:8801/docs>（FastAPI 自带文档页），
  或访问 `http://127.0.0.1:8801/api/health` 应返回 `{"ok":true,...}`。

### 终端 2：启动 Java 后端

```powershell
cd demo\backend
$env:JAVA_HOME='C:\Program Files\Microsoft\jdk-21.0.7.6-hotspot'
mvn spring-boot:run "-Dspring-boot.run.profiles=h2"
```

- 首次会下载 Maven 依赖（几分钟，之后有缓存就很快）。
- **`h2` 档**表示用嵌入式 H2 文件库，不连 MySQL；数据落在 `demo\backend\data\notifydb.mv.db`。
- 看到 `Tomcat started on port 8080` 和 `Started NotifyDemoApplication` 即成功。
- 自检：<http://127.0.0.1:8080/api/health> 应返回 `{"ok":true,"collector_online":true,...}`。
- ⚠️ PowerShell 里 `-Dspring-boot.run.profiles=h2` **必须整体加引号**，否则会被拆成两个参数。

### 终端 3：启动前端

```powershell
cd demo\frontend
npm install
npm run dev
```

### 打开页面并同步

浏览器访问 <http://127.0.0.1:5273> → 点右上角 **「立即同步」**。

几秒后（假数据模式约 1 秒）页面会出现：待办作业 4 份（含 1 份已过期、1 份明天到期）、
本周 8 节课、2 场考试、5 条通知，右上角同时显示「采集服务在线」。

- 页面上「假数据」标记表示当前走的是 `mock.py`，不是真实学习通。
- 想验证接口：<http://127.0.0.1:8080/api/overview> 会返回完整 JSON。

正常应该长这样（假数据截图）：

![页面截图](docs/screenshot.png)

对照验收：

| 位置 | 应该看到 |
|---|---|
| 右上角 | 绿点 +「采集服务在线」 |
| 同步信息行 | 「上次同步：…」+ 成功 + 假数据 两个小标签 |
| 待办作业 | 3 份；作业卡里有一条红色「已过期 X 小时」、一条「剩 1 天…」 |
| 今天课程 | 1 节（假数据里今天是周三） |
| 待考考试 | 1 场（另一场显示「已结束」） |
| 未读通知 | 2 条（前面有红点） |
| 本周课表 | 按天分组，今天那组有「今天」蓝标 |

> ⚠️ 页面上有两个容易搞混的动作：
> **「重新读取」/ 每 45 秒自动刷新 = 只重读数据库**；
> **「立即同步」才会去学习通拉新数据**。同步信息行会显示当前采集的学习通账号，
> 换号后先点同步，账号变了才说明真换过来了。

> 假数据是**按当天日期动态生成的**，所以数字（剩几天、过期几小时）会随你打开的时间变，
> 但结构应该和上图一致。
>
> ⚠️ **假数据与真实数据是互斥的**：`config.json` 里 `mock` 一改，下一轮同步会先把另一种模式的
> 历史行删掉再写入。所以从假数据切到真实账号后，看到的是"真实账号里有多少"，不会残留假作业。

后端也可以用打好的 jar 跑（等价，启动更快）：

```powershell
cd demo\backend
$env:JAVA_HOME='C:\Program Files\Microsoft\jdk-21.0.7.6-hotspot'
mvn -DskipTests package
java -jar target\notify-demo-0.1.0.jar --spring.profiles.active=h2
```

---

## 2. 接自己真实的学习通账号

> ℹ️ **验证范围**：假数据链路逐条验证过；真实账号用测试号跑通了
> **作业 6 份 + 通知 7 条**（作业 DDL 那一栏能出数据）。不过测试号是
> "超星网络空间"个人空间，**课程列表接口返回 0 门课**，所以作业是通过下面说的
> "从作业通知反查课程"捞到的；`考试 / 课表` 在该号里没有数据。
>
> 真实账号页面截图已删除（会暴露账号昵称与姓名），界面结构与上面的假数据截图一致。

### 2.1 填凭据

**推荐：在页面上登录。** 打开 <http://127.0.0.1:5273>，点右上角「登录学习通」，
填手机号 + 密码，可选「记住密码」，点「登录并同步」。好处是密码只发给本机采集服务，
不用手改文件，也不会以明文落盘（详见第 4 节）。

也可以直接编辑 `demo\collector\config.json`（老办法，会保留明文，不推荐）：

```json
{
  "phone": "你的手机号",
  "password": "你的密码",
  "mock": false,
  "throttle": 0.5,
  "notice_limit": 40,
  "with_details": true
}
```

启动时会把明文 `password` 自动迁移成加密的 `password_enc` 并清空明文。

| 字段 | 作用 |
|---|---|
| `phone` | 学习通手机号（cookie 归属也按它识别，所以这里存明文） |
| `password_enc` | **加密后的密码**（AES-256-GCM，密钥是 `secret.key`）；勾"记住密码"才有值 |
| `remember` | 是否记住密码。`false` 时密码只在进程内存里，重启就要重新登录 |
| `mock` | `true` 用假数据，`false` 走真实抓取 |
| `throttle` | 请求最小间隔（秒），"温和人类"节流，建议 0.5~0.8 |
| `notice_limit` | 最多取多少条通知（默认 40） |
| `with_details` | 是否逐份拉作业详情拿截止时间（关掉会快很多，但作业没有 DDL） |

也可以不手动改文件，用接口登录（会自动写回 `config.json`，密码只存密文）：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8801/api/login `
  -ContentType 'application/json' `
  -Body '{"phone":"你的手机号","password":"你的密码","remember":true}'
```

### 2.2 确认登录状态

```powershell
Invoke-RestMethod http://127.0.0.1:8801/api/login/status
```

返回 `{"logged_in":true,"account":{"name":"你的名字","school":"你的学校",...}}` 就对了。

- 登录成功后 cookie 会存进 `session_cookies.json`，下次启动不用重复登录。
- 登录态失效时采集层会**自动用 config.json 里的凭据重登一次**。
- **换账号**：直接改 config.json 里的 `phone` 即可，下一轮同步会自动发现
  "cookie 不属于这个手机号"并强制重登（cookie 归属记在 `session_owner.json`）。
  这一点踩过坑：只改配置不清 cookie 的话，旧 cookie 还有效，会一直用着上一个账号。

### 2.3 同步

页面上点「立即同步」，或：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/api/sync
Invoke-RestMethod http://127.0.0.1:8080/api/sync/status
```

**真实数据一轮大约 60~120 秒**：要逐门课拉作业列表、再逐份未交作业拉详情页才能拿到截止时间。
同步是异步的，`POST /api/sync` 立刻返回，页面每 2 秒自动轮询进度。

### 2.4 首次登录的坑
学习通对异地/新设备登录会要验证码或二次验证，这时 `login` 会返回
`登录失败（账号密码错误或需要验证码）`。处理办法：

1. 用浏览器正常登录 <https://i.chaoxing.com>（把验证码那步过掉）；
2. 打开开发者工具 → Application → Cookies，把 `passport2.chaoxing.com` 域下的
   cookie 复制成 JSON，覆盖写入 `demo\collector\session_cookies.json`，形如
   `{"_uid":"123456","_d":"...","UID":"..."}`；
3. 重启采集服务，`/api/login/status` 应显示已登录。

> 建议在**自己电脑自己的网络**上跑，机房/云服务器 IP 容易被学习通风控挡掉。

### 2.5 抓不到数据时先跑 probe.py（重要）

「同步成功，但作业/课表/考试都是 0」有四种可能：账号里确实没有、登录态掉了、
页面结构变了、或者查错了入口。别猜，直接让采集层把原始响应打出来：

```powershell
cd demo\collector
python probe.py --dump
```

输出会告诉你每一类的实情，例如（真实跑过的例子）：

```
[1] 登录: ok=True msg=cookie 有效
    账号: 某某 @ 某某大学 (uid=000000000)
[2] 课程 4 门:
    1. 高等数学（上） | 张老师 | courseid=111111111 clazzid=222222222
    ...
[3] 课表:
    result=1  schoolYear=2026 semester=1 maxWeek=25 currentWeek=15
    当前周课程数: 0
    第 1 周课程数: 0
    第 2 周课程数: 0
[4] 作业:
    《高等数学（上）》课程页 103082 字符, workEnc=有
      作业 0 份, 进度=(0, 0)
[5] 考试:  页面 6725 字符, dataTr 行数=0
[6] 通知:  取到 2 条
```

判断方法：

| probe 结果 | 说明 |
|---|---|
| `登录 ok=False` | 凭据/验证码问题，见 2.4 |
| `课程 0 门` | 账号或 cookie 不对，基本等于没登上 |
| `作业 0 份` 且 `workEnc=有` 且课程页很大 | 学习通里这课**确实没有作业**（列表页里是 `<div class="null-data">暂无作业</div>`） |
| `workEnc=无!` | 该课程未开放作业功能（正常现象，会记进 `errors`） |
| `课表 lessonArray 空` + 试几周都是 0 | 学习通课表里**没有录数据**（多数学校课表在教务系统，学习通课表要手动导入/绑定） |
| `dataTr 行数=0` | 没有考试安排 |
| 页面里出现登录页字样 | cookie 失效 |

`--dump` 会把原始 HTML/JSON 存到 `demo\collector\probe_out\`，可以直接用编辑器翻，
对着改 `client.py` 里的正则即可。`probe.py` 只做只读查询，每类一两次请求，放心跑。

### 2.6 作业抓不到时的兜底：从通知反查课程

有些账号（个人空间、测试号、或课程在别的"单位"下）**课程列表接口 `courselistdata`
返回 0 门课**，但作业通知里是带着线索的：

```
通知标题：作业:《111》新建作业20261104143059
附件 attachment.att_web：
  examOrWorkId = 58015147   ← workId
  courseId     = 268914623
  clazzId      = 159047090
  url          = https://mooc1-api.chaoxing.com/examApi/intoexamorwork?...&enc=...
```

采集层会跟着这个 url 跳转一次，从落地地址里抠出 `cpi`（作业列表接口必须要它），
凑齐 `courseid + clazzid + cpi` 后就能正常调作业列表接口。所以：

- **课程列表有课** → 走正常路径；
- **课程列表没课但通知里有作业** → 自动走这条兜底路径；
- 作业主键统一用 `hw:{workId}`，两条路径抓到同一份作业不会重复入库。

这也是"通知 7 条、作业 6 份"那种测试号的来历：`111` 这门课不在课程列表里，
但每条作业通知都指向它。

---

## 3. 换成 MySQL（正式一点的跑法）

### 3.1 建库

```powershell
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS notify_demo DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;"
```

### 3.2 让后端连上去

改 `demo\backend\src\main\resources\application.yml` 里的账号密码，
或者更推荐用环境变量（不改文件、不泄密）：

```powershell
$env:MYSQL_USER='root'
$env:MYSQL_PASSWORD='你的密码'
```

### 3.3 启动（不再带 h2 档）

```powershell
cd demo\backend
$env:JAVA_HOME='C:\Program Files\Microsoft\jdk-21.0.7.6-hotspot'
mvn spring-boot:run
```

表结构由 `db/schema.sql` 自动创建（`CREATE TABLE IF NOT EXISTS`，重复启动安全）。
自己看一眼数据：

```sql
USE notify_demo;
SELECT item_type, COUNT(*) FROM info_item GROUP BY item_type;
SELECT id, status, started_at, homework_count, notice_count, message FROM sync_log ORDER BY id DESC LIMIT 5;
```

---

## 4. 凭据与安全（登录界面 / 密码怎么存）

### 4.1 登录界面

页面右上角「登录学习通 / 切换账号」打开弹窗：

（登录弹窗截图已删除；弹窗里只有「手机号」「密码」「记住密码」三项。）

- 手机号 + 密码，勾不勾「记住密码」都行；
- 点「登录并同步」→ 登录成功后自动触发一轮同步，页面马上刷新；
- 已登录时弹窗里多一个「退出登录」，会清 cookie 和已保存的密码；
- 换账号就在这儿换，不用再改 `config.json`。

### 4.2 密码到底存在哪

| 情况 | 磁盘上 | 进程重启后 |
|---|---|---|
| 不勾「记住密码」 | **不存密码**，只存 `session_cookies.json` | 需要重新登录 |
| 勾了「记住密码」 | `password_enc`（AES-256-GCM 密文）+ `secret.key` | 自动解密，静默续登 |

具体做法：

1. **明文密码从不落盘**。`config.json` 里的 `password` 字段永远是空字符串，
   老版本留下的明文会在启动时自动迁移成密文并清空。
2. **密钥与配置分离**。`secret.key` 是首次使用时 `os.urandom(32)` 生成的，
   `config.json` 和 `secret.key` 都做了权限收紧（Windows `icacls` 只留当前用户，
   Linux/macOS `chmod 600`）。只拿到 config.json 解不开密码。
3. **接口不回显**。`/api/account` 只返回脱敏手机号（`138****0000`）、姓名、学校；
   任何响应里都没有 password 字段。
4. **日志不打印**。登录过程只打印"登录成功/失败"，不打印密码；
   手机号在页面与接口里一律脱敏。
5. **密码不经过 Java 后端**。登录走浏览器 → 采集服务（Vite 代理 `/collector` → :8801），
   Java 只负责业务数据。
6. **随时可清**。点「退出登录」或调 `POST /api/logout`，
   会删掉 cookie 与 `password_enc`，并把明文密码从内存里抹掉。

> 说明：这是"本机自用"级别的保护——能防住误传文件、误提交 git、
> 别人顺手翻你的 config.json；防不住已经拿到你 Windows 账户权限的人
> （他能读 `secret.key`）。真要多用户/公网部署，密码不该存在本地，
> 应该换成 OAuth/扫码登录 + 服务端会话。

---

## 4.3 可选：启用 Redis

demo 里 Redis 只做一件事——**同步互斥锁**（多实例部署时才有实际意义），
不装也完全能跑，代码会自动降级成进程内锁。

```powershell
$env:DEMO_REDIS='true'      # 或在 application.yml 里 demo.redis-enabled: true
```

---

## 5. 接口速查

### 采集服务 :8801

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/health` | 服务状态、是否 mock、有没有凭据/cookie（手机号脱敏） |
| GET | `/api/account` | 当前账号（**脱敏**）：登录状态、姓名、学校、`138****0000`、是否记住密码 |
| GET | `/api/login/status` | 旧接口，等价于 `/api/account` |
| POST | `/api/login` | `{phone,password,remember}` 登录；密码不落明文、不回显 |
| POST | `/api/logout` | 清 cookie + 清保存的密码 |
| POST | `/api/sync` | 触发一轮采集（异步，立刻返回） |
| GET | `/api/sync/status` | 采集进度：`idle/running/done/error` + 日志尾巴 |
| GET | `/api/data` | 最近一次成功的统一 JSON |
| GET | `/docs` | FastAPI 自动生成的接口文档 |

### 后端 :8080

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/api/sync` | 触发同步，`202` 开始 / `409` 已有一轮在跑 |
| GET | `/api/sync/status` | `{running, last:{...}}`，前端轮询用 |
| GET | `/api/overview` | 首页一把梭：四类列表 + 统计 + 上次同步 |
| GET | `/api/homework` | 作业（待办在前，按截止时间升序，已完成沉底） |
| GET | `/api/schedule` | 本周课表（按开始时间升序） |
| GET | `/api/exams` | 考试（待考在前，已结束沉底） |
| GET | `/api/notices` | 通知（最新在前） |
| GET | `/api/health` | 后端状态 + 采集服务是否在线 + 已入库条数 |

### 数据契约（采集层 → 后端）

```jsonc
{
  "source": "chaoxing",
  "schema": 1,
  "synced_at": "2026-11-04T16:30:00+08:00",
  "mock": false,
  "account": { "name": "...", "school": "...", "uid": "...", "fid": "..." },
  "week":    { "current": 11, "max": 20, "first_week_date": "2026-08-24" },
  "stats":   { "homework": 3, "schedule": 8, "exam": 1, "notice": 20, "errors": 0 },
  "errors":  ["《某课》作业拉取失败: ..."],
  "items": [
    {
      "source": "chaoxing",
      "item_type": "homework",          // homework | schedule | exam | notice
      "source_id": "hw:123456:789",     // 幂等键：同来源内唯一
      "title": "实验四 整体调试实验报告",
      "course": "数据结构与算法",
      "teacher": "陈老师",
      "location": "",
      "deadline": "2026-11-06T23:59:00+08:00",
      "start_time": null,
      "end_time": null,
      "status": "待提交",
      "url": "https://mooc1.chaoxing.com/mooc2/work/task?...",
      "raw": { },                        // 原始字段（对象形态）
      "raw_json": "{...}"                // 同一份内容的 JSON 文本，后端直接落库里
    }
  ]
}
```

约定：

- **时间一律 ISO8601 带 `+08:00`**，后端入库时统一换成北京时间。
- **`source_id` 是幂等键**：`(source, item_type, source_id)` 上有唯一约束，重复同步只会更新，不会重复插。
- 作业 `source_id` 用 URL 里的 `workId`（`hw:{workId}`）；课表用 `lessonId+星期+节次+教室`；考试用 `名称+开始时间`；通知用通知 id。
- **通知的 `start_time` 表示发布时间**（用来倒序排）。
- 某门课抓失败不会让整轮失败，只进 `errors` 数组，页面上显示在同步结果里。
- 以后接知到/QQ/微信，只要按同样 schema 产出、把 `source` 换掉即可，后端一行不用改。

---

## 6. 数据库表

`info_item`（统一事件表，所有来源所有类型一张表）

| 列 | 含义 |
|---|---|
| `source` | 来源：chaoxing / zhidao / qq / wechat / yuketang |
| `item_type` | homework / schedule / exam / notice |
| `source_id` | 来源内唯一键 |
| `title` / `course` / `teacher` / `location` | 展示字段 |
| `deadline` / `start_time` / `end_time` | 截止 / 开始 / 结束 |
| `status` | 学习通原始状态文案（待提交、已完成、未读…） |
| `url` | 点进去处理的原页面 |
| `raw_json` | 原始字段，本次只存不用 |
| `mock` | 1=假数据行。**真假数据互斥**：切到真实账号（或切回假数据）时，另一种模式的历史行会被清掉，避免页面上真假混排 |
| `account` | 这条数据属于哪个学习通账号（uid）。**换号时清掉别的账号的行**——否则 A 号的作业会挂在 B 号的页面下（踩过的坑） |
| `first_seen_at` / `updated_at` | 首次见到 / 最近一次见到 |

`sync_log`（每轮同步一条）

| 列 | 含义 |
|---|---|
| `status` | RUNNING / SUCCESS / FAILED |
| `started_at` / `finished_at` / `synced_at` | 开始 / 结束 / 数据生成时间 |
| `homework_count` … `notice_count` | 各类条数 |
| `mock` | 这轮是不是假数据 |
| `message` | 失败原因或采集器的局部错误汇总 |

---

## 7. 常见问题

**Q：`mvn` 报 `invalid target release: 21` / `UnsupportedClassVersionError`**
`JAVA_HOME` 还是 JDK 1.8。切到 21 再跑（见第 0 节）。

**Q：后端起来了，但页面右上角「采集服务未启动」**
采集服务没起或端口不对。先 `curl http://127.0.0.1:8801/api/health`，再看
`application.yml` 里 `demo.collector.base-url` 是否一致。

**Q：点同步后一直转圈**
看 `GET /api/sync/status`：`last.status=FAILED` 时 `message` 里就是原因。
最常见的是采集服务没登录（`未登录且自动登录失败`）或学习通变慢。

**Q：同步成功但页面空空**
先跑 `python probe.py`（见 2.5 节）。最常见的就是**账号里确实没有**：学习通课表未录入、
老师没在平台上布置作业。`client.py` 的解析函数都集中在文件上半部分（`parse_*`），
页面结构真变了就改那里，用 `probe_out/` 里的原始 HTML 对着调。

**Q：从假数据切到真实账号后，页面还显示旧的假数据**
本 demo 已处理这种情况（`info_item.mock` 列 + 同步时清理另一种模式的行）。
如果你是自己改过表结构的老库，删掉 `demo\backend\data\`（H2）或 `DROP TABLE info_item;`（MySQL），
重启会自动按最新 `schema.sql` 重建。

**Q：改了 config.json 却不生效（mock 切不过去 / 提示没凭据）**
八成是文件被存成了「UTF-8 带 BOM」。Windows 记事本和 PowerShell 的
`Set-Content -Encoding UTF8` 默认都会加 BOM，带 BOM 的 JSON 解析会失败。
采集层已用 `utf-8-sig` 兼容这种情况；如果仍不生效，用 VS Code 把编码改成 `UTF-8`
（不带 BOM）再保存，或直接调 `POST /api/login` 让程序自己写文件。

**Q：学习通页面中文乱码 / 解析函数匹配不到中文**
学习通部分页面 Header 声明的编码和实际字节不一致（声明 GBK、实际 UTF-8）。
采集层已在 `client.py` 的 `_fix_encoding()` 里按字节嗅探修正（先试 UTF-8，失败退回 GBK），
不要用 `resp.text` 直接读页面。

**Q：作业没有截止时间**
`config.json` 里 `with_details=false`。截止时间只在作业详情页上，必须逐份打开才能拿到。

**Q：怕被封号**
采集层已经做了：请求间隔 `throttle`、只读、失败不重试轰炸。
demo 默认**不开定时同步**（`demo.sync.auto-enabled=false`），你把按钮点烂才会多跑几轮。
想开 30 分钟自动同步：`$env:DEMO_AUTO_SYNC='true'`。

**Q：H2 数据乱了想重置**
停后端，删掉 `demo\backend\data\` 整个目录，再启动会重新建表。

**Q：端口被占用**
8801 / 8080 / 5273 任一被占用：改采集服务的 `--port`、后端的 `server.port`、
前端的 `server.port`（同时把 `vite.config.js` 里的代理 target 对上）。三者端口要互相对得住。

**Q：作业链接点开要求重新登录**
页面用的是学习通原始链接，浏览器里没有 cookie 时会跳登录页。这是学习通的正常行为，
不影响采集与展示。

---

## 8. 这一版**没**做的事
- ❌ agent / prompt / 大模型调用（`agent` 包只留了空说明）
- ❌ 知到、QQ、微信、雨课堂（schema 已按"可插拔"设计）
- ❌ 消息推送（Toast / 邮件 / 微信）
- ❌ 签到、刷课、答题等任何写操作（**永久不做**）
- ❌ 多用户 / 登录鉴权（demo 只服务一个账号）
- ❌ 全学期课表（只拉当前周，逐周合并要 ~20 次请求）
- ❌ 分页、搜索、已读回写

## 9. 下一步可以怎么加

1. **agent 层**：把 `info_item` 里近 7 天的作业/考试拼成 prompt，让模型输出"今天该干什么"，
   结果再落一张 `daily_brief` 表给前端展示。
2. **被动接收其他来源**：加 `POST /api/ingest`，让 QQ/微信适配器把同一 schema 推过来。
3. **定时 + 增量告警**：`sync_log` 已有基线，加"新增作业/成绩公布"判定即可推提醒。
4. **全学期课表**：`client.fetch_schedule(week)` 逐周合并，缓存 10 分钟。

## 10. 设计取舍（为什么这么分）

- **为什么 Python 抓、Java 存**：学习通是 HTML/JSON 混合的老式 Web 接口，Python 的
  `requests + re` 改起来最快；Java 侧负责事务、并发、幂等这些"正经后端"的活。
  两边的唯一契约就是那份 JSON。
- **为什么统一成一张 `info_item` 表**：作业/考试/课表/通知在"待办 + 时间 + 来源"这件事上
  结构一致，一张表就能做统一时间线；差异放进 `raw_json`。加新来源不用改表。
- **为什么幂等键放在采集层**：只有采集层知道"什么算同一条"（workId、lessonId…），
  后端只管 `upsert`，两边职责不打架。
- **为什么同步是异步的**：真实一轮 1~2 分钟，同步等会顶爆 HTTP 超时；异步 + 轮询
  让页面能显示进度，也让采集失败不影响请求。

## 11. 本版验证记录（写代码时实际跑过的东西）

| 验证项 | 结果 |
|---|---|
| 采集服务启动 + 四个接口 | ✅ `/api/health` `/api/login/status` `/api/sync` `/api/data` 均正常，假数据 19 条 |
| 后端编译 | ✅ `mvn -DskipTests package` BUILD SUCCESS（Java 21 / Boot 4.1.2） |
| 后端启动（H2 档） | ✅ `mvn spring-boot:run "-Dspring-boot.run.profiles=h2"` 与 `java -jar` 两种方式都起来 |
| 触发同步 → 入库 | ✅ 同步日志 SUCCESS：作业 4 / 课表 8 / 考试 2 / 通知 5，`/api/overview` 一致 |
| 幂等（重复同步） | ✅ 第二次同步仍是同一批 `source_id`，更新而非新增（`新增 0 条，更新 19 条`） |
| 前端 dev server + 生产构建 | ✅ `npm run dev` / `npm run build` 均成功 |
| 页面渲染 | ✅ 截图见 `docs/screenshot.png`，中文、倒计时、今日高亮、未读红点均正常 |
| H2 数据持久化 | ✅ 重启后端后 `items=19` 仍在 |
| **真实学习通账号（测试号）** | ✅ 登录成功；课程列表 0 门（个人空间），**靠"通知反查课程"抓到作业 6 份**、通知 7 条；考试 / 课表该号没有数据 |
| 真实账号（学生号） | ✅ 登录、4 门课程、2 条通知；该号学习通里确实没有作业/课表/考试（`probe.py` 已验证） |
| 换账号 | ✅ 改 config.json 手机号后自动强制重登；页面上也能「切换账号」直接登录；换号后旧账号的行会被清掉（`info_item.account`），两个号的数据不会混 |
| 登录界面 | ✅ 页面上手机号+密码登录 → 自动同步；错误密码返回「用户名或密码错误」 |
| 密码安全 | ✅ 明文不落盘（`password` 恒为空）、`password_enc` 为 AES-256-GCM 密文、`secret.key` ACL 仅当前用户、接口与日志均不出现密码、手机号显示为 `138****0000` |
| 退出登录 | ✅ 清 cookie + 清 `password_enc` |
| 真假数据切换 | ✅ 切模式时自动清掉另一种模式的历史行 |
| MySQL 档 | ⚠️ 未验证（本机 MySQL 需要密码，脚本按 `schema.sql` 通用语法编写） |

把上面两个 ⚠️ 跑通，这个 demo 就算真正闭环了。

---

参考文献：协议层移植自参考项目 `xuexitong-cli`（MIT）的 `xuexitong_mcp/client.py`，
裁掉 MCP server / CLI / 桌面小窗，只保留登录、会话与四类只读接口。
