-- 统一事件表 + 同步日志表
-- 同时兼容 MySQL 8 与 H2(MODE=MySQL)：不用 MySQL 专有的 ENGINE/COMMENT/KEY 语法，
-- 全部 IF NOT EXISTS，可重复执行。数据量小，暂不建二级索引（后续优化再加）。

CREATE TABLE IF NOT EXISTS info_item (
    id            BIGINT       NOT NULL AUTO_INCREMENT,
    source        VARCHAR(32)  NOT NULL,   -- 来源：chaoxing / zhidao / qq / wechat / yuketang
    item_type     VARCHAR(32)  NOT NULL,   -- 类型：homework / schedule / exam / notice
    source_id     VARCHAR(190) NOT NULL,   -- 来源内唯一键，用于幂等 upsert
    title         VARCHAR(500) NOT NULL,
    course        VARCHAR(200),
    teacher       VARCHAR(100),
    location      VARCHAR(200),
    deadline      DATETIME,                -- 截止时间（作业/考试）
    start_time    DATETIME,                -- 开始（上课/考试/作答开始/通知发布时间）
    end_time      DATETIME,                -- 结束（下课/考试结束）
    status        VARCHAR(64),
    url           VARCHAR(1000),
    raw_json      TEXT,                    -- 采集器保留的原始字段（JSON 文本）
    mock          TINYINT      NOT NULL DEFAULT 0,  -- 1=假数据行：切到真实账号时会被清掉
    account       VARCHAR(64)  NOT NULL DEFAULT '', -- 属于哪个学习通账号（uid）：换号时清掉别的账号的行
    first_seen_at DATETIME     NOT NULL,   -- 首次采集到的时间
    updated_at    DATETIME     NOT NULL,   -- 最近一次采集到的时间
    PRIMARY KEY (id),
    CONSTRAINT uk_info_item_source UNIQUE (source, item_type, source_id)
);

CREATE TABLE IF NOT EXISTS sync_log (
    id             BIGINT       NOT NULL AUTO_INCREMENT,
    source         VARCHAR(32)  NOT NULL,
    status         VARCHAR(16)  NOT NULL,  -- RUNNING / SUCCESS / FAILED
    started_at     DATETIME     NOT NULL,
    finished_at    DATETIME,
    synced_at      DATETIME,               -- 采集器生成数据的时间
    homework_count INT          NOT NULL DEFAULT 0,
    schedule_count INT          NOT NULL DEFAULT 0,
    exam_count     INT          NOT NULL DEFAULT 0,
    notice_count   INT          NOT NULL DEFAULT 0,
    mock           TINYINT      NOT NULL DEFAULT 0,
    account_name   VARCHAR(100),           -- 这轮采集用的学习通账号（防止多账号混淆）
    account_school VARCHAR(200),
    message        VARCHAR(1000),
    PRIMARY KEY (id)
);
