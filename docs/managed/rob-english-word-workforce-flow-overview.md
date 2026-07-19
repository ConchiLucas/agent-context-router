# rob-english-word-workforce 跨服务流转

## 用户侧主链路

```text
Vue / React 用户端
  -> Java backend
  -> PostgreSQL / Redis
```

## Dashboard 与 AI 链路

```text
React dashboard
  -> Go server
  -> Python word-agent
  -> 模型 / TTS 服务
  -> Go server 回调与持久化
```

## 排查顺序

1. 先确认问题属于用户端主链路还是 Dashboard/AI 链路。
2. 读取对应子项目 overview 确认职责和入口。
3. 检查实时 API、日志、配置和数据库。
4. 数据库连接信息读取 `rob-english-word-workforce-database-info`。
5. 子项目完整清单读取 `rob-english-word-workforce-subprojects-overview`。
