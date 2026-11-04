package com.example.notify.sync;

import java.time.LocalDateTime;

/** 同步日志的对外视图。 */
public record SyncLogView(
        Long id,
        String status,
        LocalDateTime startedAt,
        LocalDateTime finishedAt,
        LocalDateTime syncedAt,
        int homeworkCount,
        int scheduleCount,
        int examCount,
        int noticeCount,
        boolean mock,
        String accountName,
        String accountSchool,
        String message) {

    public static SyncLogView of(SyncLog row) {
        return new SyncLogView(
                row.getId(), row.getStatus(), row.getStartedAt(), row.getFinishedAt(),
                row.getSyncedAt(), nz(row.getHomeworkCount()), nz(row.getScheduleCount()),
                nz(row.getExamCount()), nz(row.getNoticeCount()),
                Boolean.TRUE.equals(row.getMock()),
                row.getAccountName(), row.getAccountSchool(), row.getMessage());
    }

    private static int nz(Integer v) {
        return v == null ? 0 : v;
    }
}
