from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True, slots=True)
class DiscoveredDatabase:
    name: str
    system_database: bool


def discover_databases(source: DataSourceRecord) -> list[DiscoveredDatabase]:
    if source.engine in {"mysql", "mariadb"}:
        return _discover_mysql_databases(source.connection_config)
    if source.engine == "postgresql":
        return _discover_postgresql_databases(source.connection_config)
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
        message = str(exc).strip() or exc.__class__.__name__
        raise DataSourceRepositoryError(f"MySQL 数据库清单读取失败：{message}") from exc

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
        message = str(exc).strip() or exc.__class__.__name__
        raise DataSourceRepositoryError(f"PostgreSQL 数据库清单读取失败：{message}") from exc

    return [
        DiscoveredDatabase(name=name, system_database=name == "postgres")
        for name in sorted(set(names), key=str.casefold)
    ]
