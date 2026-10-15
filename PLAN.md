# Oh Delhi Ops: development plan

Replaces `October2026InventorySheet.xlsx` (27 sheets) with a web app.
Stack: Vite + React frontend served by Caddy, FastAPI backend, Postgres, login built into the app, bill photos on the server disk. Everything runs on one AWS Lightsail server in Mumbai with Docker Compose (see README). Versions are tracked in git, with CI on GitHub.

## Phases

| Phase | Scope | Status |
|---|---|---|
| 1. Foundation and inventory | Master data (items, units, conversions, categories, stations, vendors), price lists (weekly-average and daily), purchase bills with vendor, bill no., payment status and photo, station issues, wastage, any-day audits and month-end audit, min/par stock | **Built** |
| 2. Finance and reporting | Daily sales, discounts / delivery / ads per brand × platform, expenses, monthly wage cost input (from Attendio), P&L with PDF export, owner dashboard | **Built** |
| 3. Reviews | Review log with assignment, status, resolution, and trends by station and brand | **Built** |
| 3b. Daily ordering and receiving | Chef requirements for tomorrow, vendor orders sent to WhatsApp groups (items can be split across vendors), receiving against the order, giving to stations, pending alerts, kitchen screen per station | **Built (v1.1.0)** |
| 3c. Station balance of cooked items | Each station records what it has left at the end of the day (gravies, marinades, prepped items) so carry-over is tracked and costed. Not in the original sheets. See "Backlog: cooked items balance" below. | Planned |
| 4. Petpooja and recipes | Petpooja sales import, dish → ingredient recipes, recipe costing, theoretical vs actual consumption | Next |
| 5. Multi-outlet and control | Outlet switcher (every table already carries `outlet_id`), roles, audit locking | Later |
| 6. Nice-to-haves | WhatsApp Business API (automatic sending and replies), Excel export of any screen, per-item min/par overrides, alert notifications | Later |

## Sheet → screen map

| Sheet(s) | Screen |
|---|---|
| Pricing, DailyPricing | Prices (Weekly-average tab, Daily tab) |
| Purchases | Purchases (bills) |
| Indian, Tandoor, Chinese, Conti, STAFFUT, Packaging, DAILYITEMS | Station issues, entered by chefs on the kitchen screen or by the store |
| Vegetable Ordering, Poultry Ordering | Daily orders (requirements → WhatsApp orders → receiving → giving to stations) |
| TotalConsumptionSheet | Station issues → month view, and the P&L |
| Week1/2/3AuditSheet, MonthlyAuditSheet | Audits (any date) + Month-end summary |
| MinimumStockSheet | Stock and ordering |
| WastageSheet | Wastage |
| SalesSheet | Sales and channel costs → Sales tab |
| DiscountSheet, DeliveryCostSheet, AdsCostSheet | Sales and channel costs → Discounts / Delivery / Ads tabs |
| ExpenseSheet | Expenses |
| P&L Sheet | P&L (with PDF) and Dashboard |
| WageSheet | Removed (payroll is in Attendio). Monthly wage total is entered on the P&L screen |
| ReviewsSheet | Reviews |

## Calculation rules (✔ = confirmed)

**Units.** Every item has a purchase unit, a consumption unit and a conversion ratio (consumption units per purchase unit; 1 when they are the same). Purchases are entered in purchase units. Issues, wastage and audit counts are in consumption units. Purchase quantity × ratio moves into stock.

**Weekly-average items** (the old `Pricing` sheet). The month has three periods: 1–10, 11–20, 21–end. A period's price is the average of manual prices entered for that period. If there are none, it is the average of purchase rates in that period. If there are none of those either, the previous period's price carries forward. The item's price for the whole month is the average of the three period prices.

**Daily items** (the old `DailyPricing` sheet). The price on a date is the manual price for that date, otherwise the average purchase rate that day, otherwise the most recent earlier price. Consumption is costed at that day's price. This fixes the old "divide by 31" average, which was wrong in 30-day months and was dragged down by zero days.

**Consumption price** = purchase price ÷ conversion ratio.

**Purchases update prices automatically.** Each bill line writes a price entry, so nobody has to maintain a separate pricing sheet. Manual prices still override.

**Audits (any date).** Counts are taken at the end of the audit date. For each item: opening = previous audit's closing; purchases and issues are summed from the day after the previous audit to the audit date; expected = opening + purchases − issued; variance = expected − counted (positive = shortage). The first audit should be of type *Opening count*, so opening stock starts at the count.
- ✔ An item left blank is *not counted*. It is excluded from variance and its expected stock carries forward as the next opening.
- ✔ Variance % = variance ÷ expected stock. Anything above **2%** is flagged; the threshold is editable in Setup → Settings. A negative expected stock (more issued than was available) is marked "check entries".
- Variance value = variance × consumption price on the audit date.

**Month-end audit.** One per month. It can only be closed after every other audit in that month is closed. The month-end summary works like the old MonthlyAuditSheet: opening = closing of the last audit before the month, movements for the whole month, actual = month-end count.

**Wastage.** ✔ Money wastage of cooked food (the old WastageSheet): dish, station, optional quantity and unit, reason, and the value in ₹. It does not move raw-material stock, and the full amount is added to COGS. Valuing wastage automatically from recipes comes with phase 4.

**Min / par stock.** Unchanged formula. With *m* = last calendar month's issues: minimum = m ÷ 4 × 1.25 and par = m ÷ 4 × 1.5. Current stock = last audit's closing + purchases − issues since. At or below minimum shows *Order now*; at or below par shows *Order*. The suggested quantity tops up to par and is shown in both consumption and purchase units.

**P&L.** Total gross = gross sale + complimentary. COGS = consumption cost + cooked-food wastage. Gross profit = net sales − COGS. Restaurant margin = gross profit − wage cost. EBITDA = margin − expenses − ads − delivery, shown in ₹ and as % of net sales. Food cost % = (Indian + Tandoor + Chinese + Conti) ÷ net sales. Gross cost % = (all stations) ÷ total gross.
- The expense list still contains "Delivery Cost" and "Ads Cost (Reelo)", which overlap with the Delivery and Ads tabs. Enter each cost in one place only, or deactivate those expense categories in Setup.

## Bugs in the workbook that the app removes
1. P&L wage cost was `#REF!`, so margin and EBITDA were overstated.
2. WastageSheet total rows summed each other (double/triple counting).
3. DailyPricing always divided by 31.
4. Audit/purchase periods (10-day) didn't match wastage/expense periods (7-day).
5. `#REF!` in MinimumStock (Nachos) and MonthlyAudit; MinimumStock's "Unit" column showed the conversion ratio.
6. Sprouts, Tori, Brinjal, Raddish, Lauki, Curry Leaves and Chinese Cabbage were audited but had no price. They are in the template now with price 0 and are flagged on the Prices screen.

## Daily ordering rules

- **Daily-order items.** All vegetables and raw meats, plus Soya Chaap, Curd (Open) ("dahi box"), Separata Curd, Paneer, Khoya, Eggs Tray, Noodles and Rumali Roti. Change the list in Setup → Daily ordering.
- **Requirements.** A station's requirement is entered for a delivery date, in consumption units. Changing it after any vendor order for that date has been sent marks it *changed late*, and that vendor's order shows *send again*.
- **Split orders.** An item can be ordered from several vendors in different quantities. If an item was split on its most recent delivery date in the last 30 days, the plan pre-fills the same vendors with the same proportions of the new total; the last vendor takes the remainder.
- **WhatsApp groups.** A vendor's WhatsApp group name takes priority over its phone number. Links can't select a group, so the app opens the share screen with the message and names the group to pick.
- **Order quantity.** This is in purchase units and defaults to the total asked ÷ conversion ratio, rounded up to whole purchase units when the ratio is above 1. *Subtract stock in store* lowers it by the estimated stock at the end of the previous day.
- **Receiving.** Confirming what arrived creates (or updates) the purchase bill, so stock and prices update as with any purchase. A delivery with nothing received creates no bill.
- **Giving to stations.** What the store gives a station is that station's issue for the day. It is the same record the station issues screen shows, so nothing is entered twice.
- **Pending.** An item is pending when given < asked for, on or before today, within the last 7 days, and not closed. The reason shown is one of:
  - *not ordered from a vendor*
  - *not received from <vendor> yet*
  - *<vendor> short-supplied (received of ordered)*
  - *not handed over yet*

  Pending items appear on the dashboard, as a red count in the menu, and on the Pending tab, which can be shared on WhatsApp.

## Backlog: cooked items balance (station level)

What it's for: stations carry prepared items from one day to the next (gravies, marinated meats, boiled/prepped items). Today that balance isn't recorded anywhere, so the station's cost on a day can't distinguish "used" from "prepared and kept". This wasn't in the October workbook.

To settle before building:
1. Which items: a fixed list of prepped items per station (e.g. Makhani gravy, Tikka marinade), or any item?
2. Units: kg/litres, or portions/containers?
3. When counted: end of every shift, end of day, or only before audits?
4. Value: entered in ₹, or derived from recipes (needs phase 4)?
5. Should leftover count reduce the next day's requirement suggestions?
6. Does it feed wastage (balance thrown away) or audits (station stock alongside store stock)?
