package com.example.notify.sync;

/** {@code GET /api/sync/status} 的响应：当前是否在跑 + 最近一次结果。 */
public record SyncStatusResponse(boolean running, SyncLogView last) {
}
