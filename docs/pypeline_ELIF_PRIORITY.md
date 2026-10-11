# Priority-preserving runtime `elif` lowering

Pypeline lowers eligible runtime `if`/`elif`/`else` chains as a single
priority selection, rather than as a sequence of nested binary conditional
merges. This avoids intermediate muxes for destinations written in multiple
branches and can reduce synthesis resource use substantially for large dispatch
logic.

For conditions `c0`, `c1`, ..., each branch selects only when no earlier
condition has matched: `take0 = c0`, `take1 = !c0 & c1`, etc. The final `else`
selects the remaining unmatched case. Each condition is elaborated from the
**pre-chain value state** so a later condition does not incorrectly observe
a write made in an earlier branch. Result selection uses the raw priority
predicates; clock enables separately combine the selected branch with its
parent's enable, preserving effects within disabled enclosing branches.

The optimization applies to two or more runtime arms with condition syntax
that can be safely elaborated without evaluation side effects. Compile-time
constant conditions and conditions containing calls, assignment expressions,
comprehensions, or other potentially effectful forms continue to use the
existing nested-`if` lowering. This is a conservative fallback, not a
requirement to rewrite such conditionals.

The regression `general_elif_priority_test.py` exercises overlapping
predicates, no-final-else chains, pre-chain reads after writes, repeated
assignments, scalar and struct-field writes, static array-element writes,
and nesting under a runtime-disabled parent. It is registered in the native
versus VHDL test suite and checks native/GHDL cycle-by-cycle equivalence.

Run with the repository's `native_vs_vhdl_sim_tests.py` harness, or directly
through `src/pypeline_sim_debug.py` using `--sim --comb --run all` with GHDL and
cocotb installed. The latter regression has been validated for 32 matching
cycles on the clean branch.
