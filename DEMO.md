# Demo script (about 2 minutes)

**Problem (one sentence):** Ordering from three different restaurants today means three apps, three fees and three drivers; 334-FOOD-NOW takes it all in one call and sends one driver.

**Live steps**
1. Open http://localhost:5173. Point at the three kitchens and the empty cart.
2. Click the first sample: "two chicken biryanis, one not spicy, and a penne alfredo. Is delivery free?"
   Show: cart split by restaurant, "1 mild" note, $44.97, progress bar, agent says "$5.04 more" and suggests one item.
3. Ask: "Is the paneer vegetarian? Is the biryani halal and how spicy? Do you have sushi?" Answers come only from the menu; no sushi.
4. "Add chicken tacos and a garlic naan" (naan joins the same Indian order, free delivery unlocks), then "drop the tacos" (rule rechecked, fee comes back).
5. "Add a margherita pizza. I'm Priya, 512-555-0142, 1042 Congress Ave." Agent reads the whole order back and waits.
6. "Yes." Show the pay-link text (no card details ever asked), the group text card and the order JSON split by restaurant.
7. Click Simulate payment, Restaurants READY, Driver DELIVERED to show the follow-up texts.
8. Optional: the "Call 334-FOOD-NOW" button (or the Twilio number) runs the same agent by voice.

Point out: all prices, tax and the $50 rule are Python tools, not the model; the key lives only in .env.

**What's next (one sentence):** Real menus and payments from the restaurants' POS, live driver tracking, and the phone line on streaming speech for faster calls.
