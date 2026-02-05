#!/usr/bin/env -S uvx
# /// script
# requires-python = ">=3.10"
# dependencies = ["pymodbus>=3.6,<3.7", "pyserial>=3.5", "click>=8.0"]
# ///
"""
End-to-end checks for the Go server with pymodbus clients over TCP, RTU and ASCII.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import click
from pymodbus import Framer
from pymodbus.client import ModbusSerialClient, ModbusTcpClient

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "modbus_server_harness.go"
HARNESS_BIN = ROOT / "bin" / "modbus-server-harness"


def _require_cmd(cmd: str) -> None:
    if subprocess.call(["which", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        raise SystemExit(f"Missing required command: {cmd}")


def kill_process(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except Exception:
            proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                proc.kill()


def wait_for_proc_ready(check, proc: subprocess.Popen, timeout: float, label: str) -> None:
    deadline = time.time() + timeout
    last_err: Exception | None = None

    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"{label} exited with code {proc.returncode}")
        try:
            if check():
                return
        except Exception as exc:  # pylint: disable=broad-except
            last_err = exc
        time.sleep(0.1)

    if last_err is not None:
        raise RuntimeError(f"{label} did not become ready in time: {last_err}") from last_err
    raise RuntimeError(f"{label} did not become ready in time")


def start_server_tcp(addr: str) -> subprocess.Popen:
    print(f"[server] starting TCP harness on {addr}")
    return subprocess.Popen(
        [str(HARNESS_BIN), "--mode", "tcp", "--listen", addr, "--unit-id", "1"],
        cwd=ROOT,
        start_new_session=True,
    )


def start_server_serial(mode: str, device: str) -> subprocess.Popen:
    print(f"[server] starting serial harness on {device} framing={mode}")
    return subprocess.Popen(
        [
            str(HARNESS_BIN),
            "--mode",
            mode,
            "--serial",
            device,
            "--unit-id",
            "1",
        ],
        cwd=ROOT,
        start_new_session=True,
    )


def build_harness() -> None:
    print(f"[build] building modbus-server-harness at {HARNESS_BIN}")
    HARNESS_BIN.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        ["go", "build", "-o", str(HARNESS_BIN), str(HARNESS)],
        cwd=ROOT,
    )


def start_socat_pair() -> tuple[subprocess.Popen, str, str]:
    _require_cmd("socat")
    print("[socat] creating connected pty pair")
    proc = subprocess.Popen(
        ["socat", "-d", "-d", "pty,raw,echo=0", "pty,raw,echo=0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    devs: list[str] = []
    while len(devs) < 2:
        line = proc.stderr.readline()
        if not line:
            break
        if "PTY is" in line:
            devs.append(line.strip().split()[-1])
    if len(devs) != 2:
        kill_process(proc)
        raise RuntimeError("failed to parse socat PTY paths")
    print(f"[socat] pty pair: {devs[0]} <-> {devs[1]}")
    return proc, devs[0], devs[1]


def expect_ok(res, message: str) -> None:
    if res.isError():
        raise AssertionError(f"{message}: {res}")


def expect_exception_code(res, expected: int, message: str) -> None:
    if not res.isError():
        raise AssertionError(f"{message}: expected exception {expected}, got success")
    got = getattr(res, "exception_code", None)
    if got != expected:
        raise AssertionError(f"{message}: expected exception {expected}, got {got}")


HOLDING_BASE = (0x1111, 0x2222, 0x1234, 0xABCD, 0x0000, 0x7FFF, 0x8000)
HOLDING_EXTRA = tuple(0x1000 + i for i in range(130))
HOLDING_DATA = HOLDING_BASE + HOLDING_EXTRA
INPUT_DATA = (0x9999, 0xAAAA, 0xBBBB, 0xCCCC)
COILS_DATA = (True, False, True, True, False, False, True, False)
DISCRETE_DATA = (False, True, True, False, True, False, False, True)


def _expected_registers(data: tuple[int, ...], start: int, extra: int) -> list[int]:
    count = extra + 1
    return [data[start + idx] for idx in range(count)]


def _expected_bools(data: tuple[bool, ...], start: int, extra: int) -> list[bool]:
    count = extra + 1
    return [data[start + idx] for idx in range(count)]


def run_read_suite(client, mode: str) -> None:
    if not client.connect():
        raise RuntimeError(f"failed to connect pymodbus client for {mode}")
    try:
        print(f"[client] running read/write suite ({mode})")
        rr = client.read_holding_registers(0, 1, slave=1)
        expect_ok(rr, f"{mode}: read holding")
        if rr.registers != _expected_registers(HOLDING_DATA, 0, 0):
            raise AssertionError(f"{mode}: unexpected holding values {rr.registers}")

        rr = client.read_holding_registers(0, 4, slave=1)
        expect_ok(rr, f"{mode}: read holding 0+3")
        if rr.registers != _expected_registers(HOLDING_DATA, 0, 3):
            raise AssertionError(f"{mode}: unexpected holding values {rr.registers}")

        rr = client.read_holding_registers(2, 3, slave=1)
        expect_ok(rr, f"{mode}: read holding 2+2")
        if rr.registers != _expected_registers(HOLDING_DATA, 2, 2):
            raise AssertionError(f"{mode}: unexpected holding values {rr.registers}")

        rr = client.read_holding_registers(0, 125, slave=1)
        expect_ok(rr, f"{mode}: read holding 0+124")
        if rr.registers != _expected_registers(HOLDING_DATA, 0, 124):
            raise AssertionError(f"{mode}: unexpected holding values {rr.registers}")

        rr = client.read_input_registers(0, 1, slave=1)
        expect_ok(rr, f"{mode}: read input")
        if rr.registers != _expected_registers(INPUT_DATA, 0, 0):
            raise AssertionError(f"{mode}: unexpected input values {rr.registers}")

        rr = client.read_input_registers(0, 4, slave=1)
        expect_ok(rr, f"{mode}: read input 0+3")
        if rr.registers != _expected_registers(INPUT_DATA, 0, 3):
            raise AssertionError(f"{mode}: unexpected input values {rr.registers}")

        wr = client.write_register(1, 0x3333, slave=1)
        expect_ok(wr, f"{mode}: write register")
        rr = client.read_holding_registers(1, 1, slave=1)
        expect_ok(rr, f"{mode}: read holding after write")
        if rr.registers != [0x3333]:
            raise AssertionError(f"{mode}: unexpected holding[1] {rr.registers}")

        rc = client.read_coils(0, 4, slave=1)
        expect_ok(rc, f"{mode}: read coils")
        if list(rc.bits[:4]) != _expected_bools(COILS_DATA, 0, 3):
            raise AssertionError(f"{mode}: unexpected coils {rc.bits[:4]}")

        wc = client.write_coil(1, True, slave=1)
        expect_ok(wc, f"{mode}: write coil")
        rc = client.read_coils(0, 2, slave=1)
        expect_ok(rc, f"{mode}: read coils after write")
        if list(rc.bits[:2]) != [True, True]:
            raise AssertionError(f"{mode}: unexpected coils after write {rc.bits[:2]}")

        rc = client.read_discrete_inputs(0, 8, slave=1)
        expect_ok(rc, f"{mode}: read discrete inputs 0+7")
        if list(rc.bits[:8]) != _expected_bools(DISCRETE_DATA, 0, 7):
            raise AssertionError(f"{mode}: unexpected discrete inputs {rc.bits[:8]}")

        bad_addr = client.read_holding_registers(200, 1, slave=1)
        expect_exception_code(bad_addr, 2, f"{mode}: expected illegal data address")

        bad_unit = client.read_holding_registers(0, 1, slave=2)
        expect_exception_code(bad_unit, 1, f"{mode}: expected illegal function")
    finally:
        client.close()


def wait_for_tcp_server(proc: subprocess.Popen, host: str, port: int, timeout: float = 6.0) -> None:
    def _check() -> bool:
        client = ModbusTcpClient(host, port=port, timeout=0.2)
        ok = client.connect()
        client.close()
        return ok

    wait_for_proc_ready(_check, proc, timeout, "TCP server")


def wait_for_serial_server(mode: str, port: str, proc: subprocess.Popen, timeout: float = 8.0) -> None:
    framing = Framer.ASCII if mode == "ascii" else Framer.RTU

    def _check() -> bool:
        client = ModbusSerialClient(
            port=port,
            framer=framing,
            baudrate=19200,
            bytesize=8,
            parity="N",
            stopbits=2,
            timeout=0.3,
        )
        try:
            if not client.connect():
                return False
            # A successful request confirms both PTY wiring and server readiness.
            rr = client.read_holding_registers(0, 1, slave=1)
            return not rr.isError() and rr.registers == [0x1111]
        finally:
            client.close()

    wait_for_proc_ready(_check, proc, timeout, f"{mode.upper()} server")


def test_tcp() -> None:
    proc = start_server_tcp("127.0.0.1:1503")
    try:
        wait_for_tcp_server(proc, "127.0.0.1", 1503)
        run_read_suite(ModbusTcpClient("127.0.0.1", port=1503, timeout=1), "tcp")
    finally:
        kill_process(proc)


def test_serial(mode: str) -> None:
    socat_proc, dev_server, dev_client = start_socat_pair()
    proc = start_server_serial(mode, dev_server)
    try:
        wait_for_serial_server(mode, dev_client, proc)
        framing = Framer.ASCII if mode == "ascii" else Framer.RTU
        client = ModbusSerialClient(
            port=dev_client,
            framer=framing,
            baudrate=19200,
            bytesize=8,
            parity="N",
            stopbits=2,
            timeout=1,
        )
        run_read_suite(client, mode)
    finally:
        kill_process(proc)
        kill_process(socat_proc)


@click.command()
@click.option(
    "--mode",
    "modes",
    multiple=True,
    type=click.Choice(["tcp", "ascii", "rtu", "serial"], case_sensitive=False),
    help="Modes to run (serial expands to ascii+rtu). Default: all.",
)
def main(modes: tuple[str, ...]) -> int:
    selected = {m.lower() for m in modes}
    if not selected:
        selected = {"tcp", "ascii", "rtu"}
    if "serial" in selected:
        selected.discard("serial")
        selected.update({"ascii", "rtu"})

    _require_cmd("go")
    _require_cmd("uv")
    build_harness()

    try:
        if "tcp" in selected:
            test_tcp()
        if "ascii" in selected:
            test_serial("ascii")
        if "rtu" in selected:
            test_serial("rtu")
    except Exception as exc:  # pylint: disable=broad-except
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    print("All modbus server e2e checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
