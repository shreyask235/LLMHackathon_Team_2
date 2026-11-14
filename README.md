# 334-FOOD-NOW: One Call, Three Restaurants, One Delivery

A chat ordering agent that takes one combined order from up to three restaurants
(Indian, Italian, Mexican), answers menu questions, checks the free-delivery rule,
collects customer details, reads the order back, and produces a pay link, the order
JSON split by restaurant, and the group text for customer, restaurants and driver.

## How it works

- **Frontend:** Vite chat page (`index.html`, `src/`) with a live order panel.
- **Backend:** FastAPI (`server/app.py`) talking to Gemini `gemini-3.1-flash-lite` via `google-genai` (fastest model that answers on our key; falls back to 3.5-flash, 3.8-flash, 3.7-flash). Minimal thinking, 10 s per-request timeout, quota-limited models skipped for 60 s. Override with GEMINI_MODEL / GEMINI_TIMEOUT_MS in .env.
- **All math is in Python** (`server/order.py`), exposed to Gemini as tools:
  `get_menu`, `add_item`, `remove_item`, `get_totals`, `set_customer`, `confirm_order`.
  Gemini never computes prices, tax or delivery.
- **Menus:** `menus.json` in the project root if present, otherwise the starter menus in
  `server/menus.py`. Items not on the menu are rejected by `add_item`.

Rules: one order per restaurant per call (new items are merged in), tax 8.25%, delivery free
when the food subtotal is over $50, else $4.99 plus the amount still needed and one suggested
item. The pay link is a placeholder; the agent never asks for card details.

## Run

Needs Python 3.10+ and Node 18+.

```bash
pip install -r requirements.txt
npm install
cp .env.example .env   # then put your key after GEMINI_API_KEY=
```

Two terminals:

```bash
python -m uvicorn server.app:app --port 8003
```

```bash
npm run dev
```

Open http://localhost:5173.

The API key is read only from `.env`, which is in `.gitignore`. No keys are in the code.

## Test call

> Hi, can I get two chicken biryanis, one not spicy, and a penne alfredo? Is delivery free?

Subtotal $44.97, so delivery is $4.99 and the agent says $5.04 more is needed and suggests an item.
Then give a name, mobile number and address, say yes to the read-back, and the pay link,
group text and JSON appear in the side panel. The **Simulate payment / READY / DELIVERED**
buttons show the follow-up texts.

Example group text:

```
334-FOOD-NOW Order #1042 (PAID)
Customer: Priya, 555-0100
Deliver to: 12 Main St
Indian: 2 Chicken Biryani (1 mild), $29.98
Italian: 1 Penne Alfredo, $14.99
Subtotal $44.97 | Tax $3.71 | Delivery $4.99 | Total $53.67
Restaurants: reply READY when packed.
```

## Phone ordering (voice)

- **Real phone call:** `server/voice.py` is a Twilio voice webhook. Twilio does speech-to-text
  (`<Gather input="speech">`) and text-to-speech (`<Say>`, or Cartesia `<Play>` when
  `CARTESIA_API_KEY` is set). Each call gets its own agent session (same tools and rules as chat),
  the caller ID fills the phone number, slow Gemini turns get a "one moment" filler so Twilio never
  times out, and after confirmation the pay link is texted to the caller and the call ends.
  Run `python -m uvicorn server.app:app --port 8003`, expose it with
  `cloudflared tunnel --url http://localhost:8003`, then
  `python -m server.twilio_wire https://<tunnel>` points the number's voice webhook at it.
  Needs `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_NUMBER` in `.env`.
- **In the browser:** the **Call 334-FOOD-NOW** button (`src/call.js`) talks to the same agent
  with the browser's speech recognition and voice (Chrome/Edge), no phone number needed.
