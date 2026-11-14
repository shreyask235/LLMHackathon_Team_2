"""Menu loading. Uses menus.json in the project root if present, else the starter menus."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MENUS_FILE = ROOT / "menus.json"

# Starter menus from the challenge brief. Only facts given in the brief are listed;
# tags (veg/halal/spicy/nuts) are left out unless known, so the agent says "not listed"
# instead of inventing. Drop the real menus.json in the project root to replace these.
STARTER_MENUS = {
    "Indian": [
        {"name": "Chicken Biryani", "price": 14.99, "tags": []},
        {"name": "Paneer Tikka", "price": 12.99, "tags": ["veg"]},
        {"name": "Garlic Naan", "price": 3.99, "tags": ["veg"]},
    ],
    "Italian": [
        {"name": "Penne Alfredo", "price": 14.99, "tags": ["veg"]},
        {"name": "Margherita Pizza", "price": 13.99, "tags": ["veg"]},
    ],
    "Mexican": [
        {"name": "Chicken Tacos (3)", "price": 11.97, "tags": []},
        {"name": "Veggie Burrito", "price": 10.99, "tags": ["veg"]},
    ],
}


def _normalize(raw):
    """Accept a few plausible menus.json shapes and return {restaurant: [item dicts]}."""
    if isinstance(raw, dict) and "restaurants" in raw:
        raw = raw["restaurants"]
    menus = {}
    if isinstance(raw, list):  # [{"name": "Indian", "items": [...]}, ...]
        for r in raw:
            name = r.get("name") or r.get("cuisine") or r.get("restaurant")
            menus[name] = r.get("items") or r.get("menu") or []
    elif isinstance(raw, dict):  # {"Indian": [...]} or {"Indian": {"items": [...]}}
        for name, val in raw.items():
            menus[name] = val.get("items", val.get("menu", [])) if isinstance(val, dict) else val
    out = {}
    for name, items in menus.items():
        clean = []
        for it in items:
            item = dict(it)
            item["name"] = it.get("name") or it.get("item")
            item["price"] = float(it.get("price"))
            item.setdefault("tags", [])
            clean.append(item)
        out[name] = clean
    return out


def load_menus():
    if MENUS_FILE.exists():
        return _normalize(json.loads(MENUS_FILE.read_text(encoding="utf-8")))
    return STARTER_MENUS


MENUS = load_menus()


def find_restaurant(name):
    n = (name or "").strip().lower()
    if not n:  # "" is a substring of everything: an empty name must not match the first restaurant
        return None
    for r in MENUS:
        if r.lower() == n or n in r.lower() or r.lower() in n:
            return r
    return None


def find_item(restaurant, item_name):
    """Exact (case-insensitive) match first, then a loose match. None if not on the menu."""
    n = (item_name or "").strip().lower()
    items = MENUS.get(restaurant, [])
    for it in items:
        if it["name"].lower() == n:
            return it
    def base(s):
        return s.lower().split("(")[0].strip().rstrip("s")
    for it in items:
        if base(it["name"]) == base(n):
            return it
    # Misheard / shortened names ("biryani", "samosas"): accept only when exactly ONE item matches.
    if len(base(n)) >= 4:
        hits = [it for it in items if base(n) in it["name"].lower() or base(it["name"]) in n]
        if len(hits) == 1:
            return hits[0]
    return None
