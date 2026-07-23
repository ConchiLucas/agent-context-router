from dataclasses import dataclass
from typing import Any

import clickhouse_connect
import psycopg
import pymysql

from context_router.repositories.data_source_repository import (
    DataSourceRecord,
    DataSourceRepositoryError,
)

_MYSQL_SYSTEM_DATABASES = {
    "information_schema",
    "mysql",
    "performance_schema",
    "sys",
}
_CLICKHOUSE_SYSTEM_DATABASES = {
    "information_schema",
    "system",
}


@dataclass(frozen=True, slots=True)
class DiscoveredDatabase:
    name: str
    system_database: bool


def discover_databases(source: DataSourceRecord) -> list[DiscoveredDatabase]:
    if source.engine in {"mysql", "mariadb"}:
        return _discover_mysql_databases(source.connection_config)
    if source.engine == "postgresql":
        return _discover_postgresql_databases(source.connection_config)
    if source.engine == "clickhouse":
        return _discover_clickhouse_databases(source.connection_config)
    raise DataSourceRepositoryError(f"{source.engine} 暂不支持自动同步数据库，请继续手工维护")


def _discover_mysql_databases(config: dict[str, Any]) -> list[DiscoveredDatabase]:
    host = str(config.get("host") or "").strip()
    username = str(config.get("username") or config.get("user") or "").strip()
    password = str(config.get("password") or config.get("passwd") or "")
    if not host:
        raise DataSourceRepositoryError("数据源未配置主机地址")
    if not username:
        raise DataSourceRepositoryError("数据源未配置用户名")
    try:
        port = int(config.get("port") or 3306)
    except (TypeError, ValueError) as exc:
        raise DataSourceRepositoryError("数据源端口配置无效") from exc

    try:
        connection = pymysql.connect(
            host=host,
            port=port,
            user=username,
            password=password,
            connect_timeout=8,
            read_timeout=15,
            write_timeout=15,
            charset="utf8mb4",
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute("SHOW DATABASES")
                names = [str(row[0]) for row in cursor.fetchall()]
        finally:
            connection.close()
    except pymysql.MySQLError as exc:
        raise DataSourceRepositoryError("MySQL 数据库清单读取失败") from exc

    return [
        DiscoveredDatabase(
            name=name,
            system_database=name.lower() in _MYSQL_SYSTEM_DATABASES,
        )
        for name in sorted(set(names), key=str.casefold)
    ]


def _discover_postgresql_databases(config: dict[str, Any]) -> list[DiscoveredDatabase]:
    host = str(config.get("host") or "").strip()
    username = str(config.get("username") or config.get("user") or "").strip()
    password = str(config.get("password") or config.get("passwd") or "")
    database = str(config.get("database") or config.get("dbname") or "postgres").strip()
    if not host:
        raise DataSourceRepositoryError("数据源未配置主机地址")
    if not username:
        raise DataSourceRepositoryError("数据源未配置用户名")
    try:
        port = int(config.get("port") or 5432)
    except (TypeError, ValueError) as exc:
        raise DataSourceRepositoryError("数据源端口配置无效") from exc

    try:
        connection = psycopg.connect(
            host=host,
            port=port,
            user=username,
            password=password,
            dbname=database,
            connect_timeout=8,
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT datname FROM pg_database
                    WHERE datallowconn AND NOT datistemplate
                    ORDER BY datname"""
                )
                names = [str(row[0]) for row in cursor.fetchall()]
        finally:
            connection.close()
    except psycopg.Error as exc:
        raise DataSourceRepositoryError("PostgreSQL 数据库清单读取失败") from exc

    return [
        DiscoveredDatabase(name=name, system_database=name == "postgres")
        for name in sorted(set(names), key=str.casefold)
    ]


def _discover_clickhouse_databases(config: dict[str, Any]) -> list[DiscoveredDatabase]:
    host = str(config.get("host") or "").strip()
    username = str(config.get("username") or config.get("user") or "default").strip()
    password = str(config.get("password") or config.get("passwd") or "")
    secure = _config_bool(config.get("secure"), default=False)
    verify = _config_bool(config.get("verify"), default=True)
    database = str(config.get("bootstrap_database") or "default").strip()
    if not host:
        raise DataSourceRepositoryError("数据源未配置主机地址")
    if not username:
        raise DataSourceRepositoryError("数据源未配置用户名")
    try:
        port = int(config.get("port") or (8443 if secure else 8123))
        connect_timeout = float(config.get("connect_timeout_seconds") or 8)
        send_receive_timeout = float(config.get("send_receive_timeout_seconds") or 15)
    except (TypeError, ValueError) as exc:
        raise DataSourceRepositoryError("ClickHouse 连接配置无效") from exc
    if not 1 <= port <= 65535 or connect_timeout <= 0 or send_receive_timeout <= 0:
        raise DataSourceRepositoryError("ClickHouse 连接配置无效")

    client = None
    try:
        client = clickhouse_connect.get_client(
            host=host,
            port=port,
            username=username,
            password=password,
            database=database,
            secure=secure,
            verify=verify,
            connect_timeout=connect_timeout,
            send_receive_timeout=send_receive_timeout,
        )
        result = client.query("SELECT name FROM system.databases ORDER BY name")
        names = [str(row[0]) for row in result.result_rows]
    except Exception as exc:
        # Driver errors can embed URLs and connection parameters. Keep the public
        # error stable and preserve the original exception only as the cause.
        raise DataSourceRepositoryError("ClickHouse 数据库清单读取失败") from exc
    finally:
        if client is not None:
            client.close()

    return [
        DiscoveredDatabase(
            name=name,
            system_database=name.casefold() in _CLICKHOUSE_SYSTEM_DATABASES,
        )
        for name in sorted(set(names), key=str.casefold)
    ]


def _config_bool(value: Any, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise DataSourceRepositoryError("ClickHouse 布尔配置无效")
