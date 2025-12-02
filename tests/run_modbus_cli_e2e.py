#!/usr/bin/env -S uvx
# /// script
# requires-python = ">=3.10"
# dependencies = ["pymodbus>=3.6,<3.7", "pyserial>=3.5", "click>=8.0"]
# ///
"""
End-to-end checks for modbus-cli against the mock server over TCP and virtual
serial (ASCII and RTU) without hardware. Spawns the existing mock server
tests/modbus_mock_server.py as a subprocess and exercises modbus-cli with
known register values.

Usage:
    uvx --with pymodbus --with pyserial python tests/run_modbus_cli_e2e.py
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parents[1]
CLI = Path(os.environ.get("CLI", ROOT / "bin" / "modbus-cli"))
SERVER_SCRIPT = ROOT / "tests" / "modbus_mock_server.py"


def _require_cmd(cmd: str) -> None:
    if subprocess.call(["which", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        raise SystemExit(f"Missing required command: {cmd}")


def _parse_register_line(line: str) -> tuple[int, int]:
    # expected format: 0x0000  0     : 0x1111  4369
    parts = line.replace(":", " ").split()
    if len(parts) < 4:
        raise ValueError(f"cannot parse register line: {line}")
    addr_hex = parts[0]
    value_hex = parts[2]
    return int(addr_hex, 16), int(value_hex, 16)


def _parse_registers(lines: list[str]) -> list[tuple[int, int]]:
    return [_parse_register_line(ln) for ln in lines]


def _parse_bool_line(line: str) -> tuple[int, bool]:
    # expected format: 0x0000  0     : true
    parts = line.replace(":", " ").split()
    if len(parts) < 3:
        raise ValueError(f"cannot parse bool line: {line}")
    addr_hex = parts[0]
    value_str = parts[2].lower()
    if value_str not in {"true", "false"}:
        raise ValueError(f"unexpected bool value in line: {line}")
    return int(addr_hex, 16), value_str == "true"


def _parse_bools(lines: list[str]) -> list[tuple[int, bool]]:
    return [_parse_bool_line(ln) for ln in lines]


def build_cli() -> None:
    if CLI.exists():
        return
    print(f"[build] building modbus-cli at {CLI}")
    subprocess.check_call(
        ["go", "build", "-o", str(CLI), str(ROOT / "cmd/modbus-cli.go")],
        cwd=ROOT,
    )


def start_server_tcp(addr: str) -> subprocess.Popen:
    print(f"[server] starting TCP mock on {addr}")
    return subprocess.Popen(
        [
            sys.executable,
            str(SERVER_SCRIPT),
            "--mode",
            "tcp",
            "--listen",
            addr,
            "--unit-id",
            "1",
            "--log-level",
            "ERROR",
        ],
    )


def start_server_serial(device: str, framing: str) -> subprocess.Popen:
    print(f"[server] starting serial mock on {device} framing={framing}")
    return subprocess.Popen(
        [
            sys.executable,
            str(SERVER_SCRIPT),
            "--mode",
            "serial",
            "--framing",
            framing,
            "--serial",
            device,
            "--unit-id",
            "1",
            "--log-level",
            "ERROR",
        ],
    )


def start_socat_pair() -> tuple[subprocess.Popen, str, str]:
    _require_cmd("socat")
    print("[socat] creating connected pty pair")
    proc = subprocess.Popen(
        ["socat", "-d", "-d", "pty,raw,echo=0", "pty,raw,echo=0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    devs: list[str] = []
    while len(devs) < 2:
        line = proc.stderr.readline()
        if not line:
            break
        if "PTY is" in line:
            devs.append(line.strip().split()[-1])
    if len(devs) != 2:
        proc.kill()
        raise RuntimeError("failed to obtain pty paths from socat")
    print(f"[socat] pty pair: {devs[0]} <-> {devs[1]}")
    return proc, devs[0], devs[1]


def run_cli_and_check(
    target: str,
    command: str,
    expected_lines: tuple[str, ...] = (),
    expected_len: int | None = None,
    expected_first: tuple[int, int] | None = None,
    expected_last: tuple[int, int] | None = None,
    expected_regs: tuple[tuple[int, int], ...] = (),
    expected_bools: tuple[tuple[int, bool], ...] = (),
) -> None:
    print(f"[cli] running modbus-cli --target={target} {command}")
    out = subprocess.check_output(
        [str(CLI), "--target", target, command],
        text=True,
        cwd=ROOT,
    )
    lines = [ln.rstrip() for ln in out.strip().splitlines() if ln.strip()]
    print(f"[cli] output for {target}:\n" + "\n".join(lines) + "\n")

    if expected_lines:
        if lines != list(expected_lines):
            raise AssertionError(
                "Output mismatch for {} {}\nexpected:\n{}\nactual:\n{}".format(
                    target,
                    command,
                    "\n".join(expected_lines),
                    "\n".join(lines),
                )
            )

    if expected_len is not None and len(lines) != expected_len:
        raise AssertionError(
            f"Expected {expected_len} lines for {target} {command}, got {len(lines)}"
        )

    if expected_bools:
        bools = _parse_bools(lines)
        if bools != list(expected_bools):
            raise AssertionError(
                f"Bool content mismatch for {target} {command}\nexpected: {expected_bools}\nactual: {bools}"
            )
        return

    regs = _parse_registers(lines)

    if expected_regs:
        if regs != list(expected_regs):
            raise AssertionError(
                f"Register content mismatch for {target} {command}\nexpected: {expected_regs}\nactual: {regs}"
            )

    if expected_first is not None:
        if not regs or regs[0] != expected_first:
            raise AssertionError(
                f"First register mismatch for {target} {command}: expected {expected_first}, got {regs[0] if regs else '<none>'}"
            )

    if expected_last is not None:
        if not regs or regs[-1] != expected_last:
            raise AssertionError(
                f"Last register mismatch for {target} {command}: expected {expected_last}, got {regs[-1] if regs else '<none>'}"
            )


def kill_process(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


HOLDING_BASE = (0x1111, 0x2222, 0x1234, 0xABCD, 0x0000, 0x7FFF, 0x8000)
HOLDING_EXTRA = tuple(0x1000 + i for i in range(130))
HOLDING_DATA = HOLDING_BASE + HOLDING_EXTRA
INPUT_DATA = (0x9999, 0xAAAA, 0xBBBB, 0xCCCC)
COILS_DATA = (True, False, True, True, False, False, True, False)
DISCRETE_DATA = (False, True, True, False, True, False, False, True)


def _expected_registers(data: tuple[int, ...], start: int, extra: int) -> tuple[tuple[int, int], ...]:
    count = extra + 1
    return tuple((start + idx, data[start + idx]) for idx in range(count))


def _expected_bools(data: tuple[bool, ...], start: int, extra: int) -> tuple[tuple[int, bool], ...]:
    count = extra + 1
    return tuple((start + idx, data[start + idx]) for idx in range(count))


def run_read_suite(target: str) -> None:
    run_cli_and_check(
        target,
        "rh:uint16:0",
        expected_regs=_expected_registers(HOLDING_DATA, 0, 0),
        expected_len=1,
    )
    run_cli_and_check(
        target,
        "rh:uint16:0+3",
        expected_regs=_expected_registers(HOLDING_DATA, 0, 3),
        expected_len=4,
    )
    run_cli_and_check(
        target,
        "rh:uint16:2+2",
        expected_regs=_expected_registers(HOLDING_DATA, 2, 2),
        expected_len=3,
    )
    run_cli_and_check(
        target,
        "rh:uint16:0+124",
        expected_regs=_expected_registers(HOLDING_DATA, 0, 124),
        expected_len=125,
    )
    run_cli_and_check(
        target,
        "ri:uint16:0",
        expected_regs=_expected_registers(INPUT_DATA, 0, 0),
        expected_len=1,
    )
    run_cli_and_check(
        target,
        "ri:uint16:0+3",
        expected_regs=_expected_registers(INPUT_DATA, 0, 3),
        expected_len=4,
    )
    run_cli_and_check(
        target,
        "rc:0",
        expected_bools=_expected_bools(COILS_DATA, 0, 0),
        expected_len=1,
    )
    run_cli_and_check(
        target,
        "rc:0+7",
        expected_bools=_expected_bools(COILS_DATA, 0, 7),
        expected_len=8,
    )
    run_cli_and_check(
        target,
        "rdi:0",
        expected_bools=_expected_bools(DISCRETE_DATA, 0, 0),
        expected_len=1,
    )
    run_cli_and_check(
        target,
        "rdi:0+7",
        expected_bools=_expected_bools(DISCRETE_DATA, 0, 7),
        expected_len=8,
    )


def test_tcp() -> None:
    proc = start_server_tcp("127.0.0.1:1502")
    try:
        time.sleep(0.5)
        run_read_suite("tcp://127.0.0.1:1502")
    finally:
        kill_process(proc)


def test_serial(framing: str, scheme: str) -> None:
    socat_proc, dev_server, dev_client = start_socat_pair()
    proc = start_server_serial(dev_server, framing)
    try:
        time.sleep(1.0)
        run_read_suite(f"{scheme}://{dev_client}")
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

    _require_cmd("uv")
    if not CLI.exists():
        build_cli()

    try:
        if "tcp" in selected:
            test_tcp()
        if "ascii" in selected:
            test_serial("ascii", "ascii")
        if "rtu" in selected:
            test_serial("rtu", "rtu")
    except Exception as exc:  # pylint: disable=broad-except
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    print("All modbus-cli e2e checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
