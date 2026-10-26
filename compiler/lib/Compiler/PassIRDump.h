#pragma once

#include "mlir/Pass/PassManager.h"
#include "mlir/Support/LLVM.h"

#include <string>

namespace acir::compiler {

/// Per-pass IR dump for the native compile and link tools. Diagnostics only:
/// the dump never changes the IR or the outcome of a pass, and it is off
/// unless a directory is configured.
struct PassIRDumpOptions {
  /// Output directory; empty disables the dump.
  std::string directory;
  /// "before", "after" or "both".
  std::string phase = "after";
  /// llvm::Regex matched against the pass argument; empty matches every pass.
  std::string filter;
};

/// Validates and installs the process-wide configuration. Every pass manager
/// instrumented afterwards shares one sequence, so the lexical order of the
/// files is the execution order across all pipelines of one tool run.
mlir::LogicalResult configurePassIRDump(PassIRDumpOptions options,
                                        std::string &error);

/// Adds the dump instrumentation to `manager` when a directory is configured.
void instrumentPassIRDump(mlir::PassManager &manager);

} // namespace acir::compiler
