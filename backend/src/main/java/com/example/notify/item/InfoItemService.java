package com.example.notify.item;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.example.notify.collector.dto.CollectorItem;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * 统一事件表的读写：幂等 upsert + 四类列表查询（排序在这一层做完，前端只渲染）。
 */
@Service
public class InfoItemService {

    private static final Logger log = LoggerFactory.getLogger(InfoItemService.class);

    /** 出现这些字样的作业视为"已交/已批"，不再计入待办。 */
    private static final Set<String> DONE_MARKS =
            Set.of("已完成", "已提交", "待批阅", "已批阅", "已批改");

    private static final ZoneId TZ = ZoneId.of("Asia/Shanghai");

    private final InfoItemMapper mapper;

    public InfoItemService(InfoItemMapper mapper) {
        this.mapper = mapper;
    }

    /** 一轮同步的入库统计。 */
    public record UpsertResult(int homework, int schedule, int exam, int notice) {
        public int total() {
            return homework + schedule + exam + notice;
        }
    }

    /**
     * 把采集结果写库：按 {@code (source, item_type, source_id)} 存在则更新、否则插入。
     *
     * <p>先用一条查询把该来源已有行读进内存做匹配，避免每条一次 SELECT。
     *
     * @param mock    本轮数据是否来自假数据。假数据与真实数据互斥：切模式时先把另一种
     *                模式的历史行清掉，否则页面上会真假混排
     * @param account 本轮采集的学习通账号（uid）。换号时清掉别的账号的行——否则
     *                A 号的内容会挂在 B 号的页面下，看着"内容不对"
     */
    public UpsertResult upsertAll(List<CollectorItem> items, boolean mock, String account) {
        LocalDateTime now = LocalDateTime.now();
        String owner = account == null || account.isBlank() ? "unknown" : account;

        int removedMock = mapper.delete(new QueryWrapper<InfoItem>().ne("mock", mock ? 1 : 0));
        int removedOther = mapper.delete(new QueryWrapper<InfoItem>()
                .and(w -> w.ne("account", owner).or().isNull("account")));
        if (removedMock + removedOther > 0) {
            log.info("清理不属于本轮的数据 {} 条（mock={}, account={}）", removedMock + removedOther, mock, owner);
        }

        Map<String, InfoItem> existing = new HashMap<>();
        if (!items.isEmpty()) {
            String source = items.get(0).source() == null ? "chaoxing" : items.get(0).source();
            List<InfoItem> rows = mapper.selectList(
                    new QueryWrapper<InfoItem>().eq("source", source));
            for (InfoItem row : rows) {
                existing.put(key(row.getItemType(), row.getSourceId()), row);
            }
        }

        int[] counts = new int[4];
        int inserted = 0;
        int updated = 0;
        for (CollectorItem src : items) {
            if (src.itemType() == null || src.sourceId() == null) {
                continue;
            }
            String k = key(src.itemType(), src.sourceId());
            InfoItem row = existing.get(k);
            if (row == null) {
                row = new InfoItem();
                row.setSource(src.source() == null ? "chaoxing" : src.source());
                row.setItemType(src.itemType());
                row.setSourceId(truncate(src.sourceId(), 190));
                row.setFirstSeenAt(now);
                row.setMock(mock);
                row.setAccount(owner);
                applyFields(row, src, now);
                mapper.insert(row);
                existing.put(k, row);
                inserted++;
            } else {
                applyFields(row, src, now);
                row.setMock(mock);
                row.setAccount(owner);
                mapper.updateById(row);
                updated++;
            }
            int idx = switch (src.itemType()) {
                case "homework" -> 0;
                case "schedule" -> 1;
                case "exam" -> 2;
                case "notice" -> 3;
                default -> -1;
            };
            if (idx >= 0) {
                counts[idx]++;
            }
        }
        log.info("入库完成：新增 {} 条，更新 {} 条", inserted, updated);
        return new UpsertResult(counts[0], counts[1], counts[2], counts[3]);
    }

    private void applyFields(InfoItem row, CollectorItem src, LocalDateTime now) {
        row.setTitle(truncate(src.title() == null || src.title().isBlank() ? "（无标题）" : src.title(), 500));
        row.setCourse(truncate(src.course(), 200));
        row.setTeacher(truncate(src.teacher(), 100));
        row.setLocation(truncate(src.location(), 200));
        row.setDeadline(toLocal(src.deadline()));
        row.setStartTime(toLocal(src.startTime()));
        row.setEndTime(toLocal(src.endTime()));
        row.setStatus(truncate(src.status(), 64));
        row.setUrl(truncate(src.url(), 1000));
        row.setRawJson(src.rawJson());
        row.setUpdatedAt(now);
    }

    // ---------------------------------------------------------------- 查询

    public List<ItemView> homework() {
        List<ItemView> list = byType("homework");
        list.sort(Comparator
                .comparing((ItemView v) -> !v.pending())          // 待办在前
                .thenComparing(ItemView::deadline, Comparator.nullsLast(Comparator.naturalOrder())));
        return list;
    }

    public List<ItemView> schedule() {
        List<ItemView> list = byType("schedule");
        list.sort(Comparator.comparing(ItemView::startTime,
                Comparator.nullsLast(Comparator.naturalOrder())));
        return list;
    }

    public List<ItemView> exams() {
        LocalDateTime now = LocalDateTime.now();
        List<ItemView> upcoming = new ArrayList<>();
        List<ItemView> past = new ArrayList<>();
        for (ItemView v : byType("exam")) {
            boolean isPast = v.endTime() != null && v.endTime().isBefore(now);
            (isPast ? past : upcoming).add(v);
        }
        upcoming.sort(Comparator.comparing(ItemView::startTime,
                Comparator.nullsLast(Comparator.naturalOrder())));
        past.sort(Comparator.comparing(ItemView::startTime,
                Comparator.nullsLast(Comparator.reverseOrder())));
        upcoming.addAll(past);
        return upcoming;
    }

    public List<ItemView> notices() {
        List<ItemView> list = byType("notice");
        list.sort(Comparator.comparing(ItemView::startTime,
                Comparator.nullsLast(Comparator.reverseOrder())));
        return list;
    }

    public long total() {
        Long count = mapper.selectCount(new QueryWrapper<>());
        return count == null ? 0 : count;
    }

    private List<ItemView> byType(String type) {
        List<InfoItem> rows = mapper.selectList(
                new QueryWrapper<InfoItem>().eq("item_type", type));
        List<ItemView> views = new ArrayList<>(rows.size());
        for (InfoItem row : rows) {
            boolean pending = switch (type) {
                case "homework" -> isHomeworkPending(row.getStatus());
                case "notice" -> "未读".equals(row.getStatus());
                default -> false;
            };
            views.add(ItemView.of(row, pending));
        }
        return views;
    }

    /** 作业是否还需要交：已完成/已提交/待批阅都不算待办。 */
    public static boolean isHomeworkPending(String status) {
        String s = status == null ? "" : status.trim();
        return DONE_MARKS.stream().noneMatch(s::contains);
    }

    // ---------------------------------------------------------------- 工具

    private static String key(String type, String sourceId) {
        return type + "|" + sourceId;
    }

    /** 采集器的 +08:00 时间统一换算成本地时间入库。 */
    private static LocalDateTime toLocal(OffsetDateTime dt) {
        return dt == null ? null : dt.atZoneSameInstant(TZ).toLocalDateTime();
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return null;
        }
        return s.length() <= max ? s : s.substring(0, max);
    }
}
