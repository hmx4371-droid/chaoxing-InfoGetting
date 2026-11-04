package com.example.notify;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * 通知整合系统 demo 后端入口。
 *
 * <p>职责：把学习通采集服务（Python，:8801）产出的统一 JSON 落进 MySQL 的统一事件表，
 * 再提供给前端查询。本 demo 不接 agent（见 {@code com.example.notify.agent}）。
 */
@SpringBootApplication
@EnableScheduling
@ConfigurationPropertiesScan
public class NotifyDemoApplication {

    public static void main(String[] args) {
        SpringApplication.run(NotifyDemoApplication.class, args);
    }
}
