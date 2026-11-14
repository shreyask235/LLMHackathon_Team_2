# 334-FOOD-NOW submission

One call, three restaurants, one delivery: a Gemini ordering agent (chat in the browser, plus a phone line) where all prices, tax and delivery math run in Python tools.

## Core checklist

| # | Requirement | Result |
|---|---|---|
| 1 | One combined order, up to 3 restaurants, one order per restaurant, new items added to it | PASS (garlic naan merged into the Indian order) |
| 2 | Menu questions (price, veg, halal, spice), never invents items | PASS (paneer veg, biryani halal + medium, "no sushi") |
| 3 | Free delivery over $50, else $4.99 + amount needed + one suggestion | PASS ($44.97 -> "$5.04 more", suggests Garlic Bread; rechecked after "drop the tacos") |
| 4 | Name, mobile, address, full read-back, clear yes | PASS |
| 5 | Pay-link text, never asks for card details | PASS |
| 6 | Order JSON by restaurant + group text to customer, restaurants, driver | PASS (below) |

## Test call transcript

**Customer:** Hi, can I get two chicken biryanis, one not spicy, and a penne alfredo? Is delivery free?

**Agent:** I've added those to your order! Your current subtotal is $44.97. Delivery is currently $4.99, but if you add just $5.04 more, you'll get free delivery. Would you like to add some Garlic Bread for $5.49 to reach that?

**Customer:** Is the paneer tikka vegetarian, and is the biryani halal and how spicy is it? Also do you have sushi?

**Agent:** The Paneer Tikka is vegetarian. The Chicken Biryani is halal and it is medium spicy (though I've noted one of yours to be mild). 

Unfortunately, we don't have any sushi on our menus. We have Indian, Italian, and Mexican options. Would you like to add anything else to your order?

**Customer:** Add chicken tacos from the Mexican place, and also one garlic naan to the Indian order.

**Agent:** Great! You've reached the threshold for free delivery. Your subtotal is now $60.93.

To finish up, could I please get your name, phone number, and delivery address?

**Customer:** Actually drop the tacos.

**Agent:** No problem, I've removed the tacos. Your subtotal is now $48.96. Since that's under $50, delivery is $4.99. If you add $1.05 more, you'll get free delivery again. Would you like to add anything else, or should we proceed with your details?

**Customer:** Add a margherita pizza. My name is Priya Shah, mobile 512-555-0142, address 1042 Congress Ave, Austin TX.

**Agent:** Thanks, Priya! I've added the Margherita Pizza and saved your details. Since your subtotal is now $62.95, your delivery is FREE.

Here is your order:
Indian:
- 2 x Chicken Biryani (1 mild)
- 1 x Garlic Naan

Italian:
- 1 x Penne Alfredo
- 1 x Margherita Pizza

Subtotal: $62.95
Tax: $5.19
Delivery: FREE
Total: $68.14

Does everything look correct?

**Customer:** Yes, that's all correct.

**Agent:** Thanks Priya Shah! Your 334-FOOD-NOW order #1042 comes to $68.14. Pay securely here: https://pay.334foodnow.example/o/1042 (we never ask for card details by phone or chat).

## Pay-link text

> Thanks Priya Shah! Your 334-FOOD-NOW order #1042 comes to $68.14. Pay securely here: https://pay.334foodnow.example/o/1042 (we never ask for card details by phone or chat).

## Group text (after payment)

```
334-FOOD-NOW Order #1042 (PAID)
Customer: Priya Shah, 512-555-0142
Deliver to: 1042 Congress Ave, Austin TX
Indian: 2 Chicken Biryani (1 mild), 1 Garlic Naan, $33.97
Italian: 1 Penne Alfredo, 1 Margherita Pizza, $28.98
Subtotal $62.95 | Tax $5.19 | Delivery FREE | Total $68.14
Restaurants: reply READY when packed.
```

## Follow-up texts (simulated)

- 334-FOOD-NOW: payment received for order #1042.
- Indian: READY
- Italian: READY
- 334-FOOD-NOW to driver: all 2 restaurant(s) READY for order #1042. Pick up: Indian, Italian. Deliver to 1042 Congress Ave, Austin TX.
- Driver: DELIVERED
- 334-FOOD-NOW to Priya Shah: order #1042 has been delivered. Enjoy!

## Order JSON (split by restaurant)

```json
{
  "order_number": 1042,
  "status": "delivered",
  "customer": {
    "name": "Priya Shah",
    "phone": "512-555-0142",
    "address": "1042 Congress Ave, Austin TX"
  },
  "restaurants": [
    {
      "restaurant": "Indian",
      "items": [
        {
          "item": "Chicken Biryani",
          "quantity": 2,
          "unit_price": "14.99",
          "line_total": "29.98",
          "notes": "1 mild"
        },
        {
          "item": "Garlic Naan",
          "quantity": 1,
          "unit_price": "3.99",
          "line_total": "3.99",
          "notes": ""
        }
      ],
      "restaurant_subtotal": "33.97"
    },
    {
      "restaurant": "Italian",
      "items": [
        {
          "item": "Penne Alfredo",
          "quantity": 1,
          "unit_price": "14.99",
          "line_total": "14.99",
          "notes": ""
        },
        {
          "item": "Margherita Pizza",
          "quantity": 1,
          "unit_price": "13.99",
          "line_total": "13.99",
          "notes": ""
        }
      ],
      "restaurant_subtotal": "28.98"
    }
  ],
  "totals": {
    "subtotal": "62.95",
    "tax": "5.19",
    "delivery": "FREE",
    "total": "68.14"
  }
}
```
