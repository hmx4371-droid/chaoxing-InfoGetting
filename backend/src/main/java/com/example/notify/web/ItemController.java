package com.example.notify.web;

import com.example.notify.collector.CollectorClient;
import com.example.notify.config.DemoProperties;
import com.example.notify.item.InfoItemService;
import com.example.notify.item.ItemView;
import com.example.notify.sync.SyncLogView;
import com.example.notify.sync.SyncService;
import com.example.notify.sync.SyncStatusResponse;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** 查询类接口：一次性总览 + 四类分页列表（demo 不分页，量小）。 */
@RestController
@RequestMapping("/api")
public class ItemController {

    private final InfoItemService itemService;
    private final SyncService syncService;
    private final CollectorClient collector;
    private final DemoProperties props;

    public ItemController(InfoItemService itemService, SyncService syncService,
                          CollectorClient collector, DemoProperties props) {
        this.itemService = itemService;
        this.syncService = syncService;
        this.collector = collector;
        this.props = props;
    }

    /** 首页总览：作业 / 课表 / 考试 / 通知 + 上次同步信息。 */
    @GetMapping("/overview")
    public Overview overview() {
        List<ItemView> homework = itemService.homework();
        List<ItemView> schedule = itemService.schedule();
        List<ItemView> exams = itemService.exams();
        List<ItemView> notices = itemService.notices();
        SyncStatusResponse sync = syncService.status();
        SyncLogView last = sync.last();
        return new Overview(
                homework, schedule, exams, notices,
                (int) homework.stream().filter(ItemView::pending).count(),
                (int) notices.stream().filter(ItemView::pending).count(),
                last, sync.running());
    }

    @GetMapping("/homework")
    public List<ItemView> homework() {
        return itemService.homework();
    }

    @GetMapping("/schedule")
    public List<ItemView> schedule() {
        return itemService.schedule();
    }

    @GetMapping("/exams")
    public List<ItemView> exams() {
        return itemService.exams();
    }

    @GetMapping("/notices")
    public List<ItemView> notices() {
        return itemService.notices();
    }

    /** 健康检查：顺带告诉前端采集服务有没有起来。 */
    @GetMapping("/health")
    public Map<String, Object> health() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("ok", true);
        body.put("service", "notify-demo-backend");
        body.put("collector_url", props.collector().baseUrlOrDefault());
        body.put("collector_online", collector.ping());
        body.put("items", itemService.total());
        return body;
    }
}
