package com.example.notify.item;

import java.time.LocalDateTime;

/**
 * 给前端的列表视图（不含 raw_json，避免把原始报文顶到页面上）。
 *
 * <p>{@code pending} 表示"还需要关注"：作业未交、通知未读等。前端排序直接用它。
 */
public record ItemView(
        Long id,
        String itemType,
        String title,
        String course,
        String teacher,
        String location,
        LocalDateTime deadline,
        LocalDateTime startTime,
        LocalDateTime endTime,
        String status,
        String url,
        boolean pending,
        LocalDateTime firstSeenAt,
        LocalDateTime updatedAt) {

    public static ItemView of(InfoItem item, boolean pending) {
        return new ItemView(
                item.getId(), item.getItemType(), item.getTitle(), item.getCourse(),
                item.getTeacher(), item.getLocation(), item.getDeadline(),
                item.getStartTime(), item.getEndTime(), item.getStatus(), item.getUrl(),
                pending, item.getFirstSeenAt(), item.getUpdatedAt());
    }
}
