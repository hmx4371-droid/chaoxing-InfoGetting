package com.example.notify.collector.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

/**
 * 采集服务（Python）返回的统一 JSON 顶层结构。
 *
 * <p>字段名用 {@link JsonProperty} 显式标注：RestClient 自己构造时用的是默认
 * JsonMapper，不会套用 application.yml 里的 {@code spring.jackson.property-naming-strategy}，
 * 所以这里不能指望 snake_case 自动转换。
 */
public record CollectorPayload(
        String source,
        Integer schema,
        @JsonProperty("synced_at") String syncedAt,
        @JsonProperty("elapsed_ms") Integer elapsedMs,
        Boolean mock,
        Account account,
        Week week,
        Stats stats,
        List<String> errors,
        List<CollectorItem> items) {

    public record Account(String name, String school, String uid, String fid) {
    }

    public record Week(Integer current, Integer max,
                       @JsonProperty("first_week_date") String firstWeekDate,
                       @JsonProperty("school_year") String schoolYear,
                       String semester,
                       @JsonProperty("lesson_count") Integer lessonCount) {
    }

    public record Stats(Integer homework, Integer schedule, Integer exam,
                        Integer notice, Integer errors) {
    }

    public boolean isMock() {
        return Boolean.TRUE.equals(mock);
    }

    public List<CollectorItem> itemsOrEmpty() {
        return items == null ? List.of() : items;
    }
}
