#!/usr/bin/env python3
"""Relay localhost TCP ports to hosts reachable only from the macOS VPN."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
from dataclasses import dataclass
from functools import partial


@dataclass(frozen=True)
class Forward:
    listen_port: int
    target_host: str
    target_port: int


def parse_forward(value: str) -> Forward:
    parts = value.split(":")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("forward must use LISTEN_PORT:TARGET_HOST:TARGET_PORT")
    listen_port_text, target_host, target_port_text = parts
    if not target_host:
        raise argparse.ArgumentTypeError("target host must not be empty")
    try:
        listen_port = int(listen_port_text)
        target_port = int(target_port_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ports must be integers") from exc
    if not 1 <= listen_port <= 65535 or not 1 <= target_port <= 65535:
        raise argparse.ArgumentTypeError("ports must be between 1 and 65535")
    return Forward(
        listen_port=listen_port,
        target_host=target_host,
        target_port=target_port,
    )


async def copy_stream(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    while data := await reader.read(64 * 1024):
        writer.write(data)
        await writer.drain()


async def relay_connection(
    forward: Forward,
    connect_timeout: float,
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
) -> None:
    upstream_writer: asyncio.StreamWriter | None = None
    try:
        upstream_reader, upstream_writer = await asyncio.wait_for(
            asyncio.open_connection(forward.target_host, forward.target_port),
            timeout=connect_timeout,
        )
        tasks = {
            asyncio.create_task(copy_stream(client_reader, upstream_writer)),
            asyncio.create_task(copy_stream(upstream_reader, client_writer)),
        }
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    except OSError as exc:
        print(
            f"relay connection failed for localhost:{forward.listen_port} -> "
            f"{forward.target_host}:{forward.target_port}: {type(exc).__name__}",
            flush=True,
        )
    finally:
        for writer in (upstream_writer, client_writer):
            if writer is None:
                continue
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()


async def run(args: argparse.Namespace) -> None:
    servers: list[asyncio.AbstractServer] = []
    for forward in args.forward:
        server = await asyncio.start_server(
            partial(relay_connection, forward, args.connect_timeout),
            host=args.listen_host,
            port=forward.listen_port,
        )
        servers.append(server)
        print(
            f"listening on {args.listen_host}:{forward.listen_port} -> "
            f"{forward.target_host}:{forward.target_port}",
            flush=True,
        )

    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signum, stopped.set)

    await stopped.wait()
    for server in servers:
        server.close()
    await asyncio.gather(*(server.wait_closed() for server in servers))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Expose VPN-only TCP services on macOS localhost so Docker Desktop "
            "can reach them through host.docker.internal."
        )
    )
    parser.add_argument(
        "--listen-host",
        default="127.0.0.1",
        help="local bind address; keep the default to avoid LAN exposure",
    )
    parser.add_argument(
        "--forward",
        action="append",
        type=parse_forward,
        required=True,
        help="LISTEN_PORT:TARGET_HOST:TARGET_PORT; may be repeated",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=8.0,
        help="upstream connection timeout in seconds",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.connect_timeout <= 0:
        raise SystemExit("--connect-timeout must be positive")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
