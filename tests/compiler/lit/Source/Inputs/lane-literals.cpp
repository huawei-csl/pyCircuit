// Constant and mixed Table lanes, and identity slices. Expected lanes are
// written from the source text: lane 0 is the most significant packed lane.
#include "pycircuit_system.hpp"
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <source_location>

void require(bool ok, std::source_location at = std::source_location::current()) {
  if (!ok) { std::cerr << "lane-literals oracle line " << at.line() << '\n'; std::abort(); }
}
template <unsigned W> auto known(std::uint64_t value) {
  return gfsim::wire<gfsim::Bits<W>>::known(gfsim::Bits<W>{value});
}
struct Row { unsigned x, n, pick, lane0, lane1, lane2; };
constexpr Row rows[] = {
    {0xa5, 0x9, 0, 0xa5, 0x07, 0xa5},  // identity slices beside an int lane
    {0xa5, 0x9, 1, 0x01, 0x02, 0xff},  // int lanes take the element type
    {0xa5, 0x9, 2, 0x01, 0x02, 0x03},  // a Table state image of int lanes
    {0xa5, 0x9, 3, 0x09, 0xa5, 0x00},  // u4 lane zero-extends; list form
    {0x3c, 0xf, 0, 0x3c, 0x07, 0x3c},
    {0x3c, 0xf, 1, 0x01, 0x02, 0xff},
    {0x3c, 0xf, 2, 0x01, 0x02, 0x03},
    {0x3c, 0xf, 3, 0x0f, 0x3c, 0x00},
};

int main(int argc, char **argv) {
  require(argc == 2);
  const unsigned workers = std::strtoul(argv[1], nullptr, 10);
  require(workers == 1 || workers == 2);
  gfsim::WorkExecutor pool(workers);
  pyc_root root("lane-literals", &pool);
  root.x = known<8>(0); root.n = known<4>(0); root.pick = known<2>(0);
  root.pyc_7079635f636c6b = root.pyc_7079635f727374 = known<1>(0);
  root.Reset();
  root.Xfer();
  unsigned index = 0;
  for (const Row &row : rows) {
    root.x = known<8>(row.x); root.n = known<4>(row.n); root.pick = known<2>(row.pick);
    root.Work();
    const auto packed = root.result.packed();
    require(packed.isFullyKnown());
    const unsigned lane0 = gfsim::extract<8>(packed, 16).value().value();
    const unsigned lane1 = gfsim::extract<8>(packed, 8).value().value();
    const unsigned lane2 = gfsim::extract<8>(packed, 0).value().value();
    std::cout << "WORK " << index++ << ' ' << std::hex << lane0 << ' ' << lane1
              << ' ' << lane2 << std::dec << '\n';
    require(lane0 == row.lane0 && lane1 == row.lane1 && lane2 == row.lane2);
    root.Xfer();
  }
  std::cout << "PASS\n";
  return 0;
}
