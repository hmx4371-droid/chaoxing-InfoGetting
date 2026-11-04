package com.example.notify.sync;

/** {@code POST /api/sync} 的响应。 */
public record SyncStartResult(boolean started, String message, Long logId) {
}
