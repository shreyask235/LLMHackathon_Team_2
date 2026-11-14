"""Order state and all money math. Gemini never does arithmetic; it calls these."""
from decimal import Decimal, ROUND_HALF_UP
import itertools

from .menus import MENUS, find_item, find_restaurant

TAX_RATE = Decimal("0.0825")
DELIVERY_FEE = Decimal("4.99")
FREE_OVER = Decimal("50.00")
PAY_LINK = "https://pay.334foodnow.example/o/{num}"  # placeholder, not a real payment page

_order_numbers = itertools.count(1042)


def money(x):
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fmt(x):
    return f"${money(x):.2f}"


class Order:
    def __init__(self):
        # {restaurant: [{"name", "price", "qty", "notes": [str]}]} - one order per restaurant
        self.restaurants = {}
        self.customer = {"name": "", "phone": "", "address": ""}
        self.number = None
        self.status = "open"  # open -> confirmed -> paid -> ready -> delivered
        self.ready = set()

    # ---- cart -------------------------------------------------------------
    def add_item(self, restaurant, item, quantity=1, note=""):
        if self.status != "open":
            return {"ok": False, "error": "Order is already confirmed; it can't be changed."}
        r = find_restaurant(restaurant)
        if not r:
            return {"ok": False, "error": f"No restaurant '{restaurant}'. Options: {list(MENUS)}"}
        m = find_item(r, item)
        if not m:
            return {"ok": False, "error": f"'{item}' is not on the {r} menu.",
                    "menu": [i["name"] for i in MENUS[r]]}
        try:
            qty = int(float(quantity or 1))
        except (TypeError, ValueError):
            return {"ok": False, "error": "Quantity must be a whole number."}
        if qty < 1:
            return {"ok": False, "error": "Quantity must be at least 1."}
        lines = self.restaurants.setdefault(r, [])  # same restaurant -> same order
        for line in lines:
            if line["name"] == m["name"]:
                line["qty"] += qty
                if note:
                    line["notes"].append(note)
                break
        else:
            lines.append({"name": m["name"], "price": m["price"], "qty": qty,
                          "notes": [note] if note else []})
        return {"ok": True, "added": f"{qty} x {m['name']} ({r})", "totals": self.totals()}

    def remove_item(self, restaurant, item, quantity=0):
        if self.status != "open":
            return {"ok": False, "error": "Order is already confirmed; it can't be changed."}
        r = find_restaurant(restaurant)
        lines = self.restaurants.get(r or "", [])
        m = find_item(r, item) if r else None
        for line in lines:
            if m and line["name"] == m["name"]:
                try:
                    q = int(float(quantity or 0))
                except (TypeError, ValueError):
                    q = 0
                if q <= 0 or q >= line["qty"]:
                    q = line["qty"]
                    lines.remove(line)
                else:
                    line["qty"] -= q
                if not lines:
                    del self.restaurants[r]
                return {"ok": True, "removed": f"{q} x {line['name']}",
                        "left_in_order": line["qty"] if line in lines else 0, "totals": self.totals()}
        return {"ok": False, "error": f"'{item}' is not in the order."}

    # ---- math -------------------------------------------------------------
    def subtotal(self):
        return sum((money(l["price"]) * l["qty"] for ls in self.restaurants.values() for l in ls),
                   Decimal("0.00"))

    def restaurant_total(self, r):
        return sum((money(l["price"]) * l["qty"] for l in self.restaurants[r]), Decimal("0.00"))

    def totals(self):
        sub = self.subtotal()
        free = sub > FREE_OVER
        delivery = Decimal("0.00") if free or sub == 0 else DELIVERY_FEE
        tax = money(sub * TAX_RATE)
        out = {
            "subtotal": f"{sub:.2f}", "tax": f"{tax:.2f}", "tax_rate": "8.25%",
            "delivery": "FREE" if free else f"{delivery:.2f}",
            "total": f"{money(sub + tax + delivery):.2f}", "free_delivery": free,
        }
        if not free and sub > 0:
            # Free delivery needs the subtotal to be OVER $50, so one cent more than the gap.
            needed = FREE_OVER - sub + Decimal("0.01")
            out["amount_needed_for_free_delivery"] = f"{needed:.2f}"
            out["suggested_item"] = self._suggest(needed)
        return out

    def _suggest(self, needed):
        """Cheapest single item that gets the subtotal over $50 (prefer restaurants already ordered)."""
        candidates = []
        for r, items in MENUS.items():
            for it in items:
                if money(it["price"]) >= needed:
                    candidates.append((r not in self.restaurants, money(it["price"]), r, it["name"]))
        if not candidates:  # nothing alone is enough: suggest the priciest item
            r, it = max(((r, it) for r, its in MENUS.items() for it in its), key=lambda x: x[1]["price"])
            return {"restaurant": r, "item": it["name"], "price": f"{it['price']:.2f}",
                    "note": "This item alone is NOT enough for free delivery; don't say it is."}
        candidates.sort(key=lambda c: (c[1], c[0]))
        _, price, r, name = candidates[0]
        return {"restaurant": r, "item": name, "price": f"{price:.2f}"}

    # ---- checkout ---------------------------------------------------------
    def set_customer(self, name="", phone="", address=""):
        for k, v in (("name", name), ("phone", phone), ("address", address)):
            if v:
                self.customer[k] = v.strip()
        missing = [k for k, v in self.customer.items() if not v]
        return {"ok": True, "customer": self.customer, "missing": missing}

    def summary(self):
        return {"restaurants": {r: [dict(l) for l in ls] for r, ls in self.restaurants.items()},
                "customer": self.customer, "totals": self.totals(), "status": self.status,
                "order_number": self.number}

    def confirm(self):
        if not self.restaurants:
            return {"ok": False, "error": "The order is empty."}
        missing = [k for k, v in self.customer.items() if not v]
        if missing:
            return {"ok": False, "error": f"Missing customer details: {missing}"}
        if self.status == "open":
            self.number = next(_order_numbers)
            self.status = "confirmed"
        t = self.totals()
        pay_text = (f"Thanks {self.customer['name']}! Your 334-FOOD-NOW order #{self.number} "
                    f"comes to ${t['total']}. Pay securely here: {PAY_LINK.format(num=self.number)} "
                    f"(we never ask for card details by phone or chat).")
        return {"ok": True, "order_number": self.number, "pay_link_text": pay_text}

    def line_text(self, line):
        note = f" ({', '.join(line['notes'])})" if line["notes"] else ""
        return f"{line['qty']} {line['name']}{note}"

    def group_text(self):
        t = self.totals()
        c = self.customer
        lines = [f"334-FOOD-NOW Order #{self.number} ({'PAID' if self.status != 'confirmed' else 'AWAITING PAYMENT'})",
                 f"Customer: {c['name']}, {c['phone']}",
                 f"Deliver to: {c['address']}"]
        for r, ls in self.restaurants.items():
            lines.append(f"{r}: {', '.join(self.line_text(l) for l in ls)}, {fmt(self.restaurant_total(r))}")
        delivery = "Delivery FREE" if t["free_delivery"] else f"Delivery ${t['delivery']}"
        lines.append(f"Subtotal ${t['subtotal']} | Tax ${t['tax']} | {delivery} | Total ${t['total']}")
        lines.append("Restaurants: reply READY when packed.")
        return "\n".join(lines)

    def order_json(self):
        t = self.totals()
        return {
            "order_number": self.number, "status": self.status, "customer": self.customer,
            "restaurants": [
                {"restaurant": r,
                 "items": [{"item": l["name"], "quantity": l["qty"], "unit_price": f"{l['price']:.2f}",
                            "line_total": f"{money(l['price']) * l['qty']:.2f}",
                            "notes": ", ".join(l["notes"])} for l in ls],
                 "restaurant_subtotal": f"{self.restaurant_total(r):.2f}"}
                for r, ls in self.restaurants.items()],
            "totals": {k: t[k] for k in ("subtotal", "tax", "delivery", "total")},
        }
