"""State declared without an initializer has no reset value and no reset.

`coeff: ac.u8` (no `= value`) allocates the same DFF/DFFE storage child as an
initialized declaration, marked `ac.no_reset`. This harness checks the whole
route independently of the DUT:

* source admission: fixed Bits and Tables of fixed Bits are accepted; Boolean,
  bounded Integer, Enum and Struct declarations without an initializer reject
  without publishing a unit;
* the final artifact marks exactly the uninitialized leaves;
* native C++ (workers 1/2): the payload is X until written, a sampled reset
  neither loads nor blocks it, and host Reset retains it, while initialized
  state beside it still resets;
* physical RTL: the same known sequence under Verilator, the primitive
  parameter only on the uninitialized leaves, and -- when sv2v and yosys are
  available -- synthesis under SYNTHESIS maps them to plain flops while the
  initialized controls keep their synchronous reset.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
for option in ("repo", "source-compiler", "linker", "emitter", "cxx", "scratch"):
    parser.add_argument("--" + option, required=True)
for tool in ("verilator", "sv2v", "yosys"):
    parser.add_argument("--" + tool, default=shutil.which(tool))
args = parser.parse_args()
repo = Path(args.repo).resolve()
fixtures = Path(__file__).resolve().parent
scratch = Path(args.scratch).resolve()
# lit's %t.dir is reused between runs; recreate every publication below.
work = scratch / "state-no-reset"
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


def write(name, text):
    path = source / name
    path.write_text(text)
    return path


def build(name, top, *targets):
    path = write(name + ".py", SOURCES[name])
    unit = work / ("unit-" + name)
    cli("compile", "-c", path, "--source-root", source, "-o", unit)
    final = work / (name + ".ac")
    cli("link", unit, "--top", name + "." + top, "-o", final)
    outputs = {}
    for target, mode in targets:
        output = work / f"{name}-{target}-{mode}"
        options = ["--rtl-mode", mode] if target == "verilog" else []
        cli("emit", final, "--target", target, *options, "-o", output)
        outputs[target, mode] = output
    return final, outputs


def files(output, role):
    receipt = json.loads((output / "generated.json").read_text())
    return sorted(output / row["path"] for row in receipt["files"] if row["role"] == role)


TAPS = """import pycircuit as ac


@ac.struct
class Observed:
    coeff: ac.u8
    sample: ac.u8
    count: ac.u8
    tap: ac.u4


@ac.module
def Taps(load: ac.u1, value: ac.u8, sample_in: ac.u8) -> Observed:
    coeff: ac.u8
    sample: ac.u8
    count: ac.u8 = 5
    taps: ac.table[2, ac.u4]

    @ac.rule
    def update() -> Observed:
        seen = Observed(coeff=coeff, sample=sample, count=count, tap=taps[1])
        if load:
            coeff = value
            taps[1] = value[:4]
        sample = sample_in
        count = count + 1
        return seen

    return update
"""


def leaf(declaration, guarded):
    write_line = "        if load:\n            held = value\n" if guarded else (
        "        held = value\n"
    )
    return (
        "import pycircuit as ac\n\n\n"
        "@ac.module\n"
        "def Leaf(load: ac.u1, value: ac.u8) -> ac.u8:\n"
        f"    {declaration}\n\n"
        "    @ac.rule\n"
        "    def step() -> ac.u8:\n"
        "        seen = held\n" + write_line + "        return seen\n\n"
        "    return step\n"
    )


SOURCES = {
    "taps": TAPS,
    "enabled_plain": leaf("held: ac.u8", True),
    "enabled_reset": leaf("held: ac.u8 = 0", True),
    "always_plain": leaf("held: ac.u8", False),
    "always_reset": leaf("held: ac.u8 = 0", False),
}

# --- Source admission ------------------------------------------------------
REJECTED = {
    "boolean": "flag: bool",
    "integer": "level: Annotated[int, range(8)]",
    "record": "pair: Pair",
    "nominal": "mode: Mode",
}
for name, declaration in REJECTED.items():
    path = write(
        "rejected_" + name + ".py",
        "from enum import Enum\nfrom typing import Annotated\n"
        "import pycircuit as ac\n\n\n"
        "@ac.struct\nclass Pair:\n    low: ac.u4\n    high: ac.u4\n\n\n"
        "@ac.encoding(width=2)\nclass Mode(Enum):\n"
        "    IDLE = 0\n    BUSY = 1\n\n\n"
        "@ac.module\ndef Top(value: ac.u1) -> ac.u1:\n"
        f"    {declaration}\n\n"
        "    @ac.rule\n    def step() -> ac.u1:\n        return value\n\n"
        "    return step\n",
    )
    absent = work / ("invalid-" + name)
    rejected = cli(
        "compile", "-c", path, "--source-root", source, "-o", absent, success=False
    )
    assert re.search(
        r"without an initializer \(no reset\) requires a fixed-Bits",
        rejected.stderr,
    ), (name, rejected.stderr)
    assert not absent.exists(), name + " published an output unit"

# --- Final artifact and both targets ---------------------------------------
final, outputs = build(
    "taps", "Taps", ("cpp", "managed"), ("verilog", "physical"), ("verilog", "managed")
)
text = final.read_text()
marked = sorted(
    re.findall(r'instance_name = "(\w+)"[^\n]*?\bac\.no_reset\b', text)
    + re.findall(r'\bac\.no_reset\b[^\n]*?instance_name = "(\w+)"', text)
)
assert sorted(set(marked)) == ["coeff", "sample", "taps"], marked
for mode in ("physical", "managed"):
    rtl = "\n".join(p.read_text() for p in files(outputs["verilog", mode], "rtl"))
    leaves = dict(
        (name, body)
        for body, name in re.findall(
            r"(dffe? #\([^;]*?\)) pyc_instance_(\w+) \(", rtl, re.S
        )
    )
    assert sorted(leaves) == ["coeff", "count", "sample", "taps"], sorted(leaves)
    for name, body in leaves.items():
        assert ("pyc_no_reset(1'b1)" in body) == (name != "count"), (mode, name)
    # The domain reset stays connected to every leaf: it names the clock
    # domain. Only the primitive parameter drops its effect.
    resets = re.findall(r"\.rst\(([^)]*)\)", rtl)
    assert len(resets) == 4 and not any("'" in net for net in resets), resets

# --- Native execution ------------------------------------------------------
runtime = next(
    (
        path
        for path in (
            Path(args.source_compiler).resolve().parent.parent
            / "runtime/libpyc6_runtime.a",
            Path(args.source_compiler).resolve().parent.parent
            / "lib/libpyc6_runtime.a",
        )
        if path.is_file()
    ),
    None,
)
assert runtime, "candidate Runtime archive missing"
cpp = outputs["cpp", "managed"]
runner = work / "native-runner"
run(
    [
        args.cxx,
        "-std=c++20",
        "-pthread",
        "-I" + str(repo / "include"),
        "-I" + str(cpp),
        fixtures / "state-no-reset.cpp",
        *files(cpp, "source"),
        runtime,
        "-o",
        runner,
    ]
)
traces = {}
for workers in (1, 2):
    trace = run([runner, workers]).stdout
    (work / f"native-{workers}.stdout").write_text(trace)
    assert trace.splitlines()[-1] == "PASS", trace
    traces[workers] = [row for row in trace.splitlines() if row.startswith("WORK ")]
assert traces[1] == traces[2], "worker count changed the committed trace"
evidence["native_workers"] = [1, 2]

# --- Physical RTL execution ------------------------------------------------
if args.verilator:
    rtl_build = work / "rtl-build"
    run(
        [
            args.verilator,
            "--binary",
            "--timing",
            "--top-module",
            "tb",
            "--prefix",
            "Vnoreset",
            "--Mdir",
            rtl_build,
            "-j",
            "2",
            "-Wno-fatal",
            *sorted((repo / "include/verilog").glob("*.v")),
            *files(outputs["verilog", "physical"], "rtl"),
            fixtures / "state-no-reset.sv",
        ]
    )
    rtl_trace = run([rtl_build / "Vnoreset"]).stdout
    (work / "rtl.stdout").write_text(rtl_trace)
    assert "PASS" in rtl_trace.splitlines(), rtl_trace
    known = [row for row in traces[1] if "x" not in row]
    assert [row for row in rtl_trace.splitlines() if row.startswith("WORK ")] == known
    evidence["rtl_physical"] = "verilator"
else:
    evidence["not_run"].append("physical RTL execution: verilator unavailable")

# --- Synthesis under SYNTHESIS ---------------------------------------------
# yosys prints "<count> <cell>" (newer) or "<cell> <count>" (older) rows.
FLOPS = re.compile(r"^\s+(?:(\d+)\s+(\$_\w*DFF\w*)|(\$_\w*DFF\w*)\s+(\d+))$", re.M)
if args.sv2v and args.yosys:
    cells = {}
    for name in ("enabled_plain", "enabled_reset", "always_plain", "always_reset"):
        _, built = build(name, "Leaf", ("verilog", "physical"))
        sources = [
            *sorted((repo / "include/verilog").glob("dff*.v")),
            *files(built["verilog", "physical"], "rtl"),
        ]
        converted = work / (name + ".synth.v")
        converted.write_text(run([args.sv2v, "-DSYNTHESIS", *sources]).stdout)
        report = run(
            [
                args.yosys,
                "-q",
                "-p",
                f"read_verilog -sv {converted}; synth -flatten -top pyc_root; "
                "check -assert; tee -o " + str(work / (name + ".stat")) + " stat",
            ]
        )
        stat = (work / (name + ".stat")).read_text()
        cells[name] = {
            a_cell or b_cell: int(a_count or b_count)
            for a_count, a_cell, b_cell, b_count in FLOPS.findall(stat)
        }
    assert cells["enabled_plain"] == {"$_DFFE_PP_": 8}, cells
    assert cells["always_plain"] == {"$_DFF_P_": 8}, cells
    for name in ("enabled_reset", "always_reset"):
        assert cells[name] and all(c.startswith("$_SDFF") for c in cells[name]), cells
    evidence["synthesis_flops"] = cells
else:
    evidence["not_run"].append("synthesis: sv2v or yosys unavailable")

(work / "candidate.json").write_text(json.dumps(evidence, indent=2) + "\n")
sys.stdout.write("state-no-reset gate passed\n")
