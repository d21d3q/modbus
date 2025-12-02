#!/usr/bin/env -S uvx
# /// script
# requires-python = ">=3.10"
# dependencies = ["pymodbus>=3.6,<3.7", "pyserial>=3.5", "click>=8.0"]
# ///
"""
Tiny Modbus server for local testing of modbus-cli against TCP or serial
(ASCII or RTU) without real hardware. Known register/coils values:

Unit ID: configurable via --unit-id (default 1)
- Coils (co):            [1,0,1,1,0,0,1,0] starting at address 0
- Discrete inputs (di):  [0,1,1,0,1,0,0,1] starting at address 0
- Holding registers (hr): 0x1111, 0x2222, 0x1234, 0xabcd, 0x0000, 0x7fff, 0x8000
- Input registers (ir):    0x9999, 0xaaaa, 0xbbbb, 0xcccc
"""

import logging
from typing import Tuple

import click
from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.server import StartSerialServer, StartTcpServer
from pymodbus.transaction import ModbusAsciiFramer, ModbusRtuFramer, ModbusSocketFramer


def build_context(unit_id: int) -> ModbusServerContext:
    coils = ModbusSequentialDataBlock(0, [1, 0, 1, 1, 0, 0, 1, 0])
    discretes = ModbusSequentialDataBlock(0, [0, 1, 1, 0, 1, 0, 0, 1])
    base_holding = [0x1111, 0x2222, 0x1234, 0xABCD, 0x0000, 0x7FFF, 0x8000]
    # add enough values to allow maximum-length register reads
    extra_holding = [0x1000 + i for i in range(130)]
    holding = ModbusSequentialDataBlock(0, base_holding + extra_holding)
    inputs = ModbusSequentialDataBlock(0, [0x9999, 0xAAAA, 0xBBBB, 0xCCCC])

    store = {
        unit_id: ModbusSlaveContext(
            di=discretes,
            co=coils,
            hr=holding,
            ir=inputs,
            zero_mode=True,
        )
    }
    return ModbusServerContext(slaves=store, single=False)


@click.command()
@click.option(
    "--mode",
    type=click.Choice(["tcp", "serial"], case_sensitive=False),
    default="tcp",
    show_default=True,
    help="Run as TCP server or serial (ASCII/RTU).",
)
@click.option(
    "--framing",
    type=click.Choice(["ascii", "rtu"], case_sensitive=False),
    default="ascii",
    show_default=True,
    help="Serial framing (serial mode only).",
)
@click.option(
    "--listen",
    default="127.0.0.1:1502",
    show_default=True,
    help="TCP listen address host:port (tcp mode).",
)
@click.option(
    "--serial",
    "serial_dev",
    default="/dev/ttyUSB0",
    show_default=True,
    help="Serial device path (serial mode).",
)
@click.option("--unit-id", type=int, default=1, show_default=True, help="Unit/slave ID to serve.")
@click.option("--speed", type=int, default=19200, show_default=True, help="Serial baud rate.")
@click.option("--data-bits", type=int, default=8, show_default=True, help="Serial data bits.")
@click.option(
    "--parity",
    type=click.Choice(["N", "E", "O"], case_sensitive=False),
    default="N",
    show_default=True,
    help="Serial parity (N/E/O).",
)
@click.option("--stop-bits", type=int, default=2, show_default=True, help="Serial stop bits.")
@click.option("--timeout", type=float, default=1.0, show_default=True, help="Serial timeout (s).")
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default="INFO",
    show_default=True,
    help="Log verbosity.",
)
def main(
    mode: str,
    framing: str,
    listen: str,
    serial_dev: str,
    unit_id: int,
    speed: int,
    data_bits: int,
    parity: str,
    stop_bits: int,
    timeout: float,
    log_level: str,
    ) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    context = build_context(unit_id)

    if mode.lower() == "tcp":
        host, port = parse_host_port(listen)
        logging.info("Starting TCP server on %s:%s", host, port)
        StartTcpServer(
            context=context,
            address=(host, port),
            framer=ModbusSocketFramer,
        )
        return

    framer = ModbusAsciiFramer if framing.lower() == "ascii" else ModbusRtuFramer

    logging.info(
        "Starting serial server on %s (%s framing) baud=%s parity=%s stopbits=%s",
        serial_dev,
        framing,
        speed,
        parity,
        stop_bits,
    )
    StartSerialServer(
        context=context,
        framer=framer,
        port=serial_dev,
        timeout=timeout,
        baudrate=speed,
        bytesize=data_bits,
        parity=parity,
        stopbits=stop_bits,
    )


def parse_host_port(addr: str) -> Tuple[str, int]:
    if ":" not in addr:
        raise SystemExit("listen address must be host:port")
    host, port_str = addr.rsplit(":", 1)
    return host, int(port_str)


if __name__ == "__main__":
    # Click handles argv parsing.
    main()
