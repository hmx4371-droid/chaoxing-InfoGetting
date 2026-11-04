package com.example.notify.item;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;

/**
 * 统一信息事件表实体：所有来源、所有类型共一张表。
 *
 * <p>{@code (source, itemType, sourceId)} 上有唯一约束，保证重复同步是幂等的。
 */
@TableName("info_item")
public class InfoItem {

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /** 来源：chaoxing / zhidao / qq / wechat / yuketang */
    private String source;

    /** 类型：homework / schedule / exam / notice */
    private String itemType;

    /** 来源内唯一键，幂等 upsert 用 */
    private String sourceId;

    private String title;
    private String course;
    private String teacher;
    private String location;

    /** 截止时间（作业/考试） */
    private LocalDateTime deadline;

    /** 开始：上课 / 考试开始 / 作答开始 / 通知发布时间 */
    private LocalDateTime startTime;

    /** 结束：下课 / 考试结束 */
    private LocalDateTime endTime;

    private String status;
    private String url;

    /** 采集器保留的原始字段（JSON 文本，演示阶段只存不用） */
    private String rawJson;

    /** 1=假数据行：从假数据切到真实账号（或反向）时，另一模式的历史行会被清掉 */
    private Boolean mock;

    /** 属于哪个学习通账号（uid）：换号后旧账号的行要清掉，否则两个号的数据混在一张表里 */
    private String account;

    private LocalDateTime firstSeenAt;
    private LocalDateTime updatedAt;

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

    public String getItemType() {
        return itemType;
    }

    public void setItemType(String itemType) {
        this.itemType = itemType;
    }

    public String getSourceId() {
        return sourceId;
    }

    public void setSourceId(String sourceId) {
        this.sourceId = sourceId;
    }

    public String getTitle() {
        return title;
    }

    public void setTitle(String title) {
        this.title = title;
    }

    public String getCourse() {
        return course;
    }

    public void setCourse(String course) {
        this.course = course;
    }

    public String getTeacher() {
        return teacher;
    }

    public void setTeacher(String teacher) {
        this.teacher = teacher;
    }

    public String getLocation() {
        return location;
    }

    public void setLocation(String location) {
        this.location = location;
    }

    public LocalDateTime getDeadline() {
        return deadline;
    }

    public void setDeadline(LocalDateTime deadline) {
        this.deadline = deadline;
    }

    public LocalDateTime getStartTime() {
        return startTime;
    }

    public void setStartTime(LocalDateTime startTime) {
        this.startTime = startTime;
    }

    public LocalDateTime getEndTime() {
        return endTime;
    }

    public void setEndTime(LocalDateTime endTime) {
        this.endTime = endTime;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public String getUrl() {
        return url;
    }

    public void setUrl(String url) {
        this.url = url;
    }

    public String getRawJson() {
        return rawJson;
    }

    public void setRawJson(String rawJson) {
        this.rawJson = rawJson;
    }

    public Boolean getMock() {
        return mock;
    }

    public void setMock(Boolean mock) {
        this.mock = mock;
    }

    public String getAccount() {
        return account;
    }

    public void setAccount(String account) {
        this.account = account;
    }

    public LocalDateTime getFirstSeenAt() {
        return firstSeenAt;
    }
    public void setFirstSeenAt(LocalDateTime firstSeenAt) {
        this.firstSeenAt = firstSeenAt;
    }

    public LocalDateTime getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(LocalDateTime updatedAt) {
        this.updatedAt = updatedAt;
    }
}
