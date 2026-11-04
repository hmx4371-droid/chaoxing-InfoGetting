package com.example.notify.sync;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.example.notify.collector.CollectorClient;
import com.example.notify.collector.dto.CollectorPayload;
import com.example.notify.collector.dto.CollectorSyncStatus;
import com.example.notify.config.DemoProperties;
import com.example.notify.item.InfoItemService;
import jakarta.annotation.PreDestroy;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

/**
 * 一轮同步的编排：触采集 → 等采集器跑完 → 取统一 JSON → 幂等入库 → 记日志。
 *
 * <p>对外是异步的：{@code POST /api/sync} 立刻返回，前端轮询 {@code /api/sync/status}。
 * 采集器一轮可能要 1~2 分钟（逐份作业详情），不能占着 HTTP 线程。
 */
@Service
public class SyncService {

    private static final Logger log = LoggerFactory.getLogger(SyncService.class);
    private static final ZoneId TZ = ZoneId.of("Asia/Shanghai");
    private static final String SOURCE = "chaoxing";

    private final CollectorClient collector;
    private final InfoItemService itemService;
    private final SyncLogMapper logMapper;
    private final SyncGuard guard;
    private final DemoProperties props;

    private final ExecutorService worker = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "chaoxing-sync");
        t.setDaemon(true);
        return t;
    });
    private final AtomicReference<Long> currentLogId = new AtomicReference<>();

    public SyncService(CollectorClient collector, InfoItemService itemService,
                       SyncLogMapper logMapper, SyncGuard guard, DemoProperties props) {
        this.collector = collector;
        this.itemService = itemService;
        this.logMapper = logMapper;
        this.guard = guard;
        this.props = props;
    }

    /** 触发一轮同步（不阻塞）。 */
    public SyncStartResult trigger(String trigger) {
        if (!guard.tryAcquire()) {
            return new SyncStartResult(false, "已有一轮同步正在进行中，请稍候", currentLogId.get());
        }
        SyncLog row = SyncLog.running(SOURCE);
        try {
            logMapper.insert(row);
        } catch (RuntimeException e) {
            guard.release();
            throw e;
        }
        currentLogId.set(row.getId());
        log.info("开始同步（触发方式：{}），日志 #{}", trigger, row.getId());
        worker.submit(() -> runOnce(row.getId()));
        return new SyncStartResult(true, "同步已开始，正在从学习通拉取数据", row.getId());
    }

    /** 最近一次同步状态 + 是否正在跑。 */
    public SyncStatusResponse status() {
        List<SyncLog> rows = logMapper.selectList(
                new QueryWrapper<SyncLog>().orderByDesc("id").last("limit 1"));
        SyncLogView last = rows.isEmpty() ? null : SyncLogView.of(rows.get(0));
        return new SyncStatusResponse(guard.isBusy(), last);
    }

    /** 定时自动同步：demo 默认关闭（demo.sync.auto-enabled）。 */
    @Scheduled(cron = "${demo.sync.cron:0 */30 * * * *}")
    public void scheduledSync() {
        if (!props.sync().autoEnabled()) {
            return;
        }
        SyncStartResult result = trigger("schedule");
        if (!result.started()) {
            log.debug("定时同步跳过：{}", result.message());
        }
    }

    // ---------------------------------------------------------------- 内部

    private void runOnce(Long logId) {
        long begin = System.currentTimeMillis();
        try {
            CollectorPayload payload = collectFromCollector();
            String account = "unknown";
            if (payload.account() != null && payload.account().uid() != null
                    && !payload.account().uid().isBlank()) {
                account = payload.account().uid();
            }
            InfoItemService.UpsertResult counts =
                    itemService.upsertAll(payload.itemsOrEmpty(), payload.isMock(), account);

            SyncLog done = new SyncLog();
            done.setId(logId);
            done.setStatus(SyncLog.SUCCESS);
            done.setFinishedAt(LocalDateTime.now());
            done.setSyncedAt(parseTime(payload.syncedAt()));
            done.setHomeworkCount(counts.homework());
            done.setScheduleCount(counts.schedule());
            done.setExamCount(counts.exam());
            done.setNoticeCount(counts.notice());
            done.setMock(payload.isMock());
            if (payload.account() != null) {
                done.setAccountName(payload.account().name());
                done.setAccountSchool(payload.account().school());
            }
            done.setMessage(summarize(payload));
            logMapper.updateById(done);

            log.info("同步成功：{} 条，用时 {} ms", counts.total(), System.currentTimeMillis() - begin);
        } catch (Exception e) {
            log.warn("同步失败", e);
            fail(logId, rootMessage(e));
        } finally {
            guard.release();
        }
    }

    /** 触发采集器并等它跑完，然后取回统一 JSON。 */
    private CollectorPayload collectFromCollector() throws InterruptedException {
        CollectorSyncStatus status = collector.startSync();
        long deadline = System.currentTimeMillis()
                + props.sync().waitTimeoutSecondsOrDefault() * 1000L;
        while (status != null && status.isRunning()) {
            if (System.currentTimeMillis() > deadline) {
                throw new IllegalStateException("等待采集服务超时（超过 "
                        + props.sync().waitTimeoutSecondsOrDefault() + " 秒）");
            }
            Thread.sleep(props.sync().pollIntervalMsOrDefault());
            status = collector.syncStatus();
        }
        if (status != null && status.isError()) {
            throw new IllegalStateException("采集失败：" + status.error());
        }
        return collector.fetchData();
    }

    private void fail(Long logId, String message) {
        SyncLog row = new SyncLog();
        row.setId(logId);
        row.setStatus(SyncLog.FAILED);
        row.setFinishedAt(LocalDateTime.now());
        row.setMessage(message != null && message.length() > 900
                ? message.substring(0, 900) : message);
        try {
            logMapper.updateById(row);
        } catch (RuntimeException e) {
            log.error("写同步失败日志也失败了", e);
        }
    }

    /** 采集器上报的局部错误（某门课作业拉取失败等）也记进日志，便于排查。 */
    private String summarize(CollectorPayload payload) {
        List<String> errors = payload.errors();
        if (errors == null || errors.isEmpty()) {
            return null;
        }
        String joined = String.join("; ", errors);
        return joined.length() > 900 ? joined.substring(0, 900) : joined;
    }

    private LocalDateTime parseTime(String iso) {
        if (iso == null || iso.isBlank()) {
            return LocalDateTime.now();
        }
        try {
            return OffsetDateTime.parse(iso).atZoneSameInstant(TZ).toLocalDateTime();
        } catch (RuntimeException e) {
            return LocalDateTime.now();
        }
    }

    private String rootMessage(Throwable e) {
        Throwable cur = e;
        while (cur.getCause() != null && cur.getCause() != cur) {
            cur = cur.getCause();
        }
        String msg = cur.getMessage();
        if (msg == null || msg.isBlank()) {
            return cur.getClass().getSimpleName();
        }
        return "采集服务不可用或返回异常：" + msg;
    }

    @PreDestroy
    public void shutdown() {
        worker.shutdownNow();
    }
}
