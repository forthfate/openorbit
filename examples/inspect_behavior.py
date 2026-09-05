"""Inspect a public behavior definition without calling a model or process."""

from orbit import load_bundle, render_prompt

bundle = load_bundle("user-simulation")
print(bundle.definition["graph"])
print(render_prompt(bundle, "session_planner", persona="Example", memory="None", catalog="route:/"))
