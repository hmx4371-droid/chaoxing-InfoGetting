package com.example.notify.collector.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/** 采集服务 {@code /api/sync} 与 {@code /api/sync/status} 的响应。 */
public record CollectorSyncStatus(
        String state,
        @JsonProperty("started_at") String startedAt,
        @JsonProperty("finished_at") String finishedAt,
        String error,
        Object stats,
        @JsonProperty("has_data") Boolean hasData,
        @JsonProperty("synced_at") String syncedAt,
        Boolean mock) {

    public boolean isRunning() {
        return "running".equalsIgnoreCase(state);
    }

    public boolean isError() {
        return "error".equalsIgnoreCase(state);
    }

    public boolean isDone() {
        return "done".equalsIgnoreCase(state);
    }
}
