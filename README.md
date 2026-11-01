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

A second test checks that every explanation uses only real justifications and
never explains a node by a chain that loops back to itself, including when the
rules themselves are cyclic.

I also broke the code on purpose five ways: no label minimization, no nogood
minimization, no removal of nogood supersets from labels, no consistency
filter on new sets, and no propagation to dependent rules. Each break made the
tests fail.

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
  re-read the paper first. The tests check it against the definition of a
  label, not against the paper's algorithm or its terminology.
