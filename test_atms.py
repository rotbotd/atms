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


if __name__ == "__main__":
    unittest.main()
