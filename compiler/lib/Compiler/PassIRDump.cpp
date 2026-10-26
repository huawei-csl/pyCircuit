#include "PassIRDump.h"

#include "mlir/IR/Operation.h"
#include "mlir/IR/OperationSupport.h"
#include "mlir/Pass/Pass.h"
#include "mlir/Pass/PassInstrumentation.h"
#include "llvm/ADT/SmallString.h"
#include "llvm/ADT/StringExtras.h"
#include "llvm/Support/FileSystem.h"
#include "llvm/Support/Format.h"
#include "llvm/Support/Path.h"
#include "llvm/Support/Regex.h"
#include "llvm/Support/raw_ostream.h"

#include <memory>
#include <mutex>
#include <optional>

using namespace mlir;

namespace acir::compiler {
namespace {

struct DumpState {
  PassIRDumpOptions options;
  std::optional<llvm::Regex> filter;
  std::mutex mutex;
  unsigned sequence = 0;
};

DumpState &state() {
  static DumpState instance;
  return instance;
}

std::string passName(Pass *pass) {
  // Registered passes have a command-line argument; an unregistered helper
  // pass falls back to its unqualified C++ class name.
  std::string name = pass->getArgument().str();
  if (name.empty()) {
    llvm::StringRef type = pass->getName();
    name = type.substr(type.rfind(':') + 1).str();
  }
  for (char &c : name)
    if (!llvm::isAlnum(c) && c != '-' && c != '_' && c != '.')
      c = '_';
  return name.empty() ? std::string("pass") : name;
}

class PassIRDumper final : public PassInstrumentation {
public:
  void runBeforePass(Pass *pass, Operation *op) override {
    if (wants("before"))
      write(pass, op, "before", false);
  }
  void runAfterPass(Pass *pass, Operation *op) override {
    if (wants("after"))
      write(pass, op, "after", false);
  }
  // A failure is always recorded, whatever the phase selection.
  void runAfterPassFailed(Pass *pass, Operation *op) override {
    write(pass, op, "after", true);
  }

private:
  static bool wants(llvm::StringRef phase) {
    llvm::StringRef selected = state().options.phase;
    return selected == "both" || selected == phase;
  }
  static void write(Pass *pass, Operation *op, llvm::StringRef phase,
                    bool failed) {
    DumpState &dump = state();
    std::string name = passName(pass);
    if (dump.filter && !dump.filter->match(name))
      return;
    // Print outside the lock; nested pipelines may run passes concurrently.
    std::string text;
    llvm::raw_string_ostream stream(text);
    if (failed)
      stream << "// PASS FAILED\n";
    stream << "// pass: " << name << " on '" << op->getName() << "'\n";
    op->print(stream, OpPrintingFlags().useLocalScope());
    stream << '\n';
    unsigned sequence;
    {
      std::lock_guard<std::mutex> lock(dump.mutex);
      sequence = dump.sequence++;
    }
    llvm::SmallString<256> path(dump.options.directory);
    std::string file;
    llvm::raw_string_ostream fileName(file);
    fileName << llvm::format("%04u", sequence) << '_' << phase << '_' << name
             << (failed ? "_FAILED" : "") << ".mlir";
    llvm::sys::path::append(path, file);
    std::error_code error;
    llvm::raw_fd_ostream out(path, error, llvm::sys::fs::OF_Text);
    if (error) {
      llvm::errs() << "warning: cannot write pass IR dump '" << path
                   << "': " << error.message() << '\n';
      return;
    }
    out << text;
  }
};

} // namespace

LogicalResult configurePassIRDump(PassIRDumpOptions options,
                                  std::string &error) {
  if (options.phase != "before" && options.phase != "after" &&
      options.phase != "both") {
    error = "pass IR dump phase must be before, after or both";
    return failure();
  }
  std::optional<llvm::Regex> filter;
  if (!options.filter.empty()) {
    filter.emplace(options.filter);
    std::string reason;
    if (!filter->isValid(reason)) {
      error = "invalid pass IR dump filter '" + options.filter + "': " + reason;
      return failure();
    }
  }
  if (!options.directory.empty())
    if (auto code = llvm::sys::fs::create_directories(options.directory)) {
      error = "cannot create pass IR dump directory '" + options.directory +
              "': " + code.message();
      return failure();
    }
  DumpState &dump = state();
  std::lock_guard<std::mutex> lock(dump.mutex);
  dump.options = std::move(options);
  dump.filter = std::move(filter);
  dump.sequence = 0;
  return success();
}

void instrumentPassIRDump(PassManager &manager) {
  if (!state().options.directory.empty())
    manager.addInstrumentation(std::make_unique<PassIRDumper>());
}

} // namespace acir::compiler
