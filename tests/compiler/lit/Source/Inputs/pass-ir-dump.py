"""Per-pass IR dump on `pycircuit compile` and `pycircuit link`.

The dump is diagnostics only. This harness checks that it is off by default,
that `--dump-pass-ir DIR` writes one file per pass and phase in execution
order with the IR the pass saw or produced, that phase and filter select
files, that a malformed phase or filter is refused before any publication,
and that the published unit and final design are byte-identical with and
without the dump.
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
args = parser.parse_args()
repo = Path(args.repo).resolve()
fixtures = Path(__file__).resolve().parent
scratch = Path(args.scratch).resolve()
work = scratch / "pass-ir-dump"
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


DESIGN = """import pycircuit as ac


@ac.module
def Counter(enable: ac.u1) -> ac.u8:
    count: ac.u8 = 3

    @ac.rule
    def step() -> ac.u8:
        if enable:
            count = count + 1
        return count

    return step
"""
path = source / "counter.py"
path.write_text(DESIGN)
NAME = re.compile(r"^(\d{4})_(before|after)_([A-Za-z0-9_.-]+?)(_FAILED)?\.mlir$")


def listing(directory):
    names = sorted(p.name for p in directory.iterdir())
    rows = [NAME.match(name) for name in names]
    assert all(rows), names
    assert [int(row.group(1)) for row in rows] == list(range(len(rows))), names
    return [(row.group(2), row.group(3)) for row in rows]


def compile_unit(output, *options, success=True):
    return cli("compile", "-c", path, "--source-root", source, "-o", output,
               *options, success=success)


# Off by default: the plain publication is the reference for byte identity.
plain_unit, plain_final = work / "plain-unit", work / "plain.ac"
compile_unit(plain_unit)
cli("link", plain_unit, "--top", "counter.Counter", "-o", plain_final)

# compile: the source-unit pipeline, after each pass by default.
dumped_unit, compile_dump = work / "dumped-unit", work / "compile-dump"
compile_unit(dumped_unit, "--dump-pass-ir", compile_dump)
compile_rows = listing(compile_dump)
assert compile_rows == [
    ("after", "ac-analyze-rule-writes"),
    ("after", "ac-infer-source-bindings"),
    ("after", "ac-lower-python-source"),
    ("after", "ac-normalize-source-control-flow"),
    ("after", "ac-analyze-source-method-summaries"),
    ("after", "ac-extract-source-interface"),
], compile_rows
first = sorted(compile_dump.iterdir())[0].read_text()
assert first.startswith("// pass: ac-analyze-rule-writes on 'builtin.module'"), first[:200]
assert '"ac.state"' in sorted(compile_dump.iterdir())[2].read_text()
for name in ("counter.ac", "counter.interface.ac"):
    assert (plain_unit / name).read_bytes() == (dumped_unit / name).read_bytes(), name

# link: both phases bracket each pass of the link pipeline.
link_dump, dumped_final = work / "link-dump", work / "dumped.ac"
cli("link", dumped_unit, "--top", "counter.Counter", "-o", dumped_final,
    "--dump-pass-ir", link_dump, "--dump-pass-ir-phase", "both")
link_rows = listing(link_dump)
passes = [name for phase, name in link_rows[::2]]
assert [phase for phase, _ in link_rows] == ["before", "after"] * len(passes), link_rows
assert [name for _, name in link_rows[1::2]] == passes, link_rows
assert passes[0] == "ac-normalize-source-control-flow", passes
assert passes[-1] == "ac-lower-transactions", passes
assert "CompactLiteralPayloadWiresPass" in passes, passes
last = sorted(link_dump.iterdir())[-1].read_text()
assert "pycircuit.__builtins__.dff" in last and '"ac.state"' not in last
assert plain_final.read_bytes() == dumped_final.read_bytes()

# The filter selects passes by argument.
filtered = work / "filtered-dump"
cli("link", dumped_unit, "--top", "counter.Counter", "-o", work / "filtered.ac",
    "--dump-pass-ir", filtered, "--dump-pass-ir-phase", "before",
    "--dump-pass-ir-filter", "route|lower-trans")
assert listing(filtered) == [
    ("before", "ac-route-transactions"),
    ("before", "ac-lower-transactions"),
], listing(filtered)

# Malformed requests are refused and publish nothing.
for options, expected in (
    (("--dump-pass-ir", work / "bad-filter", "--dump-pass-ir-filter", "("),
     "invalid pass IR dump filter"),
    (("--dump-pass-ir-filter", "lower"), "require --dump-pass-ir"),
):
    absent = work / "absent-unit"
    result = compile_unit(absent, *options, success=False)
    assert expected in result.stderr, result.stderr
    assert not absent.exists()
# argparse refuses an unknown phase (exit status 2) before any work.
result = subprocess.run(
    [sys.executable, "-m", "pycircuit.cli", "link", dumped_unit, "--top",
     "counter.Counter", "-o", work / "absent.ac", "--dump-pass-ir",
     work / "bad-phase", "--dump-pass-ir-phase", "sideways"],
    env=env, cwd=repo, text=True, capture_output=True, timeout=120,
)
assert result.returncode == 2 and "invalid choice" in result.stderr, result.stderr
assert not (work / "absent.ac").exists() and not (work / "bad-phase").exists()
result = run([args.source_compiler, "--capture", path, "--path", "counter.py",
              "--body-out", work / "x.ac", "--interface-out", work / "x.i.ac",
              "--dump-pass-ir", work / "native", "--dump-pass-ir-phase", "sideways"],
             success=False)
assert "phase must be before, after or both" in result.stderr, result.stderr
sys.stdout.write("pass-ir-dump gate passed\n")
