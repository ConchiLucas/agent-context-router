# 数据库连接信息: rob-english-word-workforce

本文件是数据库排查入口，只记录连接信息和排查起点。表结构、模型和临时数据请按需直接读取项目目录。

## 主要数据库

| 用途 | 数据库 | 本地连接 | 账号 |
| --- | --- | --- | --- |
| 英语抢词 Java 后端 | `rob_english_word` | `127.0.0.1:5432` | 代码默认 `rob_word`，当前本地常用 `conchi / conchi123456` |
| 管理后台 Go 服务 | `select_english_word` | `127.0.0.1:5432` | 本地配置 `conchi / conchi123456` |
| 缓存/房间状态 | Redis | `127.0.0.1:6379` | 默认无密码 |

## Docker 内连接

- 根目录 `docker-compose.yml` 中，`rob_english_word_back` 通过 `jdbc:postgresql://db:5432/rob_english_word` 连接 compose 内的 Postgres。
- `rob_english_word_back/docker-compose.yml` 中，后端容器通过 `host.docker.internal:5432/rob_english_word` 连接宿主机 Postgres。
- `word_select_dashboard/server/config.docker.yaml` 中，管理后台默认通过 `host.docker.internal:5432` 连接宿主机 Postgres。

## 快速只读检查

本地 shell 可能没有 `psql`，可以优先使用 `word_select_dashboard/word-agent` 的 Python 环境：

```bash
cd /Users/conchi/workforce/rob_english_word_workforce
word_select_dashboard/word-agent/.venv/bin/python -c "import psycopg; conn=psycopg.connect('host=127.0.0.1 port=5432 dbname=rob_english_word user=conchi password=conchi123456'); print(conn.execute('select 1').fetchone()); conn.close()"
```

如果沙箱阻止访问 `127.0.0.1:5432`，用同一条只读命令申请外部权限后重试。

## 排查起点

- `rob_english_word_back` 表结构：`/Users/conchi/workforce/rob_english_word_workforce/rob_english_word_back/db`
- Java 后端数据库配置：`/Users/conchi/workforce/rob_english_word_workforce/rob_english_word_back/src/main/resources/application.yml`
- 管理后台数据库配置：`/Users/conchi/workforce/rob_english_word_workforce/word_select_dashboard/server/config.yaml`
- 管理后台 GORM 模型：`/Users/conchi/workforce/rob_english_word_workforce/word_select_dashboard/server/model`
- word-agent 生成数据逻辑：`/Users/conchi/workforce/rob_english_word_workforce/word_select_dashboard/word-agent/src/word_agent/services`
