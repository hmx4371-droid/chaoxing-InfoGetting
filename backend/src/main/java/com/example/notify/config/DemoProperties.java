package com.example.notify.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * application.yml 里 {@code demo.*} 的配置。
 *
 * @param collector    采集服务地址与超时
 * @param sync         同步策略（等待超时、轮询间隔、定时任务开关）
 * @param redisEnabled 是否启用 Redis（同步锁）；false 时降级为进程内锁
 */
@ConfigurationProperties(prefix = "demo")
public record DemoProperties(Collector collector, Sync sync, boolean redisEnabled) {

    public record Collector(String baseUrl, int readTimeoutSeconds) {
        public String baseUrlOrDefault() {
            return baseUrl == null || baseUrl.isBlank() ? "http://127.0.0.1:8801" : baseUrl;
        }

        public int readTimeoutSecondsOrDefault() {
            return readTimeoutSeconds <= 0 ? 120 : readTimeoutSeconds;
        }
    }

    public record Sync(boolean autoEnabled, String cron,
                       int waitTimeoutSeconds, long pollIntervalMs) {
        public int waitTimeoutSecondsOrDefault() {
            return waitTimeoutSeconds <= 0 ? 300 : waitTimeoutSeconds;
        }

        public long pollIntervalMsOrDefault() {
            return pollIntervalMs <= 0 ? 1500L : pollIntervalMs;
        }
    }
}
