"""Constant and mixed Table lanes; identity (full-width) slices.

The retired frontend's `vec()` admitted plain int lanes beside wires, and its
`trunc()` treated a width equal to the input as the identity. The current
language spells both directly:

* a tuple/list literal builds a Table from its expected type, so int lanes
  take the declared element type, narrower Bits lanes zero-extend, and
  out-of-range, miscounted or context-free literals reject;
* a full-width slice -- `x[:]`, `x[0:8]` or a bound equal to the width given
  by a source constant -- is the identity, including through a static width
  parameter at two different instance widths.

The values are checked natively (workers 1/2) and in physical RTL.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
for option in ("repo", "source-compiler", "linker", "emitter", "cxx", "scratch"):
    parser.add_argument("--" + option, required=True)
for tool in ("verilator",):
    parser.add_argument("--" + tool, default=shutil.which(tool))
args = parser.parse_args()
repo = Path(args.repo).resolve()
fixtures = Path(__file__).resolve().parent
scratch = Path(args.scratch).resolve()
work = scratch / "lane-literals"
shutil.rmtree(work, ignore_errors=True)
source = work / "source"
source.mkdir(parents=True)
env = dict(
    os.environ,
    PYTHONPATH=str(repo / "python"),
    PYTHONDONTWRITEBYTECODE="1",
    PYCIRCUIT_SOURCE_COMPILER=args.source_compiler,
    PYCIRCUIT_LINKER=args.linker,
    PYCIRCUIT_EMITTER=args.emitter,
)
commands = []
evidence = {"not_run": []}


def run(command, success=True, timeout=300):
    command = list(map(str, command))
    result = subprocess.run(
        command, env=env, cwd=repo, text=True, capture_output=True, timeout=timeout
    )
    commands.append(
        {
            "command": command,
            "exit_status": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    )
    (work / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
    assert result.returncode == (0 if success else 1), commands[-1]
    assert (
        "Assertion failed" not in result.stderr and "Traceback" not in result.stderr
    ), commands[-1]
    return result


def cli(*options, success=True):
    return run([sys.executable, "-m", "pycircuit.cli", *options], success)


def files(output, role):
    receipt = json.loads((output / "generated.json").read_text())
    return sorted(output / row["path"] for row in receipt["files"] if row["role"] == role)


DESIGN = """import pycircuit as ac

KEEP = 8


@ac.struct
class Lanes:
    lanes: ac.table[3, ac.u8]


@ac.module
def Ident(value: ac.bits[W], *, W: int = 4) -> ac.bits[W]:
    return value[:]


@ac.module
def Top(x: ac.u8, n: ac.u4, pick: ac.u2) -> Lanes:
    same = Ident(x, W=8)
    narrow = Ident(n)
    seeds: ac.table[3, ac.u8] = (1, 2, 3)

    @ac.rule
    def build() -> Lanes:
        mixed = Lanes(lanes=(same, 7, x[:KEEP]))
        if pick == 1:
            mixed = Lanes(lanes=(1, 2, 255))
        if pick == 2:
            mixed = Lanes(lanes=(seeds[0], seeds[1], seeds[2]))
        if pick == 3:
            mixed = Lanes(lanes=[narrow, x[0:8], 0])
        return mixed

    return build
"""

NEGATIVE = """import pycircuit as ac


@ac.struct
class Lanes:
    lanes: ac.table[3, ac.u8]


@ac.module
def Top(x: ac.u8) -> Lanes:
    @ac.rule
    def build() -> Lanes:
        BODY
        return mixed

    return build
"""
rejected = {
    "lane-out-of-range": ("mixed = Lanes(lanes=(256, 0, 0))", "not proven within destination bounds"),
    "too-few-lanes": ("mixed = Lanes(lanes=(1, 2))", "element count disagrees with extent"),
    "too-many-lanes": ("mixed = Lanes(lanes=(1, 2, 3, 4))", "element count disagrees with extent"),
    "no-table-context": (
        "lanes = (1, 2, 3)\n        mixed = Lanes(lanes=lanes)",
        "requires an expected Table type",
    ),
    "slice-beyond-width": (
        "mixed = Lanes(lanes=(x[:9], 0, 0))",
        "slice bounds require 0 <= lower < upper <= source width",
    ),
}
for name, (body, expected) in rejected.items():
    path = source / (name.replace("-", "_") + ".py")
    path.write_text(NEGATIVE.replace("BODY", body))
    absent = work / ("invalid-" + name)
    result = cli("compile", "-c", path, "--source-root", source, "-o", absent, success=False)
    assert expected in result.stderr, (name, result.stderr)
    assert not absent.exists(), name + " published an output unit"

path = source / "lanes.py"
path.write_text(DESIGN)
unit = work / "unit"
cli("compile", "-c", path, "--source-root", source, "-o", unit)
final = work / "lanes.ac"
cli("link", unit, "--top", "lanes.Top", "-o", final)
cpp, physical = work / "cpp", work / "physical"
cli("emit", final, "--target", "cpp", "-o", cpp)
cli("emit", final, "--target", "verilog", "--rtl-mode", "physical", "-o", physical)

runtime = next(
    (
        candidate
        for candidate in (
            Path(args.source_compiler).resolve().parent.parent
            / "runtime/libpyc6_runtime.a",
            Path(args.source_compiler).resolve().parent.parent
            / "lib/libpyc6_runtime.a",
        )
        if candidate.is_file()
    ),
    None,
)
assert runtime, "candidate Runtime archive missing"
runner = work / "native-runner"
run(
    [
        args.cxx,
        "-std=c++20",
        "-pthread",
        "-I" + str(repo / "include"),
        "-I" + str(cpp),
        fixtures / "lane-literals.cpp",
        *files(cpp, "source"),
        runtime,
        "-o",
        runner,
    ]
)
traces = {}
for workers in (1, 2):
    trace = run([runner, workers]).stdout
    assert trace.splitlines()[-1] == "PASS", trace
    traces[workers] = [row for row in trace.splitlines() if row.startswith("WORK ")]
    assert len(traces[workers]) == 8, traces[workers]
assert traces[1] == traces[2], "worker count changed the trace"

if args.verilator:
    build = work / "rtl-build"
    run(
        [
            args.verilator,
            "--binary",
            "--timing",
            "--top-module",
            "tb",
            "--prefix",
            "Vlanes",
            "--Mdir",
            build,
            "-j",
            "2",
            "-Wno-fatal",
            *sorted((repo / "include/verilog").glob("*.v")),
            *files(physical, "rtl"),
            fixtures / "lane-literals.sv",
        ]
    )
    trace = run([build / "Vlanes"]).stdout
    assert "PASS" in trace.splitlines(), trace
    assert [row for row in trace.splitlines() if row.startswith("WORK ")] == traces[1]
    evidence["rtl_physical"] = "verilator"
else:
    evidence["not_run"].append("physical RTL execution: verilator unavailable")

(work / "candidate.json").write_text(json.dumps(evidence, indent=2) + "\n")
sys.stdout.write("lane-literals gate passed\n")
