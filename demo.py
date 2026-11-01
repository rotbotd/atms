"""The car that won't start: two incompatible beliefs, each with its reasons."""
import json

from atms import ATMS

t = ATMS()
t.assume("battery dead")
t.assume("starter broken")
t.justify("jump-start fixes it", ["battery dead"], "mechanic: dead batteries jump-start")
t.justify("jump-start won't fix it", ["starter broken"], "mechanic: jumping can't turn a dead starter")
t.contradiction(["jump-start fixes it", "jump-start won't fix it"], "they can't both be true")


def show(title):
    print(f"--- {title}")
    for name in ["jump-start fixes it", "jump-start won't fix it"]:
        print(f"{name!r:28} holds under {sorted(sorted(e) for e in t.label(name))}")
    print(f"{'nogoods':28} {sorted(sorted(e) for e in t.nogoods)}")


show("both believed, in different environments")
print(json.dumps(t.explain("jump-start fixes it", {"battery dead"}), indent=2))

t.premise("headlights work", "observed tonight")
t.contradiction(["battery dead", "headlights work"], "a dead battery can't light headlights")
show("after seeing the headlights work")
