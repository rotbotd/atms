# atms

A small assumption-based truth maintenance system, after Johan de Kleer's
"An Assumption-based TMS" (Artificial Intelligence 28, 1986). One Python file,
no dependencies.

Lynn asked for "something that believes two incompatible things for documented
reasons." This is it.

## what it does

You declare assumptions, and rules of the form "if these nodes hold, this node
holds, because of this informant." For every node, the ATMS keeps a **label**:
the smallest sets of assumptions under which you can derive it. Two nodes that
contradict each other can both have labels, because they hold under different
assumptions. If you derive the contradiction node `⊥` under some set of
assumptions, that set becomes a **nogood**. The ATMS removes it, and every
larger set containing it, from every label. It never re-runs your rules to do
this.

```python
from atms import ATMS

t = ATMS()
t.assume("battery dead")
t.assume("starter broken")
t.justify("jump-start fixes it", ["battery dead"], "mechanic: dead batteries jump-start")
t.justify("jump-start won't fix it", ["starter broken"], "mechanic: jumping can't turn a dead starter")
t.contradiction(["jump-start fixes it", "jump-start won't fix it"], "they can't both be true")

t.label("jump-start fixes it")      # {frozenset({'battery dead'})}
t.label("jump-start won't fix it")  # {frozenset({'starter broken'})}
t.nogoods                           # {frozenset({'battery dead', 'starter broken'})}

t.explain("jump-start fixes it", {"battery dead"})
# {'node': 'jump-start fixes it', 'because': 'mechanic: dead batteries jump-start',
#  'from': [{'node': 'battery dead', 'because': 'assumed'}]}

t.premise("headlights work", "observed tonight")
t.contradiction(["battery dead", "headlights work"], "a dead battery can't light headlights")
t.label("jump-start fixes it")      # set(): nothing left to believe it under
```

`nix run .#demo` runs this example.

## how it's checked

`nix flake check` runs the tests. The main test builds 1,200 random rule
networks. It adds the assumptions, premises and rules to the ATMS in a random
order. Then it compares every label and the nogood set against a brute-force
answer: for every subset of assumptions, forward-chain the rules to a fixpoint
and see what gets derived. So the labels are checked to be:

- **sound**: every set in a label really derives the node,
- **complete**: every consistent set that derives the node contains some set in the label,
- **minimal**: no set in a label contains another one, and
- **consistent**: no set in a label contains a nogood,

and none of these depend on the order the facts arrived in. Half the networks
are dense, with many alternative derivations, so about 300 labels have more
than one set in them.

A second, independent oracle comes from Lynn's review of the first version. It
computes its antichains itself rather than calling this library's `minimize`,
and it checks the labels after every single insertion: 2,500 networks, over
20,000 intermediate states.

Another test checks that every explanation uses only real justifications and
never explains a node by a chain that loops back to itself, including when the
rules themselves are cyclic.

I also broke the code on purpose twelve ways: no label minimization, no nogood
minimization, no removal of nogood supersets from labels, no consistency
filter on new sets, no propagation to dependent rules, no rollback, the
whole original recursive version, the write-then-log undo log, undo by `pop`
instead of truncation, the old nesting shortcut at transaction entry,
consuming antecedents inside the transaction, and accepting `str` subclasses as
names. Each break made the tests fail.

## updates are all-or-nothing

The first version propagated labels recursively. Lynn found that a chain of 800
rules, with the assumption added last, ran out of Python stack halfway through.
Worse, the half-finished labels stayed queryable: with a contradiction at the
far end of the chain, `holds_in('n0', {'A'})` still said yes, although the rules
on record derive a contradiction from A. A retry then did nothing.

Now propagation uses an explicit worklist, so depth is limited by memory, not
the call stack. The tests run 5,000-rule chains, with and without a
contradiction at the far end, and explain a 5,000-step derivation. Every
mutation (`assume`, `justify`, `premise`, `contradiction`) also keeps an undo log.
If it fails partway for any reason, every change it made is reversed before
the exception propagates, so queries only ever see completed updates, and
retrying starts clean. A test injects a failure halfway through propagation
and checks both of those.

The log is write-ahead: each undo record is registered *before* the write it
guards, and restores the old state by value (an old label, an old list length
to truncate to), so it's correct whether or not that write happened. Lynn's
second review found that the first undo log wrote first and logged second, so
a failure between the two left a label behind with no justification for it.
A fault sweep now fails at every undo registration in five scenarios, both
just before and just after the record is appended (72 injected failures).
Each time, the whole state (nodes, labels, assumption flags, justification
and consumer lists, nogoods) must equal the state before the call, and a retry
must end exactly where a clean run ends.

Lynn's third review found a window at the very start of a transaction: the
"transaction active" marker was set before the `try` that cleans it up. An
interrupt between the two left a stale marker behind. Later, unrelated calls
mistook it for an enclosing transaction and ran with no rollback at all. Now no
mutator calls another, so there's no nesting to detect, and each call binds its
own fresh log inside the `try`. A stale marker is just overwritten by the next
call. A second sweep interrupts at every single line executed inside
`atms.py` during the five scenarios (743 points). After each interrupt, the
state must be either untouched or the completed update, and a later,
separate update that fails must still roll back.

Lynn's fourth review found that caller code could still run *inside* an
update. `justify` turned its antecedents into a tuple after the transaction had
started, so a generator could call `assume` mid-update. The inner call
replaced the outer undo log, and the outer update then wrote with no log at
all. So there's an input contract now: `justify` consumes the antecedents into
a tuple, and every name and the informant must be exactly `str`, all *before*
the transaction starts. A generator's side effects become their own completed
calls, and a `str` subclass can't run its own `__hash__` or `__eq__` mid-update,
because it's rejected with a `TypeError` before anything changes.

What rollback can't promise:

- No reentry from outside the arguments. The input contract keeps caller code
  that arrives *through the arguments* out of an update. But a Python signal
  handler (say, for SIGALRM) runs between bytecodes, and if it mutates the same
  ATMS mid-update, it re-enters. So does code that monkeypatches the class. Don't
  mutate one ATMS from a signal handler or another thread.
- It assumes the undo records themselves run. If a second interrupt or
  allocation failure hits *during* rollback, the state can be left partly
  restored, and nothing detects that.
- An interrupt during the final cleanup, after the work is done, still
  raises. The update has then fully committed even though the call raised.
  The state is consistent, but a caller that retries would add the rule twice.
  (Rules are idempotent for labels, but the duplicate justification is kept.)

## limits

- Rules are Horn clauses only: no negation and no disjunction. De Kleer's
  extensions for choosing among alternatives aren't here.
- Label computation takes the cartesian product of the antecedents' labels,
  which is exponential in the worst case. That's fine for small networks; I
  haven't measured it on large ones.
- You can't retract a rule or an assumption once it's added. Only nogoods take
  beliefs away.
- It tracks *why* something is believed. It doesn't detect when an external
  cached result has gone stale. Those are different jobs.
- I built this from my understanding of de Kleer's design, and I didn't
  re-read the paper first. Lynn has since compared it with §§4.1–4.7 of the
  paper and found that the label computation follows the same basic shape:
  cartesian product of antecedent labels, removing subsumed and inconsistent
  sets, propagating changes, pruning nogood supersets. Nobody has compared it
  with the rest of the paper or with its optimized algorithm.
- `explain()` returns nested dicts. It builds them without recursion, but very
  deep ones are too deep for Python's recursive tools such as `==` or
  `json.dumps`.
