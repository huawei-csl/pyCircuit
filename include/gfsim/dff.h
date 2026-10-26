// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include "gfsim/SimModule.h"
#include "gfsim/sampled_clock.h"

#include <string>
#include <utility>

namespace gfsim {

// This is the sole register state transition implementation. Both scalar
// modules and bulk owners pass plain state and borrowed pins to the same
// kernel. NoReset elaborates a register declared without a reset value: the
// sampled reset never loads init and a host Reset retains the committed value.
template <class T = Bits<1>, bool NoReset = false> struct dffe_kernel {
  struct Current {
    wire<T> q;
    bool clock = false;
  };
  struct Pending {
    wire<T> q;
    bool clock = false;
    bool valid = false;
  };
  struct Inputs {
    const wire<Bits<1>> &clk, &rst, &en;
    const wire<T> &d, &init;
  };
  struct Outputs {
    wire<T> &q;
  };

  static void discard(const Current &current, Pending &pending) noexcept {
    pending.q = current.q;
    pending.clock = current.clock;
    pending.valid = false;
  }
  static void work(const Current &current, Inputs inputs, Pending &pending,
                   Outputs) {
    discard(current, pending);
    try {
      const auto clock =
          evaluateSampledClock(current.clock, inputs.clk, inputs.rst);
      if (clock.fault == SampledClockFault::UnknownClock)
        throw FourStateViolation("dffe clock must be known");
      // A register without reset still reports an unknown reset: the reset
      // policy is the root's, only its effect on this register is removed.
      if (clock.fault == SampledClockFault::UnknownReset)
        throw FourStateViolation("dffe reset must be known at posedge");
      pending.clock = clock.nextClock;
      pending.valid = true;
      if (!clock.rising)
        return;
      if (!NoReset && clock.resetActive) {
        pending.q = inputs.init;
        return;
      }
      if (!inputs.en.isFullyKnown())
        throw FourStateViolation("dffe enable must be known at posedge");
      if (inputs.en.value().toBool())
        pending.q = inputs.d;
    } catch (...) {
      discard(current, pending);
      throw;
    }
  }
  static void xfer(Current &current, Pending &pending,
                   Outputs outputs) noexcept {
    if (!pending.valid)
      return;
    current.q = pending.q;
    current.clock = pending.clock;
    outputs.q = current.q;
    discard(current, pending);
  }
  static void reset(const Current &current, Inputs inputs,
                    Pending &pending) noexcept {
    pending.q = NoReset ? current.q : inputs.init;
    pending.clock = false;
    pending.valid = true;
  }
};

template <class T = Bits<1>, bool NoReset = false> struct dff_kernel {
  using Enabled = dffe_kernel<T, NoReset>;
  using Current = typename Enabled::Current;
  using Pending = typename Enabled::Pending;
  struct Inputs {
    const wire<Bits<1>> &clk, &rst;
    const wire<T> &d, &init;
  };
  using Outputs = typename Enabled::Outputs;
  static void discard(const Current &current, Pending &pending) noexcept {
    Enabled::discard(current, pending);
  }
  static void work(const Current &current, Inputs inputs, Pending &pending,
                   Outputs outputs) {
    const auto enabled = wire<Bits<1>>::known(Bits<1>{1});
    Enabled::work(
        current, {inputs.clk, inputs.rst, enabled, inputs.d, inputs.init},
        pending, outputs);
  }
  static void xfer(Current &current, Pending &pending,
                   Outputs outputs) noexcept {
    Enabled::xfer(current, pending, outputs);
  }
  static void reset(const Current &current, Inputs inputs,
                    Pending &pending) noexcept {
    const auto enabled = wire<Bits<1>>::known(Bits<1>{1});
    Enabled::reset(
        current, {inputs.clk, inputs.rst, enabled, inputs.d, inputs.init},
        pending);
  }
};

template <class T = Bits<1>> class dffe final : public SimModule {
public:
  using Kernel = dffe_kernel<T>;
  explicit dffe(std::string name) : SimModule(std::move(name)) {}
  wire<Bits<1>> clk, rst, en;
  wire<T> d, init, q;
  void Work() override { Kernel::work(current_, pins(), pending_, {q}); }
  void Xfer() noexcept override { Kernel::xfer(current_, pending_, {q}); }
  void DiscardNext() noexcept override { Kernel::discard(current_, pending_); }
  void Reset() noexcept override { Kernel::reset(current_, pins(), pending_); }
  bool HasWork() const noexcept override { return true; }

private:
  typename Kernel::Inputs pins() const noexcept {
    return {clk, rst, en, d, init};
  }
  typename Kernel::Current current_;
  typename Kernel::Pending pending_;
};

template <class T = Bits<1>> class dff final : public SimModule {
public:
  using Kernel = dff_kernel<T>;
  explicit dff(std::string name) : SimModule(std::move(name)) {}
  wire<Bits<1>> clk, rst;
  wire<T> d, init, q;
  void Work() override { Kernel::work(current_, pins(), pending_, {q}); }
  void Xfer() noexcept override { Kernel::xfer(current_, pending_, {q}); }
  void DiscardNext() noexcept override { Kernel::discard(current_, pending_); }
  void Reset() noexcept override { Kernel::reset(current_, pins(), pending_); }
  bool HasWork() const noexcept override { return true; }

private:
  typename Kernel::Inputs pins() const noexcept { return {clk, rst, d, init}; }
  typename Kernel::Current current_;
  typename Kernel::Pending pending_;
};

} // namespace gfsim
