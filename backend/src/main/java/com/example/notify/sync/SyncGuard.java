package com.example.notify.sync;

import com.example.notify.config.DemoProperties;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

/**
 * 同步互斥锁：同一时刻只允许一轮同步。
 *
 * <p>{@code demo.redis-enabled=true} 时用 Redis {@code SET NX}（多实例部署才有意义）；
 * 默认关闭，用进程内 {@link AtomicBoolean} 兜住——demo 只跑一个后端实例。
 * Redis 不可用时自动降级，不会让同步直接失败。
 */
@Component
public class SyncGuard {

    private static final Logger log = LoggerFactory.getLogger(SyncGuard.class);
    private static final String LOCK_KEY = "notify:sync:lock";
    private static final Duration LOCK_TTL = Duration.ofMinutes(15);

    private final AtomicBoolean localBusy = new AtomicBoolean(false);
    private final StringRedisTemplate redis;

    public SyncGuard(ObjectProvider<StringRedisTemplate> redisProvider, DemoProperties props) {
        StringRedisTemplate template = null;
        if (props.redisEnabled()) {
            template = redisProvider.getIfAvailable();
            if (template == null) {
                log.warn("demo.redis-enabled=true 但容器里没有 Redis 客户端，降级为进程内锁");
            }
        }
        this.redis = template;
    }

    /** 抢锁；返回 false 说明已经有同步在跑。 */
    public boolean tryAcquire() {
        if (!localBusy.compareAndSet(false, true)) {
            return false;
        }
        if (redis == null) {
            return true;
        }
        try {
            Boolean ok = redis.opsForValue().setIfAbsent(LOCK_KEY, "1", LOCK_TTL);
            if (!Boolean.TRUE.equals(ok)) {
                localBusy.set(false);
                return false;
            }
        } catch (Exception e) {
            log.warn("Redis 抢锁失败，本机继续执行：{}", e.getMessage());
        }
        return true;
    }

    public void release() {
        localBusy.set(false);
        if (redis == null) {
            return;
        }
        try {
            redis.delete(LOCK_KEY);
        } catch (Exception e) {
            log.warn("Redis 释放锁失败（TTL 会自动过期）：{}", e.getMessage());
        }
    }

    public boolean isBusy() {
        return localBusy.get();
    }
}
