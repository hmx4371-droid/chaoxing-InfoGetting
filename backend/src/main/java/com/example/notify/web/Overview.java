package com.example.notify.web;

import com.example.notify.item.ItemView;
import com.example.notify.sync.SyncLogView;
import java.util.List;

/**
 * 首页一次性拿全的数据：四类列表 + 统计 + 上次同步信息。
 *
 * <p>前端只调这一个接口就够，省掉四次往返。
 */
public record Overview(
        List<ItemView> homework,
        List<ItemView> schedule,
        List<ItemView> exams,
        List<ItemView> notices,
        int pendingHomework,
        int unreadNotices,
        SyncLogView lastSync,
        boolean syncing) {
}
