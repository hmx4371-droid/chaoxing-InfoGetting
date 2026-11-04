package com.example.notify.web;

import com.example.notify.sync.SyncService;
import com.example.notify.sync.SyncStartResult;
import com.example.notify.sync.SyncStatusResponse;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** 同步相关接口：触发一轮采集、查询进度。 */
@RestController
@RequestMapping("/api/sync")
public class SyncController {

    private final SyncService syncService;

    public SyncController(SyncService syncService) {
        this.syncService = syncService;
    }

    /**
     * 触发一轮同步。采集是异步的：立刻返回 202，进度看 {@code /api/sync/status}。
     */
    @PostMapping
    public ResponseEntity<SyncStartResult> sync() {
        SyncStartResult result = syncService.trigger("manual");
        return ResponseEntity.status(result.started() ? HttpStatus.ACCEPTED : HttpStatus.CONFLICT)
                .body(result);
    }

    @GetMapping("/status")
    public SyncStatusResponse status() {
        return syncService.status();
    }
}
