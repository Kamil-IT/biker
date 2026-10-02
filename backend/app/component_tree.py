"""The flat component rows <-> nested BikeCategory tree, shared by bikes and equipment.

`bike_component` and `equipment_component` (TODO-042 / TODO-044) store the
category -> subcategory -> element -> spec tree as one row per spec, each
carrying its whole ancestry. `flatten_components` turns a tree into the column
dicts of those rows; `rebuild_components` regroups ordered rows into the tree.
"""
from typing import Optional

from .schemas import BikeCategory, BikeSubcategory, ComponentElement, SpecItem


def rebuild_components(rows, element_links: bool = True) -> list[BikeCategory]:
    """Regroup flat component rows back into the nested response tree.

    `rows` must already be ordered by (component_order, element_order,
    spec_order) — the relationships declare that ordering. Grouping keys off
    those integers rather than off names, so two elements sharing a name inside
    one subcategory stay distinct. A row whose spec_key is NULL contributes an
    element with no specs, which is how `specs: []` round-trips. An element's
    `equipment_id` (TODO-042, bike rows only) comes from its first row. An
    `equipment_component` row's own `equipment_id` is its OWNER, not an element
    link: its callers pass `element_links=False`.
    """
    comps: dict[int, dict] = {}
    for r in rows:
        comp = comps.setdefault(r.component_order, {
            "category": r.category,
            "subcategory": r.subcategory,
            "elements": {},
        })
        element = comp["elements"].setdefault(r.element_order, {
            "name": r.element_name,
            "description": r.element_description or "",
            "specs": [],
            "equipment_id": getattr(r, "equipment_id", None) if element_links else None,
            # ISSUE-016: bike rows carry the flag; equipment rows have no column → True (schema default).
            "is_linkable": bool(getattr(r, "is_linkable", True)),
        })
        if r.spec_key is not None:
            element["specs"].append(SpecItem(key=r.spec_key, value=r.spec_value or ""))

    # Categories are contiguous runs of component_order, so walking in order and
    # grouping into a dict re-nests them with their original ordering intact.
    grouped: dict[str, list[BikeSubcategory]] = {}
    for comp_order in sorted(comps):
        comp = comps[comp_order]
        grouped.setdefault(comp["category"], []).append(BikeSubcategory(
            subcategory=comp["subcategory"],
            elements=[ComponentElement(**el) for _, el in sorted(comp["elements"].items())],
        ))
    return [
        BikeCategory(category=name, subcategories=subs)
        for name, subs in grouped.items()
    ]


def flatten_components(components: list[BikeCategory], include_linkable: bool = False) -> list[dict]:
    """The tree as one column dict per row (no parent FK, no equipment_id).

    `component_order` is a running counter across the tree so rows sharing a
    category stay contiguous; element_order and spec_order order the levels
    beneath it. An element with no specs still emits one row, with the spec_*
    columns None — that is what makes `specs: []` survive the round-trip.
    `include_linkable=True` adds each element's `is_linkable` (ISSUE-016) — only
    `bike_component` has that column, `equipment_component` does not.
    """
    rows: list[dict] = []
    comp_order = 0
    for category in components:
        for subcategory in category.subcategories:
            for e_idx, element in enumerate(subcategory.elements):
                base = dict(
                    category=category.category,
                    subcategory=subcategory.subcategory,
                    component_order=comp_order,
                    element_name=element.name,
                    element_description=element.description,
                    element_order=e_idx,
                )
                if include_linkable:
                    base["is_linkable"] = element.is_linkable
                specs: list[Optional[SpecItem]] = list(element.specs) or [None]
                for s_idx, spec in enumerate(specs):
                    rows.append({
                        **base,
                        "spec_key": spec.key if spec else None,
                        "spec_value": spec.value if spec else None,
                        "spec_order": s_idx if spec else None,
                    })
            comp_order += 1
    return rows


def has_components(components: list[BikeCategory]) -> bool:
    """True when the tree has at least one element (empty category shells do not count)."""
    return any(sub.elements for cat in components for sub in cat.subcategories)
