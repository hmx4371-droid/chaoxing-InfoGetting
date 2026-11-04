package com.example.notify.collector.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.OffsetDateTime;

/**
 * 一条统一事件（作业 / 课表 / 考试 / 通知）。
 *
 * <p>{@code sourceId} 是幂等键：同一来源内唯一，重复同步只会更新已有行。
 * {@code raw} 是原始对象（给人/agent 看），{@code rawJson} 是同一份内容的 JSON 文本
 * （直接落库，Java 侧不解析）。
 *
 * <p>多词字段必须显式标注 JSON 名：反序列化走的是 RestClient 的默认 JsonMapper，
 * 不套用全局 snake_case 命名策略（详见 {@link CollectorPayload} 的说明）。
 */
public record CollectorItem(
        String source,
        @JsonProperty("item_type") String itemType,
        @JsonProperty("source_id") String sourceId,
        String title,
        String course,
        String teacher,
        String location,
        OffsetDateTime deadline,
        @JsonProperty("start_time") OffsetDateTime startTime,
        @JsonProperty("end_time") OffsetDateTime endTime,
        String status,
        String url,
        @JsonProperty("raw_json") String rawJson) {
}
