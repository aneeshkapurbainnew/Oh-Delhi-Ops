# Changelog

Versions follow MAJOR.MINOR.PATCH (see CONTRIBUTING.md). The running version shows at the bottom of the app menu.

## 1.2.0 (2026-10-15)
- **Dry store items on the kitchen screen.** "Order for tomorrow" now lists every item on the station's list in two sections: *From vendors* (daily-order items, which go into tonight's WhatsApp orders) and *From the store* (dry store items, handed over from store stock). There's a search box for long lists.
- Dry store requests never appear in vendor orders. They show in *Give to stations* with a Store / Vendor tag and flow into pending like everything else. When the store doesn't have enough, the reason says so: "Only 2 left in store".
- Changing a dry store request after vendor orders are sent is not marked "changed late"; only vendor items are.

## 1.1.0 (2026-10-15)
- **WhatsApp groups:** each vendor can have a WhatsApp group name. Sending opens the share screen (on phones, the share sheet) with the message ready and shows which group to pick. The message is also copied.
- **Split orders:** one item can be ordered from several vendors in different quantities. The next plan starts with the last split's vendors and proportions.
- Pending reasons name every vendor involved, e.g. "Not received from Veg Kumar yet".
- The menu link "Items and settings" is now **Setup**. The app version shows in the menu and at `/api/health`.
- GitHub CI (tests, migrations, frontend and Docker builds), `deploy/update.sh` for one-command server updates and rollbacks, and an issue template.
- Deployment is AWS Lightsail with Docker Compose. Supabase and Render/Netlify files are removed; the optional Supabase photo storage code remains but is off by default.

## 1.0.0 (2026-10-15)
- Replaces the 27-sheet workbook. Prices (weekly-average and daily), purchases with bill photos and credit tracking, station issues, cooked-food wastage, any-day audits with 2% variance flags, month-end summary, min/par ordering, sales, discount/delivery/ads per brand × platform, expenses, P&L with PDF, reviews, owner dashboard.
- Daily ordering loop: chef requirements → vendor orders on WhatsApp → receiving → giving to stations → pending alerts; kitchen screen per station login.
- Built-in login (scrypt hashes, httpOnly session cookie), users managed in Setup.
- Seed template from the October 2026 workbook: 345 items, units, conversions, prices, 7 stations, 41 channels, 33 expense categories.
