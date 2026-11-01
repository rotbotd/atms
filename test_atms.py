import random
import unittest
from itertools import combinations

from atms import ATMS, minimize


def oracle(assumptions, premises, rules):
    """Brute force over every assumption subset: forward-chain to a fixpoint.

    Returns (labels, nogoods) as the ATMS should compute them: for each node,
    the minimal consistent subsets under which it is derivable, and the minimal
    subsets that derive the contradiction.
    """
    derives = {}
    subsets = [frozenset(c) for r in range(len(assumptions) + 1)
               for c in combinations(assumptions, r)]
    for s in subsets:
        known = set(s) | set(premises)
        changed = True
        while changed:
            changed = False
            for consequent, antecedents in rules:
                if consequent not in known and all(a in known for a in antecedents):
                    known.add(consequent)
                    changed = True
        derives[s] = known
    nogoods = minimize(s for s in subsets if ATMS.CONTRADICTION in derives[s])
    consistent = [s for s in subsets if not any(ng <= s for ng in nogoods)]
    nodes = set(assumptions) | set(premises) | {c for c, _ in rules} | {a for _, ants in rules for a in ants}
    labels = {n: minimize(s for s in consistent if n in derives[s]) for n in nodes}
    return labels, nogoods


def random_network(rng, dense=False):
    """Small random Horn networks. `dense` packs many alternative derivations
    onto few nodes, so labels with several minimal environments are common."""
    assumptions = [f"A{i}" for i in range(rng.randint(2, 5) if dense else rng.randint(1, 5))]
    derived = [f"n{i}" for i in range(rng.randint(1, 3) if dense else rng.randint(1, 6))]
    premises = [p for p in ["P0", "P1"] if rng.random() < (0.2 if dense else 0.4)]
    pool = assumptions + derived + premises
    rules = []
    for _ in range(rng.randint(4, 14) if dense else rng.randint(1, 12)):
        contradiction_weight = 1 if dense else 2
        consequent = rng.choice(derived * (3 if dense else 1) + [ATMS.CONTRADICTION] * contradiction_weight)
        size = rng.randint(1, 2) if dense else rng.randint(1, min(3, len(pool)))
        antecedents = tuple(rng.sample(pool, min(size, len(pool))))
        rules.append((consequent, antecedents))
    return assumptions, premises, rules


def build(assumptions, premises, rules, order):
    t = ATMS()
    steps = ([("assume", a) for a in assumptions] + [("premise", p) for p in premises]
             + [("rule", r) for r in rules])
    order.shuffle(steps)  # labels must not depend on the order facts arrive in
    for kind, x in steps:
        if kind == "assume":
            t.assume(x)
        elif kind == "premise":
            t.premise(x)
        else:
            t.justify(x[0], x[1], "random rule")
    return t


class OracleTest(unittest.TestCase):
    def test_labels_and_nogoods_match_brute_force(self):
        rng = random.Random(20261101)
        for case in range(1200):
            assumptions, premises, rules = random_network(rng, dense=case % 2 == 1)
            t = build(assumptions, premises, rules, random.Random(case))
            labels, nogoods = oracle(assumptions, premises, rules)
            with self.subTest(case=case, rules=rules):
                self.assertEqual(t.nogoods, nogoods)
                for n, expected in labels.items():
                    if n == ATMS.CONTRADICTION:
                        continue
                    self.assertEqual(t.label(n), expected, n)

    def test_explanations_are_well_founded_and_valid(self):
        rng = random.Random(7)
        for case in range(600):
            assumptions, premises, rules = random_network(rng, dense=case % 2 == 1)
            t = build(assumptions, premises, rules, random.Random(case))
            for name, node in t.nodes.items():
                for env in node.label:
                    tree = t.explain(name, env)
                    self.assertTrue(self._valid(t, tree, env, set()), (name, env, tree))

    def _valid(self, t, tree, env, path):
        name = tree["node"]
        if name in path:
            return False  # circular explanation
        if tree["because"] == "assumed":
            return name in env and t.nodes[name].is_assumption
        children = [c["node"] for c in tree["from"]]
        if not any(j.antecedents == tuple(children) and j.informant == tree["because"]
                   for j in t.nodes[name].justifications):
            return False
        return all(self._valid(t, c, env, path | {name}) for c in tree["from"])


class CarTest(unittest.TestCase):
    """Two incompatible beliefs, held at once, each for a documented reason."""

    def setUp(self):
        t = ATMS()
        t.assume("battery dead")
        t.assume("starter broken")
        t.justify("jump-start fixes it", ["battery dead"], "mechanic: dead batteries jump-start")
        t.justify("jump-start won't fix it", ["starter broken"], "mechanic: jumping can't turn a dead starter")
        t.contradiction(["jump-start fixes it", "jump-start won't fix it"], "they can't both be true")
        self.t = t

    def test_believes_two_incompatible_things(self):
        self.assertEqual(self.t.label("jump-start fixes it"), {frozenset({"battery dead"})})
        self.assertEqual(self.t.label("jump-start won't fix it"), {frozenset({"starter broken"})})
        self.assertEqual(self.t.nogoods, {frozenset({"battery dead", "starter broken"})})
        self.assertFalse(self.t.holds_in("jump-start fixes it", {"battery dead", "starter broken"}))

    def test_documented_reasons(self):
        self.assertEqual(self.t.explain("jump-start fixes it", {"battery dead"}), {
            "node": "jump-start fixes it",
            "because": "mechanic: dead batteries jump-start",
            "from": [{"node": "battery dead", "because": "assumed"}],
        })

    def test_new_evidence_retracts_without_recomputation(self):
        self.t.premise("headlights work", "observed tonight")
        self.t.contradiction(["battery dead", "headlights work"], "a dead battery can't light headlights")
        self.assertIn(frozenset({"battery dead"}), self.t.nogoods)
        self.assertEqual(self.t.label("jump-start fixes it"), set())
        self.assertEqual(self.t.label("jump-start won't fix it"), {frozenset({"starter broken"})})
        with self.assertRaises(ValueError):
            self.t.explain("jump-start fixes it", {"battery dead"})


class EdgeTest(unittest.TestCase):
    def test_cycles_do_not_produce_circular_explanations(self):
        t = ATMS()
        t.assume("A")
        t.justify("x", ["y"], "y implies x")
        t.justify("y", ["x"], "x implies y")
        t.justify("x", ["A"], "A implies x")
        self.assertEqual(t.label("y"), {frozenset({"A"})})
        self.assertEqual(t.explain("y", {"A"}), {
            "node": "y", "because": "x implies y",
            "from": [{"node": "x", "because": "A implies x",
                      "from": [{"node": "A", "because": "assumed"}]}]})

    def test_premise_holds_everywhere_and_minimality(self):
        t = ATMS()
        t.assume("A")
        t.assume("B")
        t.justify("g", ["A", "B"], "both")
        t.justify("g", ["A"], "A alone suffices")
        self.assertEqual(t.label("g"), {frozenset({"A"})})
        t.premise("g", "known outright")
        self.assertEqual(t.label("g"), {frozenset()})

    def test_contradiction_is_not_an_assumption(self):
        with self.assertRaises(ValueError):
            ATMS().assume(ATMS.CONTRADICTION)


class DeepAndFailureTest(unittest.TestCase):
    """Regressions from Lynn's review of a38de44: recursive propagation hit the
    stack limit on an 800-node chain and left partial labels queryable."""

    N = 5000

    def chain(self, n, contradiction_at_end=False):
        t = ATMS()
        for i in range(n):
            t.justify(f"n{i}", ["A" if i == 0 else f"n{i-1}"], "chain")
        if contradiction_at_end:
            t.contradiction([f"n{n-1}"], "the chain cannot hold")
        t.assume("A")  # late: every label in the chain changes in one update
        return t

    def test_deep_chain_propagates_completely(self):
        t = self.chain(self.N)
        self.assertEqual(t.label(f"n{self.N-1}"), {frozenset({"A"})})

    def test_far_contradiction_reaches_the_start(self):
        t = self.chain(self.N, contradiction_at_end=True)
        self.assertEqual(t.nogoods, {frozenset({"A"})})
        self.assertFalse(t.holds_in("n0", {"A"}))
        self.assertEqual(t.label("n0"), set())

    def test_deep_explanation(self):
        t = self.chain(self.N)
        tree, depth = t.explain(f"n{self.N-1}", {"A"}), 0
        while "from" in tree:  # walk it iteratively; == on it would recurse
            (tree,), depth = tree["from"], depth + 1
        self.assertEqual((tree["node"], tree["because"], depth), ("A", "assumed", self.N))

    def test_failed_update_rolls_back_and_retry_completes(self):
        t = ATMS()
        for i in range(50):
            t.justify(f"n{i}", ["A" if i == 0 else f"n{i-1}"], "chain")
        t.contradiction(["n49"], "the chain cannot hold")
        before = (dict((k, set(v.label)) for k, v in t.nodes.items()), set(t.nogoods),
                  {k: len(v.justifications) for k, v in t.nodes.items()})

        real, calls = ATMS._candidates, [0]
        def failing(self, j):
            calls[0] += 1
            if calls[0] == 25:
                raise MemoryError("injected halfway through propagation")
            return real(self, j)
        ATMS._candidates = failing
        try:
            with self.assertRaises(MemoryError):
                t.assume("A")
        finally:
            ATMS._candidates = real

        after = (dict((k, set(v.label)) for k, v in t.nodes.items()), set(t.nogoods),
                 {k: len(v.justifications) for k, v in t.nodes.items()})
        self.assertEqual(after, before)  # nothing half-done is visible
        self.assertFalse(t.holds_in("n0", {"A"}))
        t.assume("A")  # the retry does the whole job
        self.assertEqual(t.nogoods, {frozenset({"A"})})


class LynnIndependentOracleTest(unittest.TestCase):
    """Lynn's independent check (review of a38de44), adopted with credit.

    Its oracle computes antichains with strict subsets itself instead of
    calling the implementation's `minimize`, and it checks after every
    insertion prefix, with empty antecedents, assumptions that are also
    derived, repeated antecedents, and ⊥ as an antecedent.
    """

    @staticmethod
    def brute(assumptions, rules, names):
        subsets = [frozenset(s) for n in range(len(assumptions) + 1)
                   for s in combinations(sorted(assumptions), n)]
        closures = {}
        for s in subsets:
            known = set(s)
            while True:
                nxt = known | {c for c, ants in rules if set(ants) <= known}
                if nxt == known:
                    break
                known = nxt
            closures[s] = known
        raw_bad = {s for s in subsets if ATMS.CONTRADICTION in closures[s]}
        bad = {s for s in raw_bad if not any(t < s for t in raw_bad)}
        labels = {}
        for name in names:
            supports = {s for s in subsets if name in closures[s] and s not in raw_bad}
            labels[name] = {s for s in supports if not any(t < s for t in supports)}
        return labels, bad

    def test_every_prefix_matches(self):
        rng = random.Random(2026110103)
        names = ["A", "B", "x", "y", ATMS.CONTRADICTION]
        for case in range(2500):
            steps = [("assume", a) for a in names[:-1] if rng.random() < .4]
            steps += [("rule", (rng.choice(names), tuple(rng.choices(names, k=rng.randrange(4)))))
                      for _ in range(rng.randrange(1, 15))]
            rng.shuffle(steps)
            t, assumptions, rules = ATMS(), set(), []
            for kind, payload in steps:
                if kind == "assume":
                    if payload == ATMS.CONTRADICTION:
                        continue
                    assumptions.add(payload)
                    t.assume(payload)
                else:
                    rules.append(payload)
                    t.justify(payload[0], payload[1], "independent test")
                expected, bad = self.brute(assumptions, rules, names)
                self.assertEqual(t.nogoods, bad, (case, steps))
                for name in t.nodes:
                    if name != ATMS.CONTRADICTION:
                        self.assertEqual(t.label(name), expected[name], (case, name, steps))


if __name__ == "__main__":
    unittest.main()
