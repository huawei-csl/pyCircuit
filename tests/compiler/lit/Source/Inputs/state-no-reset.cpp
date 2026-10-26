// State without a reset value. The expected rows below are written from the
// declared semantics, never from a DUT sample: an uninitialized declaration is
// X until written, a sampled reset neither loads nor blocks it, a host Reset
// retains it, and the initialized `count` beside it resets to 5 as before.
#include "pycircuit_system.hpp"
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <source_location>
#include <sstream>
#include <string>

void require(bool ok, std::source_location at = std::source_location::current()) {
  if (!ok) { std::cerr << "state-no-reset oracle line " << at.line() << '\n'; std::abort(); }
}
template <unsigned W> auto known(std::uint64_t value) {
  return gfsim::wire<gfsim::Bits<W>>::known(gfsim::Bits<W>{value});
}
// Observed packs coeff, sample, count (8 bits each) and tap (4 bits), first
// field most significant. An unknown field prints as "x".
template <unsigned W, unsigned P>
std::string field(const gfsim::FourState<P> &packed, unsigned lsb) {
  const auto part = gfsim::extract<W>(packed, lsb);
  if (!part.isFullyKnown()) {
    require(part.knownMask() == gfsim::Bits<W>{0});  // wholly X, no Z, no mix
    require(part.zMask() == gfsim::Bits<W>{0});
    return "x";
  }
  std::ostringstream text;
  text << std::hex << part.value().value();
  return text.str();
}

struct Frame { unsigned clock, reset, load, value, sample; const char *expected; };
// Observation at Work is the state committed before this epoch's edge.
constexpr Frame frames[] = {
    {0, 0, 0, 0x00, 0x00, "x x 5 x"},
    {1, 0, 1, 0x5a, 0x11, "x x 5 x"},  // first writes; count 5 -> 6
    {0, 0, 0, 0x00, 0x00, "5a 11 6 a"},
    {1, 1, 0, 0x00, 0x22, "5a 11 6 a"},  // reset edge, no load: coeff holds
    {0, 0, 0, 0x00, 0x00, "5a 22 5 a"},  // sample still written, count reset
    {1, 1, 1, 0xc3, 0x33, "5a 22 5 a"},  // reset edge with load: loads anyway
    {0, 0, 0, 0x00, 0x00, "c3 33 5 3"},
    {1, 0, 0, 0x00, 0x44, "c3 33 5 3"},
    {0, 0, 0, 0x00, 0x00, "c3 44 6 3"},
};

int main(int argc, char **argv) {
  require(argc == 2);
  const unsigned workers = std::strtoul(argv[1], nullptr, 10);
  require(workers == 1 || workers == 2);
  gfsim::WorkExecutor pool(workers);
  pyc_root root("state-no-reset", &pool);
  root.load = known<1>(0);
  root.value = root.sample_in = known<8>(0);
  root.pyc_7079635f636c6b = root.pyc_7079635f727374 = known<1>(0);
  root.Reset();
  root.Xfer();
  auto observe = [&](const char *tag, unsigned epoch, const char *expected) {
    root.Work();
    const auto packed = root.result.packed();
    require(packed.invariantHolds());
    const std::string row = field<8>(packed, 20) + ' ' + field<8>(packed, 12) +
                            ' ' + field<8>(packed, 4) + ' ' + field<4>(packed, 0);
    std::cout << tag << ' ' << epoch << ' ' << row << '\n';
    require(row == expected);
    root.Xfer();
  };
  unsigned epoch = 0;
  for (const Frame &frame : frames) {
    root.pyc_7079635f636c6b = known<1>(frame.clock);
    root.pyc_7079635f727374 = known<1>(frame.reset);
    root.load = known<1>(frame.load);
    root.value = known<8>(frame.value);
    root.sample_in = known<8>(frame.sample);
    observe("WORK", epoch++, frame.expected);
  }
  // Host Reset restores initialized state and retains state without a reset.
  root.load = known<1>(0);
  root.pyc_7079635f636c6b = root.pyc_7079635f727374 = known<1>(0);
  root.Reset();
  root.Xfer();
  observe("RESET", epoch++, "c3 44 5 3");
  // The reset policy itself is unchanged. Check the register kernel alone,
  // without the initialized `count` beside it: an unknown reset at a rising
  // edge still faults and leaves no pending update.
  gfsim::dffe_kernel<gfsim::Bits<8>, true>::Current current;
  gfsim::dffe_kernel<gfsim::Bits<8>, true>::Pending pending;
  gfsim::wire<gfsim::Bits<8>> q;
  const auto low = known<1>(0), high = known<1>(1);
  const auto unknown = gfsim::wire<gfsim::Bits<1>>::unknown();
  const auto data = known<8>(0x7e), init = known<8>(0x01);
  using Leaf = gfsim::dffe_kernel<gfsim::Bits<8>, true>;
  bool faulted = false;
  try {
    Leaf::work(current, {high, unknown, high, data, init}, pending, {q});
  } catch (const std::exception &) {
    faulted = true;
  }
  require(faulted && !pending.valid);
  // A known reset at a rising edge neither loads init nor blocks the write.
  Leaf::work(current, {high, high, high, data, init}, pending, {q});
  Leaf::xfer(current, pending, {q});
  require(q.isFullyKnown() && q.value().value() == 0x7e);
  // A host reset retains the committed value.
  Leaf::reset(current, {low, high, low, data, init}, pending);
  Leaf::xfer(current, pending, {q});
  require(q.isFullyKnown() && q.value().value() == 0x7e);
  std::cout << "PASS\n";
  return 0;
}
