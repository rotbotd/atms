"""A small assumption-based truth maintenance system (after de Kleer, 1986).

Every node carries a *label*: the minimal, consistent sets of assumptions
(environments) under which it can be derived. Contradictory beliefs coexist
because each lives in its own environments. Deriving the contradiction node
under an environment records that environment as a *nogood* and removes it,
and every superset of it, from every label.

What this tracks: why a node is believed and under which assumptions.
What it does not track: whether some external cached computation is stale.
Justifications are monotone Horn clauses (antecedents -> consequent). There
is no negation-as-failure and no disjunction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import FrozenSet, Iterable

Env = FrozenSet[str]


def minimize(envs: Iterable[Env]) -> set[Env]:
    """Keep only the environments with no proper subset in the collection."""
    unique = sorted(set(envs), key=len)
    kept: list[Env] = []
    for env in unique:
        if not any(k <= env for k in kept):
            kept.append(env)
    return set(kept)


@dataclass(frozen=True)
class Justification:
    consequent: str
    antecedents: tuple[str, ...]
    informant: str  # the documented reason: who or what asserted this rule


@dataclass
class Node:
    name: str
    label: set[Env] = field(default_factory=set)
    is_assumption: bool = False
    justifications: list[Justification] = field(default_factory=list)  # concluding this node
    consumers: list[Justification] = field(default_factory=list)  # using this node


class ATMS:
    CONTRADICTION = "⊥"

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.nogoods: set[Env] = set()
        self.node(self.CONTRADICTION)

    # ---- construction -------------------------------------------------

    def node(self, name: str) -> Node:
        if name not in self.nodes:
            self.nodes[name] = Node(name)
        return self.nodes[name]

    def assume(self, name: str) -> Node:
        """Declare an assumption: it holds exactly in environments containing it."""
        n = self.node(name)
        if name == self.CONTRADICTION:
            raise ValueError("the contradiction cannot be an assumption")
        n.is_assumption = True
        self._add_envs(n, {frozenset({name})})
        return n

    def premise(self, name: str, informant: str = "premise") -> Node:
        """A node that holds unconditionally (in the empty environment)."""
        self.justify(name, [], informant)
        return self.nodes[name]

    def justify(self, consequent: str, antecedents: Iterable[str], informant: str) -> Justification:
        """Record: if all antecedents hold, the consequent holds, because `informant`."""
        j = Justification(consequent, tuple(antecedents), informant)
        self.node(consequent).justifications.append(j)
        for a in j.antecedents:
            self.node(a).consumers.append(j)
        self._fire(j)
        return j

    def contradiction(self, antecedents: Iterable[str], informant: str) -> Justification:
        """Record that these nodes cannot all hold together."""
        return self.justify(self.CONTRADICTION, antecedents, informant)

    # ---- label propagation --------------------------------------------

    def _consistent(self, env: Env) -> bool:
        return not any(ng <= env for ng in self.nogoods)

    def _fire(self, j: Justification) -> None:
        labels = [self.nodes[a].label for a in j.antecedents]
        if any(not label for label in labels):
            return
        candidates = {frozenset().union(*combo) for combo in product(*labels)}
        self._add_envs(self.nodes[j.consequent], candidates)

    def _add_envs(self, node: Node, envs: set[Env]) -> None:
        envs = {e for e in envs if self._consistent(e)}
        if node.name == self.CONTRADICTION:
            if envs:
                self._add_nogoods(envs)
            return
        new_label = minimize(node.label | envs)
        if new_label == node.label:
            return
        node.label = new_label
        for j in list(node.consumers):
            self._fire(j)

    def _add_nogoods(self, envs: set[Env]) -> None:
        merged = minimize(self.nogoods | envs)
        if merged == self.nogoods:
            return
        self.nogoods = merged
        for n in self.nodes.values():
            n.label = {e for e in n.label if self._consistent(e)}

    # ---- queries ------------------------------------------------------

    def label(self, name: str) -> set[Env]:
        return set(self.nodes[name].label)

    def holds_in(self, name: str, env: Iterable[str]) -> bool:
        """True iff `name` is derivable under `env` and `env` is consistent."""
        env = frozenset(env)
        return self._consistent(env) and any(e <= env for e in self.nodes[name].label)

    def explain(self, name: str, env: Iterable[str]) -> dict:
        """The documented reason `name` holds under `env`, as a justification tree.

        The tree is well-founded: each node is explained only by nodes derived
        strictly earlier in a forward-chaining pass over `env`, so cyclic
        justifications can never produce a circular explanation.
        Raises ValueError if `name` doesn't hold there.
        """
        env = frozenset(env)
        if not self.holds_in(name, env):
            raise ValueError(f"{name!r} does not hold in {sorted(env)}")
        rank, via = self._derivation(env)
        return self._tree(name, rank, via)

    def _derivation(self, env: Env) -> tuple[dict[str, int], dict[str, Justification]]:
        rank: dict[str, int] = {a: 0 for a in env if a in self.nodes and self.nodes[a].is_assumption}
        via: dict[str, Justification] = {}
        step = 0
        while True:
            step += 1
            fired = []
            for n in self.nodes.values():
                if n.name in rank:
                    continue
                for j in n.justifications:
                    if all(a in rank for a in j.antecedents):
                        fired.append((n.name, j))
                        break
            if not fired:
                return rank, via
            for name, j in fired:
                rank[name] = step
                via[name] = j

    def _tree(self, name: str, rank: dict[str, int], via: dict[str, Justification]) -> dict:
        if name not in via:
            return {"node": name, "because": "assumed"}
        j = via[name]
        return {"node": name, "because": j.informant,
                "from": [self._tree(a, rank, via) for a in j.antecedents]}
