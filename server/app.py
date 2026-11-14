"""334-FOOD-NOW chat server: FastAPI + Gemini (google-genai) with Python tools for all math."""
import copy
import json
import re
import time
import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from google import genai
from google.genai import types

from .menus import MENUS
from .order import Order

load_dotenv()  # reads GEMINI_API_KEY from .env (never committed)
# Fastest model that answers on this key goes first (measured 2026-11-14: 3.8/3.7-flash return 429 quota).
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
# Tried in order when a model is busy (503), rate limited (429), missing (404) or hangs (timeout).
MODELS = [MODEL] + [m for m in ("gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.7-flash")
                    if m != MODEL]
TIMEOUT_MS = int(os.getenv("GEMINI_TIMEOUT_MS", "10000"))  # per request (API minimum 10 s); was 20 s
SKIP_UNTIL = {}  # model -> time.time() until which it is skipped (quota / not found)
MAX_TURN_S = int(os.getenv("GEMINI_MAX_TURN_S", "40"))  # longest one customer turn may take, retries and waits included

app = FastAPI(title="334-FOOD-NOW")
_client = None
_client_key = None
SESSIONS = {}
LAST_GOOD = {"i": 0}  # index in MODELS of the last model that answered


def client():
    global _client, _client_key
    load_dotenv(override=True)  # pick up a key added to (or replaced in) .env after the server started
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if _client is None or key != _client_key:
        if not key:
            raise HTTPException(500, "GEMINI_API_KEY is missing. Put it in .env (see .env.example).")
        os.environ["GEMINI_API_KEY"] = key
        _client_key = key
        SKIP_UNTIL.clear()  # a new key has fresh quota
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                               http_options=types.HttpOptions(timeout=TIMEOUT_MS,
                                                             retry_options=types.HttpRetryOptions(attempts=1)))
    return _client


SYSTEM = f"""You are the friendly phone/chat ordering agent for 334-FOOD-NOW, a delivery service that
takes ONE combined order from up to three restaurants and sends ONE driver.

MENUS (the only items and prices that exist):
{json.dumps(MENUS, separators=(',', ':'))}

Rules:
- Never invent items, prices, or dietary facts. Answer price/vegetarian/halal/spice/nut questions only
  from the menu data above (fields: veg, halal, spice = none/mild/medium/hot, nuts). If a fact is not
  listed for an item, say the menu doesn't say and offer to check with the restaurant. Always mention
  nuts when an item contains them and the customer asks about allergies. If an item isn't on a menu, say so and offer what is.
- Each restaurant gets at most one order per call. New items for a restaurant are added to that same order.
- Never do math yourself. Use add_item / remove_item and read numbers from get_totals.
- Special requests go in the item's note, e.g. two biryanis with one not spicy -> add_item("Indian",
  "Chicken Biryani", 2, note="1 mild").
- Delivery is free only when the food subtotal is OVER $50, otherwise $4.99. Tax is 8.25%.
  Whenever delivery comes up, or after the order changes and it's not free, tell the customer the
  subtotal and the exact amount_needed_for_free_delivery from the totals ("$5.04 more") and suggest the suggested_item.
- Before checkout collect: name, mobile number, and delivery address (save with set_customer).
- Then read the WHOLE order back (each restaurant, items with notes, subtotal, tax, delivery, total)
  and ask for a clear yes (say "Delivery: FREE" when it is free). Only call confirm_order after an explicit yes.
- After confirm_order, give the customer the pay_link_text exactly. NEVER ask for card numbers or any
  payment details; payment only happens through the link.
- Keep replies short and conversational, like a phone call. Use plain text, no markdown tables.
"""


class ChatIn(BaseModel):
    session_id: str | None = None
    message: str


def new_session():
    order = Order()
    turn = {"cart_changed": False}  # reset by send_with_fallback at the start of every customer turn

    # Tool functions: google-genai reads the signatures/docstrings and calls them automatically.
    def get_menu(restaurant: str = "") -> dict:
        """Return menu items (name, price, tags) for one restaurant, or all restaurants if empty."""
        if restaurant:
            for r in MENUS:
                if r.lower() == restaurant.lower():
                    return {r: MENUS[r]}
        return MENUS

    def add_item(restaurant: str, item: str, quantity: int = 1, note: str = "") -> dict:
        """Add an item to that restaurant's order. note = special request, e.g. '1 mild'."""
        out = order.add_item(restaurant, item, quantity, note)
        turn["cart_changed"] |= bool(out.get("ok"))
        return out

    def remove_item(restaurant: str, item: str, quantity: int = 0) -> dict:
        """Remove an item. quantity 0 removes all of that item."""
        out = order.remove_item(restaurant, item, quantity)
        turn["cart_changed"] |= bool(out.get("ok"))
        return out

    def get_totals() -> dict:
        """Current order lines and exact subtotal, tax, delivery, total, and free-delivery gap."""
        return order.summary()

    def set_customer(name: str = "", phone: str = "", address: str = "") -> dict:
        """Save the customer's name, mobile number and delivery address. Returns what's still missing."""
        return order.set_customer(name, phone, address)

    def confirm_order() -> dict:
        """Call ONLY after the customer clearly said yes to the full read-back. Returns pay link text."""
        if turn["cart_changed"] and order.status == "open":
            # The cart changed in this same turn, so the customer can't have heard this order read back.
            return {"ok": False, "error": "The order just changed. Read the WHOLE updated order back "
                                          "(use get_totals) and get a clear yes before confirming."}
        return order.confirm()

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        tools=[get_menu, add_item, remove_item, get_totals, set_customer, confirm_order],
        temperature=0.3,
        thinking_config=types.ThinkingConfig(thinking_level="minimal"),  # much faster, tools still work
    )
    i = LAST_GOOD["i"]  # start new chats on the model that answered last
    return {"order": order, "config": config, "model_i": i, "turn": turn,
            "chat": client().chats.create(model=MODELS[i], config=config)}


def _next_model(i):
    """Next model index after i that is not cooling down (quota/not found). Falls back to i+1."""
    now = time.time()
    for k in range(1, len(MODELS) + 1):
        j = (i + k) % len(MODELS)
        if SKIP_UNTIL.get(MODELS[j], 0) <= now:
            return j
    return (i + 1) % len(MODELS)


def _fallback_reply(order):
    """Gemini sometimes returns no text after a tool call. Never show/speak a blank reply:
    say where the order stands, using only numbers from Python."""
    t = order.totals()
    if order.number:
        return order.confirm()["pay_link_text"]
    if not order.restaurants:
        return "Sorry, I missed that. What would you like to order?"
    items = "; ".join(f"{r}: {', '.join(order.line_text(l) for l in ls)}" for r, ls in order.restaurants.items())
    if t["free_delivery"]:
        tail = "Delivery is free."
    else:
        s = t["suggested_item"]
        tail = (f"Delivery is ${t['delivery']}; add ${t['amount_needed_for_free_delivery']} more for free "
                f"delivery, for example the {s['item']} at ${s['price']}.")
    return f"Okay, so far I have {items}. Your subtotal is ${t['subtotal']}. {tail} Anything else?"


def send_with_fallback(sess, message):
    """Send one message with a short per-request timeout. A hang gets one quick retry on the same
    model, then we move to the next model keeping history. Quota (429) / missing (404) models are
    skipped for a while so later turns don't waste time on them."""
    order = sess["order"]
    last = None
    retried = False
    deadline = time.time() + MAX_TURN_S
    for attempt in range(len(MODELS) + 8):
        snapshot = copy.deepcopy((order.restaurants, order.customer, order.status, order.number))
        model = MODELS[sess["model_i"]]
        t0 = time.time()
        if "turn" in sess:
            sess["turn"]["cart_changed"] = False
        try:
            text = (sess["chat"].send_message(message).text or "").strip()
            LAST_GOOD["i"] = sess["model_i"]
            print(f"[gemini] answered by {model} in {time.time() - t0:.1f}s", flush=True)
            return text or _fallback_reply(order)
        except Exception as e:
            last = e
            # undo any tool calls that ran during the failed turn so a retry can't double-add
            order.restaurants, order.customer, order.status, order.number = snapshot
            code = getattr(e, "code", None)
            msg = str(e).lower()
            kind = type(e).__name__.lower()
            hang = code == 504 or (code is None and ("timed out" in msg or "timeout" in msg or "timeout" in kind))
            # dropped connections (httpx ConnectError / ReadError / RemoteProtocolError) are retried too
            network = code is None and any(k in kind for k in ("connect", "protocol", "readerror", "network"))
            print(f"[gemini] {model} failed in {time.time() - t0:.1f}s ({code or type(e).__name__})", flush=True)
            if code not in (429, 500, 502, 503, 504, 404) and not hang and not network:
                raise
            if code == 404:
                SKIP_UNTIL[model] = time.time() + 3600
            elif code == 429:
                # Free tier: 15 requests/minute per model. The error says when to retry ("retry in 17.1s").
                # A used-up DAILY quota won't come back during a call, so that model is parked for an hour.
                m = re.search(r"retry in ([\d.]+)\s*s", msg)
                daily = "perday" in msg.replace(" ", "").replace("_", "")
                SKIP_UNTIL[model] = time.time() + (3600 if daily else min(float(m.group(1)) + 1, 60) if m else 60)
            if hang and not retried:
                retried = True  # hangs are random: one fresh try on the same model is usually instant
            else:
                retried = False
                sess["model_i"] = _next_model(sess["model_i"])
            wait = 0.3 if code == 503 else 0
            if code == 429 and all(SKIP_UNTIL.get(m, 0) > time.time() for m in MODELS):
                # every model is rate limited: wait for the first one to free up instead of giving up
                sess["model_i"] = min(range(len(MODELS)), key=lambda j: SKIP_UNTIL[MODELS[j]])
                wait = SKIP_UNTIL[MODELS[sess["model_i"]]] - time.time()
            sess["chat"] = client().chats.create(model=MODELS[sess["model_i"]], config=sess["config"],
                                                 history=sess["chat"].get_history())
            if time.time() + wait > deadline:
                break  # out of time (or quota gone for the day): report it, the order itself is kept
            if wait > 0:
                print(f"[gemini] waiting {wait:.1f}s for {MODELS[sess['model_i']]}", flush=True)
                time.sleep(wait)
    raise last


def state(sid):
    o = SESSIONS[sid]["order"]
    out = {"session_id": sid, "order": o.summary()}
    if o.number:
        out["order_json"] = o.order_json()
        out["group_text"] = o.group_text()
        out["pay_link_text"] = o.confirm()["pay_link_text"]
    return out


@app.post("/api/chat")
def chat(body: ChatIn):
    if not body.message.strip():
        raise HTTPException(400, "Type a message first.")
    sid = body.session_id if body.session_id in SESSIONS else str(uuid.uuid4())
    if sid not in SESSIONS:
        SESSIONS[sid] = new_session()
    try:
        reply = send_with_fallback(SESSIONS[sid], body.message[:2000])
    except HTTPException:
        raise
    except Exception as e:  # surface API errors to the UI instead of a blank 500
        print(f"[gemini] gave up: {e}", flush=True)
        code = getattr(e, "code", None)
        if code == 429 and "perday" in str(e).lower().replace(" ", "").replace("_", ""):
            raise HTTPException(502, "The Gemini key has used up its free daily quota. Put a new GEMINI_API_KEY "
                                     "in .env (it is picked up after a server restart).")
        if code in (429, 500, 502, 503, 504) or code is None:
            # the order is kept (failed turns are rolled back), so the customer can just resend
            raise HTTPException(502, "The assistant is busy right now. Your order is saved, please send that again.")
        raise HTTPException(502, f"Gemini error: {e}")
    return {"reply": reply, "model": MODELS[SESSIONS[sid]["model_i"]], **state(sid)}


@app.get("/api/state/{sid}")
def get_state(sid: str):
    if sid not in SESSIONS:
        raise HTTPException(404, "Unknown session")
    return state(sid)


@app.post("/api/simulate/{sid}/{event}")
def simulate(sid: str, event: str):
    """Demo only: pretend the customer paid, restaurants replied READY, driver DELIVERED."""
    if sid not in SESSIONS:
        raise HTTPException(404, "Unknown session")
    o = SESSIONS[sid]["order"]
    if not o.number:
        raise HTTPException(400, "Order not confirmed yet")
    msgs = []
    if event == "paid":
        o.status = "paid"
        msgs = [f"334-FOOD-NOW: payment received for order #{o.number}."]
    elif event == "ready":
        o.status = "ready"
        msgs = [f"{r}: READY" for r in o.restaurants]
        msgs.append(f"334-FOOD-NOW to driver: all {len(o.restaurants)} restaurant(s) READY for order #{o.number}. "
                    f"Pick up: {', '.join(o.restaurants)}. Deliver to {o.customer['address']}.")
    elif event == "delivered":
        o.status = "delivered"
        msgs = ["Driver: DELIVERED",
                f"334-FOOD-NOW to {o.customer['name']}: order #{o.number} has been delivered. Enjoy!"]
    else:
        raise HTTPException(400, "event must be paid, ready or delivered")
    return {"messages": msgs, **state(sid)}


# Phone ordering (Twilio voice webhook): /voice/incoming and /voice/turn, see server/voice.py
from .voice import router as _voice_router  # noqa: E402
app.include_router(_voice_router)
from .voice_stream import router as _voice_stream_router  # noqa: E402
app.include_router(_voice_stream_router)
