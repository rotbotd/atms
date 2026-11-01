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

from collections import deque
from dataclasses import dataclass, field
from functools import wraps
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


def _transactional(method):
    """Run a mutation all-or-nothing.

    Every state change made during the call is recorded in an undo log. If the
    call fails partway (any exception, including KeyboardInterrupt or
    MemoryError), the log is replayed backwards and the exception re-raised.
    Queries never see labels from an unfinished propagation, and retrying the
    call starts from a clean state. The cost is proportional to what the call
    changed, not to the size of the network. Nested calls share one log.
    """
    @wraps(method)
    def run(self, *args, **kwargs):
        if self._undo is not None:
            return method(self, *args, **kwargs)
        self._undo = []
        try:
            return method(self, *args, **kwargs)
        except BaseException:
            for undo in reversed(self._undo):
                undo()
            raise
        finally:
            self._undo = None
    return run


class ATMS:
    CONTRADICTION = "⊥"

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.nogoods: set[Env] = set()
        self._undo: list | None = None
        self.node(self.CONTRADICTION)

    # ---- construction -------------------------------------------------

    def node(self, name: str) -> Node:
        if name not in self.nodes:
            self._log(lambda: self.nodes.pop(name, None))
            self.nodes[name] = Node(name)
        return self.nodes[name]

    # Write-ahead: every write is preceded by an undo record that restores the
    # old state *by value*, so the record is correct whether or not the write
    # it guards ever happened. (Lynn found the write-then-log version could
    # fail between the two and leave an unrecorded label behind.)
    def _log(self, undo) -> None:
        if self._undo is not None:
            self._undo.append(undo)

    def _log_truncate(self, items: list) -> None:
        length = len(items)  # truncate, don't pop: pop would eat an older entry if the append never happened
        self._log(lambda: items.__delitem__(slice(length, None)))

    @_transactional
    def assume(self, name: str) -> Node:
        """Declare an assumption: it holds exactly in environments containing it."""
        n = self.node(name)
        if name == self.CONTRADICTION:
            raise ValueError("the contradiction cannot be an assumption")
        was = n.is_assumption
        self._log(lambda: setattr(n, "is_assumption", was))
        n.is_assumption = True
        self._propagate(n, {frozenset({name})})
        return n

    def premise(self, name: str, informant: str = "premise") -> Node:
        """A node that holds unconditionally (in the empty environment)."""
        self.justify(name, [], informant)
        return self.nodes[name]

    @_transactional
    def justify(self, consequent: str, antecedents: Iterable[str], informant: str) -> Justification:
        """Record: if all antecedents hold, the consequent holds, because `informant`."""
        j = Justification(consequent, tuple(antecedents), informant)
        target = self.node(consequent)
        self._log_truncate(target.justifications)
        target.justifications.append(j)
        for a in j.antecedents:
            source = self.node(a)
            self._log_truncate(source.consumers)
            source.consumers.append(j)
        self._propagate(None, set(), [j])
        return j

    def contradiction(self, antecedents: Iterable[str], informant: str) -> Justification:
        """Record that these nodes cannot all hold together."""
        return self.justify(self.CONTRADICTION, antecedents, informant)

    # ---- label propagation --------------------------------------------

    def _consistent(self, env: Env) -> bool:
        return not any(ng <= env for ng in self.nogoods)

    def _candidates(self, j: Justification) -> set[Env]:
        labels = [self.nodes[a].label for a in j.antecedents]
        if any(not label for label in labels):
            return set()
        return {frozenset().union(*combo) for combo in product(*labels)}

    def _propagate(self, node: Node | None, envs: set[Env], fire: list[Justification] = ()) -> None:
        """Add `envs` to `node`, then propagate with an explicit worklist.

        No recursion, so propagation depth is bounded by memory, not the call
        stack. A justification is fired against the labels current at the time
        it's popped, so a later, larger label is never lost to a stale snapshot.
        """
        queue: deque[Justification] = deque(fire)
        if node is not None:
            queue.extend(self._add_envs(node, envs))
        while queue:
            j = queue.popleft()
            queue.extend(self._add_envs(self.nodes[j.consequent], self._candidates(j)))

    def _add_envs(self, node: Node, envs: set[Env]) -> list[Justification]:
        """Merge envs into node's label; return the justifications to re-fire."""
        envs = {e for e in envs if self._consistent(e)}
        if node.name == self.CONTRADICTION:
            if envs:
                self._add_nogoods(envs)
            return []
        new_label = minimize(node.label | envs)
        if new_label == node.label:
            return []
        old = node.label
        self._log(lambda: setattr(node, "label", old))
        node.label = new_label
        return list(node.consumers)

    def _add_nogoods(self, envs: set[Env]) -> None:
        merged = minimize(self.nogoods | envs)
        if merged == self.nogoods:
            return
        old_nogoods = self.nogoods
        self._log(lambda: setattr(self, "nogoods", old_nogoods))
        self.nogoods = merged
        for n in self.nodes.values():
            kept = {e for e in n.label if self._consistent(e)}
            if kept != n.label:
                old = n.label
                self._log(lambda n=n, old=old: setattr(n, "label", old))
                n.label = kept

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
        """Build the explanation bottom-up, with no recursion, so depth is unbounded."""
        built: dict[str, dict] = {}
        for n in sorted(self._needed(name, via), key=lambda n: rank[n]):
            if n not in via:
                built[n] = {"node": n, "because": "assumed"}
            else:
                j = via[n]
                built[n] = {"node": n, "because": j.informant,
                            "from": [built[a] for a in j.antecedents]}
        return built[name]

    def _needed(self, name: str, via: dict[str, Justification]) -> set[str]:
        seen, stack = {name}, [name]
        while stack:
            j = via.get(stack.pop())
            for a in (j.antecedents if j else ()):
                if a not in seen:
                    seen.add(a)
                    stack.append(a)
        return seen
