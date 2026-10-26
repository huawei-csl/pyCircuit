# Compiler pipeline

The active compiler processes source one unit at a time, links an explicit
closure, verifies a common final design, then selects a backend:

1. `pycircuit compile -c source.py` captures exactly one Python source and
   publishes its body, interface, dependency file, and unit receipt.
2. Parent sources import compiler-published interfaces through explicit `-I`
   unit directories. The compiler does not fall back to child Python bodies.
3. `pycircuit link <units...> --top ...` validates the complete unit closure,
   resolves instances, and publishes one verified final design.
4. `pycircuit emit <design_top.ac> --target cpp|verilog` verifies the final
   input and emits the chosen target.

The same saved final design is input to both backends. No whole-system capture
followed by source splitting is allowed. C++ output keeps one implementation
source group per source unit, plus generated core/runtime glue. Generated CMake
compiles those units separately as `pycircuit_modules`; the host driver links
them with the shared Runtime.

Runtime-only CMake exports `pycircuit::pyc6_runtime` without LLVM discovery.
CompilerDev includes native compiler development targets and requires exact
LLVM/MLIR 22.1.8.

The common source and final hardware representation is ACIR. Its `ac` dialect
name is an IR identifier, not another Python frontend. Unsupported source or
backend capabilities fail before output publication; see
[known limitations](../development/known-limitations.md).

## Pass pipelines

Each command runs fixed MLIR pass managers. In execution order:

| Command | Pass (argument) | Runs when |
| --- | --- | --- |
| `compile` | `ac-analyze-rule-writes` | always |
| | `ac-infer-source-bindings` | always |
| | `ac-lower-python-source` | always |
| | `ac-normalize-source-control-flow` | always |
| | `ac-analyze-source-method-summaries` | always |
| | `ac-simplify-record-wires` | the unit has no source transaction effects |
| | `ac-extract-source-interface` | always, on a copy of the body; the result is the published interface |
| `link` | `ac-normalize-source-control-flow` | always |
| | `CompactLiteralPayloadWiresPass` | always (internal pass, not registered) |
| | `DiscardUninstantiatedReferenceTemplatesPass` | always (internal pass, not registered) |
| | `ac-analyze-transaction-state-ssa` | the linked design has unlowered transactions |
| | `ac-route-transactions` | always |
| | `ac-lower-transactions` | `--target final` (not for an anchor) |

Verification, closure checks, hardware-state materialization inside
`ac-lower-transactions` and both emitters are not separate passes. `emit` runs
no pass manager. Registered passes can be run one at a time with
`pycircuit-opt --<argument>`.

## Per-pass IR dump

`pycircuit compile` and `pycircuit link` take `--dump-pass-ir DIR` to write the
IR around every pass of the tables above. It is a diagnostic only: the IR,
the result and the published artifacts are byte-identical with and without
it, and nothing is written unless it is given.

| Option | Default | Meaning |
| --- | --- | --- |
| `--dump-pass-ir DIR` | off | Directory for the files; created if missing. |
| `--dump-pass-ir-phase before\|after\|both` | `after` | Which side of each pass to write. A failing pass is always written. |
| `--dump-pass-ir-filter REGEX` | all passes | Write only passes whose argument (or internal class name) matches. |

Files are named `NNNN_<phase>_<pass>[_FAILED].mlir`. `NNNN` is one sequence
across every pass manager of the command, so lexical order is execution
order and the file before a pass's `after` file is its input. Each file
starts with `// pass: <pass> on '<operation>'`; a failure adds
`// PASS FAILED`. To see what one pass changed:

```bash
pycircuit link unit --top pkg.Top -o top.ac --dump-pass-ir ir --dump-pass-ir-phase both
diff ir/0008_before_ac-route-transactions.mlir ir/0009_after_ac-route-transactions.mlir
```

The native tools take the same options (`pycircuit-source-unit
--dump-pass-ir=DIR`, `pycircuit-link --dump-pass-ir DIR`). `pycircuit-opt` is
a standard MLIR driver and already has the generic equivalents:
`--mlir-print-ir-before-all`, `--mlir-print-ir-after-all`,
`--mlir-print-ir-after-failure` and `--mlir-print-ir-tree-dir=DIR`.
