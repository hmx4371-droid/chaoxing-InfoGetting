package com.example.notify.sync;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;

/** 每轮同步的执行日志（前端据此显示"上次同步时间/结果"）。 */
@TableName("sync_log")
public class SyncLog {

    public static final String RUNNING = "RUNNING";
    public static final String SUCCESS = "SUCCESS";
    public static final String FAILED = "FAILED";

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    private String source;
    private String status;
    private LocalDateTime startedAt;
    private LocalDateTime finishedAt;
    private LocalDateTime syncedAt;
    private Integer homeworkCount;
    private Integer scheduleCount;
    private Integer examCount;
    private Integer noticeCount;
    private Boolean mock;

    /** 这轮采集用的学习通账号（姓名 / 学校），页面上要显示出来，避免多账号搞混 */
    private String accountName;
    private String accountSchool;

    private String message;

    public static SyncLog running(String source) {
        SyncLog row = new SyncLog();
        row.setSource(source);
        row.setStatus(RUNNING);
        row.setStartedAt(LocalDateTime.now());
        row.setHomeworkCount(0);
        row.setScheduleCount(0);
        row.setExamCount(0);
        row.setNoticeCount(0);
        row.setMock(false);
        return row;
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getSource() {
        return source;
    }

    public void setSource(String source) {
        this.source = source;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public LocalDateTime getStartedAt() {
        return startedAt;
    }

    public void setStartedAt(LocalDateTime startedAt) {
        this.startedAt = startedAt;
    }

    public LocalDateTime getFinishedAt() {
        return finishedAt;
    }

    public void setFinishedAt(LocalDateTime finishedAt) {
        this.finishedAt = finishedAt;
    }

    public LocalDateTime getSyncedAt() {
        return syncedAt;
    }

    public void setSyncedAt(LocalDateTime syncedAt) {
        this.syncedAt = syncedAt;
    }

    public Integer getHomeworkCount() {
        return homeworkCount;
    }

    public void setHomeworkCount(Integer homeworkCount) {
        this.homeworkCount = homeworkCount;
    }

    public Integer getScheduleCount() {
        return scheduleCount;
    }

    public void setScheduleCount(Integer scheduleCount) {
        this.scheduleCount = scheduleCount;
    }

    public Integer getExamCount() {
        return examCount;
    }

    public void setExamCount(Integer examCount) {
        this.examCount = examCount;
    }

    public Integer getNoticeCount() {
        return noticeCount;
    }

    public void setNoticeCount(Integer noticeCount) {
        this.noticeCount = noticeCount;
    }

    public Boolean getMock() {
        return mock;
    }

    public void setMock(Boolean mock) {
        this.mock = mock;
    }

    public String getMessage() {
        return message;
    }
    public void setMessage(String message) {
        this.message = message;
    }

    public String getAccountName() {
        return accountName;
    }

    public void setAccountName(String accountName) {
        this.accountName = accountName;
    }

    public String getAccountSchool() {
        return accountSchool;
    }

    public void setAccountSchool(String accountSchool) {
        this.accountSchool = accountSchool;
    }
}
