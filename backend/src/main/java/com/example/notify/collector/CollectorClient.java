package com.example.notify.collector;

import com.example.notify.collector.dto.CollectorPayload;
import com.example.notify.collector.dto.CollectorSyncStatus;
import com.example.notify.config.DemoProperties;
import java.net.http.HttpClient;
import java.time.Duration;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

/**
 * 学习通采集服务（Python FastAPI）的 HTTP 客户端。
 *
 * <p>三个动作：触发一轮采集、轮询进度、取回统一 JSON。
 * 采集本身是异步的（逐份作业详情可能要 1~2 分钟），所以这里不设短超时。
 */
@Component
public class CollectorClient {

    private final RestClient http;

    public CollectorClient(DemoProperties props) {
        HttpClient jdk = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(5))
                .version(HttpClient.Version.HTTP_1_1)
                .build();
        JdkClientHttpRequestFactory factory = new JdkClientHttpRequestFactory(jdk);
        factory.setReadTimeout(Duration.ofSeconds(props.collector().readTimeoutSecondsOrDefault()));
        // 自己构造 RestClient，不依赖自动配置的 RestClient.Builder（Spring Boot 4 默认不提供该 bean）
        this.http = RestClient.builder()
                .baseUrl(props.collector().baseUrlOrDefault())
                .requestFactory(factory)
                .build();
    }

    /** 触发一轮采集（采集服务内部异步执行，立刻返回当前状态）。 */
    public CollectorSyncStatus startSync() {
        return http.post().uri("/api/sync").retrieve().body(CollectorSyncStatus.class);
    }

    /** 查询采集进度。 */
    public CollectorSyncStatus syncStatus() {
        return http.get().uri("/api/sync/status").retrieve().body(CollectorSyncStatus.class);
    }

    /** 取回最近一次成功的统一 JSON。 */
    public CollectorPayload fetchData() {
        return http.get().uri("/api/data").retrieve().body(CollectorPayload.class);
    }

    /** 采集服务是否在线（给前端显示"采集服务未启动"用）。 */
    public boolean ping() {
        try {
            http.get().uri("/api/health").retrieve().toBodilessEntity();
            return true;
        } catch (Exception e) {
            return false;
        }
    }
}
