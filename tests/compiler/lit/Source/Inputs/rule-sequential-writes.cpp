// Several guarded writes to one state variable inside one Rule. The oracle
// replays the Rule's statements in source order on the committed value; it
// never reads a DUT sample to compute an expectation.
#include "pycircuit_system.hpp"
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <source_location>

void require(bool ok, std::source_location at = std::source_location::current()) {
  if (!ok) { std::cerr << "sequential-writes oracle line " << at.line() << '\n'; std::abort(); }
}
template <unsigned W> auto known(std::uint64_t value) {
  return gfsim::wire<gfsim::Bits<W>>::known(gfsim::Bits<W>{value});
}

int main(int argc, char **argv) {
  require(argc == 2);
  const unsigned workers = std::strtoul(argv[1], nullptr, 10);
  require(workers == 1 || workers == 2);
  gfsim::WorkExecutor pool(workers);
  pyc_root root("sequential-writes", &pool);
  root.a = root.b = root.c = known<1>(0);
  root.x = root.y = root.z = known<8>(0);
  root.pyc_7079635f636c6b = root.pyc_7079635f727374 = known<1>(0);
  root.Reset();
  root.Xfer();
  unsigned committed = 0;  // declared initializer
  unsigned epoch = 0;
  for (unsigned round = 0; round < 3; ++round)
    for (unsigned guards = 0; guards < 8; ++guards) {
      const unsigned a = guards & 1, b = (guards >> 1) & 1, c = guards >> 2;
      const unsigned x = 0x11 * (round + 1), y = 0x07 + round, z = 0xa0 + guards;
      root.a = known<1>(a); root.b = known<1>(b); root.c = known<1>(c);
      root.x = known<8>(x); root.y = known<8>(y); root.z = known<8>(z);
      for (unsigned clock : {0u, 1u}) {
        root.pyc_7079635f636c6b = known<1>(clock);
        root.Work();
        const auto seen = root.result.packed();
        require(seen.isFullyKnown() && seen.value().value() == committed);
        std::cout << "WORK " << epoch++ << ' ' << committed << '\n';
        root.Xfer();
      }
      // Sequential Rule semantics: later guards win, and `acc = y + acc`
      // reads the value an earlier statement of this Rule assigned.
      unsigned next = committed;
      if (a) next = x;
      if (b) next = (y + next) & 0xffu;
      if (c) next = z;
      committed = next;
    }
  std::cout << "PASS\n";
  return 0;
}
