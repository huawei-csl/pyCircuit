"""Several guarded writes to one state variable inside one Rule.

`acc` is assigned under three independent guards in one Rule, and the second
assignment reads the first. The compiler must build one next-state value from
the Rule's sequential SSA: later writes win, earlier writes are visible to
later reads, and an unwritten path holds. This harness checks that

* the final artifact owns exactly one storage leaf for `acc`;
* the emitted RTL drives every net exactly once (one continuous assign or one
  child output pin), and yosys `check -assert` agrees when it is available;
* native C++ (workers 1/2) and physical RTL under Verilator match an
  independent replay of the Rule over all guard combinations.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
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
work = scratch / "rule-sequential-writes"
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


def cli(*options):
    return run([sys.executable, "-m", "pycircuit.cli", *options])


def files(output, role):
    receipt = json.loads((output / "generated.json").read_text())
    return sorted(output / row["path"] for row in receipt["files"] if row["role"] == role)


DESIGN = """import pycircuit as ac


@ac.module
def LastWrite(a: ac.u1, b: ac.u1, c: ac.u1, x: ac.u8, y: ac.u8, z: ac.u8) -> ac.u8:
    acc: ac.u8 = 0

    @ac.rule
    def step() -> ac.u8:
        seen = acc
        if a:
            acc = x
        if b:
            acc = y + acc
        if c:
            acc = z
        return seen

    return step
"""
path = source / "last_write.py"
path.write_text(DESIGN)
unit = work / "unit"
cli("compile", "-c", path, "--source-root", source, "-o", unit)
final = work / "last_write.ac"
cli("link", unit, "--top", "last_write.LastWrite", "-o", final)
cpp, physical, managed = work / "cpp", work / "physical", work / "managed"
cli("emit", final, "--target", "cpp", "-o", cpp)
cli("emit", final, "--target", "verilog", "--rtl-mode", "physical", "-o", physical)
cli("emit", final, "--target", "verilog", "--rtl-mode", "managed", "-o", managed)

# One storage leaf for the one declaration, whatever the number of writes.
text = final.read_text()
leaves = re.findall(r'callee = @pycircuit\.__builtins__\.(dffe?)\b[^\n]*?instance_name = "(\w+)"', text)
assert leaves == [("dffe", "acc")], leaves

def preprocess(text, defined):
    """Keep the lines of the active `ifdef/`ifndef/`else branches."""
    kept, active = [], [True]
    for line in text.splitlines():
        directive = re.match(r"\s*`(ifdef|ifndef|else|endif)\b\s*(\w*)", line)
        if not directive:
            if all(active):
                kept.append(line)
            continue
        kind, macro = directive.groups()
        if kind in ("ifdef", "ifndef"):
            active.append((macro in defined) == (kind == "ifdef"))
        elif kind == "else":
            active[-1] = not active[-1]
        else:
            active.pop()
    return "\n".join(kept) + "\n"


# Every net has one driver: a whole-net continuous assign or a child output,
# in simulation and in synthesis elaboration alike.
for output, defined in ((physical, ()), (physical, ("SYNTHESIS",)), (managed, ())):
    for rtl in files(output, "rtl"):
        drivers = Counter()
        text = preprocess(rtl.read_text(), defined)
        for module in re.findall(r"^module \w+ \(.*?^endmodule", text, re.S | re.M):
            for target in re.findall(r"^\s*assign (\w+) =", module, re.M):
                drivers[target] += 1
            for target in re.findall(r"^\s*(?:wire|logic)\b[^;=]*?\b(\w+) = ", module, re.M):
                drivers[target] += 1
            for pin, target in re.findall(r"\.(q|rdata\w*|rlive\w*)\((\w+)\)", module):
                drivers[target] += 1
        repeated = {net: n for net, n in drivers.items() if n > 1}
        assert not repeated, (rtl, repeated)
        if rtl.name == "last_write.v":
            # The source module itself: the next-state chain and its leaf.
            assert len(drivers) > 10 and drivers["result"] == 1, drivers

if args.sv2v and args.yosys:
    sources = [
        *sorted((repo / "include/verilog").glob("dff*.v")),
        *files(physical, "rtl"),
    ]
    converted = work / "last_write.synth.v"
    converted.write_text(run([args.sv2v, "-DSYNTHESIS", *sources]).stdout)
    # `check -assert` fails on a net with more than one driver.
    run(
        [
            args.yosys,
            "-q",
            "-p",
            f"read_verilog -sv {converted}; hierarchy -top pyc_root; proc; "
            "check -assert; synth -flatten -top pyc_root; check -assert",
        ]
    )
    evidence["yosys_check"] = "pass"
else:
    evidence["not_run"].append("yosys check: sv2v or yosys unavailable")

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
        fixtures / "rule-sequential-writes.cpp",
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
    assert len(traces[workers]) == 48, len(traces[workers])
assert traces[1] == traces[2], "worker count changed the committed trace"

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
            "Vsequential",
            "--Mdir",
            build,
            "-j",
            "2",
            "-Wno-fatal",
            *sorted((repo / "include/verilog").glob("*.v")),
            *files(physical, "rtl"),
            fixtures / "rule-sequential-writes.sv",
        ]
    )
    trace = run([build / "Vsequential"]).stdout
    assert "PASS" in trace.splitlines(), trace
    assert [row for row in trace.splitlines() if row.startswith("WORK ")] == traces[1]
    evidence["rtl_physical"] = "verilator"
else:
    evidence["not_run"].append("physical RTL execution: verilator unavailable")

(work / "candidate.json").write_text(json.dumps(evidence, indent=2) + "\n")
sys.stdout.write("rule-sequential-writes gate passed\n")
