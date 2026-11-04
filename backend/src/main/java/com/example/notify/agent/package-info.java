/**
 * 预留：agent 层。
 *
 * <p>后续在这里接 Spring AI 2.0.2：把 info_item 表里的作业/考试/通知拼成 prompt，
 * 交给模型做"今天该干什么"的汇总与提醒文案，再把结果回给前端。
 *
 * <p>本次 demo 刻意不实现——先把"数据搬进来"跑通，agent 属于下一阶段。
 * 开工时在 {@code pom.xml} 加 Spring AI 2.0.2 的 BOM 与对应 starter，
 * 再在此包写一个 Service 即可。
 */
package com.example.notify.agent;
