"""Database models.

Every operational table carries outlet_id so multi-outlet support (phase 5) needs no schema change.
Quantities: purchases are in purchase units; issues, wastage and audit counts are in consumption units.
Prices are stored per purchase unit.
"""
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

Qty = Numeric(14, 3, asdecimal=False)
Money = Numeric(14, 2, asdecimal=False)


def outlet_fk() -> Mapped[int]:
    return mapped_column(ForeignKey("outlets.id"), index=True, default=1)


class Outlet(Base):
    __tablename__ = "outlets"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))


class User(Base):
    """App login. No roles yet: every active user can use every screen."""

    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # bumping this signs the user out everywhere (password change, deactivation)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    # a station login (shared kitchen device) opens the kitchen screen for that station; not a permission
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id", ondelete="SET NULL"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Setting(Base):
    __tablename__ = "settings"
    outlet_id: Mapped[int] = mapped_column(ForeignKey("outlets.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("outlet_id", "name", name="uq_item_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = outlet_fk()
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(80), index=True)
    pricing_mode: Mapped[str] = mapped_column(String(20))  # weekly_avg | daily
    purchase_unit: Mapped[str] = mapped_column(String(40))
    consumption_unit: Mapped[str] = mapped_column(String(40))
    conversion_ratio: Mapped[float] = mapped_column(Qty, default=1)  # consumption units per purchase unit
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # ordered every day from a vendor (vegetables, poultry, dairy, eggs, noodles, rumali)
    daily_order: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    default_vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id", ondelete="SET NULL"))


class Station(Base):
    __tablename__ = "stations"
    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = outlet_fk()
    name: Mapped[str] = mapped_column(String(80))
    # kitchen | staff | packaging | daily_items -- drives food cost % and gross cost % in the P&L
    kind: Mapped[str] = mapped_column(String(20), default="kitchen")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class StationItem(Base):
    __tablename__ = "station_items"
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Vendor(Base):
    __tablename__ = "vendors"
    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = outlet_fk()
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(30))
    # orders go to a WhatsApp group; WhatsApp can't pre-select a group from a link, so the app
    # opens the share screen and shows which group to pick
    whatsapp_group: Mapped[str | None] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PriceEntry(Base):
    __tablename__ = "price_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = outlet_fk()
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    price: Mapped[float] = mapped_column(Money)  # per purchase unit
    source: Mapped[str] = mapped_column(String(10))  # manual | purchase
    purchase_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_lines.id", ondelete="CASCADE"), index=True
    )


class PurchaseBill(Base):
    __tablename__ = "purchase_bills"
    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = outlet_fk()
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    bill_no: Mapped[str | None] = mapped_column(String(60))
    payment_status: Mapped[str] = mapped_column(String(10), default="paid")  # paid | credit | partial
    amount_paid: Mapped[float] = mapped_column(Money, default=0)
    photo_path: Mapped[str | None] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lines: Mapped[list["PurchaseLine"]] = relationship(
        back_populates="bill", cascade="all, delete-orphan", order_by="PurchaseLine.id"
    )
    vendor: Mapped[Vendor] = relationship()


class PurchaseLine(Base):
    __tablename__ = "purchase_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("purchase_bills.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    qty: Mapped[float] = mapped_column(Qty)  # purchase units
    rate: Mapped[float] = mapped_column(Money)  # per purchase unit
    bill: Mapped[PurchaseBill] = relationship(back_populates="lines")


class Issue(Base):
    """Stock issued from store to a station (the old station / ordering sheets)."""

    __tablename__ = "issues"
    __table_args__ = (UniqueConstraint("date", "station_id", "item_id", name="uq_issue_day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = outlet_fk()
    date: Mapped[date] = mapped_column(Date, index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    qty: Mapped[float] = mapped_column(Qty)  # consumption units


class Wastage(Base):
    """Money wastage of cooked food (the old WastageSheet). Does not move raw-material stock."""

    __tablename__ = "wastage"
    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = outlet_fk()
    date: Mapped[date] = mapped_column(Date, index=True)
    dish: Mapped[str] = mapped_column(String(160))
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id"))
    qty: Mapped[float | None] = mapped_column(Qty)
    unit: Mapped[str | None] = mapped_column(String(30))  # e.g. plates, portions, kg
    value: Mapped[float] = mapped_column(Money)  # rupees
    reason: Mapped[str] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)


class Audit(Base):
    __tablename__ = "audits"
    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = outlet_fk()
    date: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(12))  # opening | spot | month_end
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft | closed
    notes: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counts: Mapped[list["AuditCount"]] = relationship(cascade="all, delete-orphan")


class AuditCount(Base):
    __tablename__ = "audit_counts"
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)
    counted_qty: Mapped[float] = mapped_column(Qty)


class Channel(Base):
    """A brand x platform row (e.g. Swiggy / Oh Delhi) used by discount, delivery and ads entry."""

    __tablename__ = "channels"
    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = outlet_fk()
    platform: Mapped[str] = mapped_column(String(60))
    brand: Mapped[str] = mapped_column(String(80))
    kinds: Mapped[str] = mapped_column(String(60), default="discount,delivery,ads")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ChannelCost(Base):
    __tablename__ = "channel_costs"
    __table_args__ = (UniqueConstraint("date", "channel_id", "kind", name="uq_channel_cost"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = outlet_fk()
    date: Mapped[date] = mapped_column(Date, index=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # discount | delivery | ads
    amount: Mapped[float] = mapped_column(Money)


class DailySales(Base):
    __tablename__ = "daily_sales"
    __table_args__ = (UniqueConstraint("outlet_id", "date", name="uq_sales_day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = outlet_fk()
    date: Mapped[date] = mapped_column(Date, index=True)
    gross_sale: Mapped[float] = mapped_column(Money, default=0)
    complimentary: Mapped[float] = mapped_column(Money, default=0)
    net_sales: Mapped[float] = mapped_column(Money, default=0)  # with tax


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = outlet_fk()
    name: Mapped[str] = mapped_column(String(100))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (UniqueConstraint("date", "category_id", name="uq_expense_day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = outlet_fk()
    date: Mapped[date] = mapped_column(Date, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("expense_categories.id"), index=True)
    amount: Mapped[float] = mapped_column(Money)


class MonthlyInput(Base):
    __tablename__ = "monthly_inputs"
    outlet_id: Mapped[int] = mapped_column(ForeignKey("outlets.id"), primary_key=True)
    month: Mapped[str] = mapped_column(String(7), primary_key=True)  # YYYY-MM
    wage_cost: Mapped[float] = mapped_column(Money, default=0)
    days_of_operation: Mapped[int | None] = mapped_column(Integer)


class Staff(Base):
    __tablename__ = "staff"
    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = outlet_fk()
    name: Mapped[str] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = outlet_fk()
    brand: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(40))
    date: Mapped[date] = mapped_column(Date, index=True)
    shift: Mapped[str | None] = mapped_column(String(20))
    review_item: Mapped[str | None] = mapped_column(String(160))
    review_text: Mapped[str | None] = mapped_column(Text)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id"))
    concerned_person: Mapped[str | None] = mapped_column(String(80))
    rating: Mapped[float | None] = mapped_column(Numeric(3, 1, asdecimal=False))
    assigned_to: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(12), default="open")  # open | in_progress | resolved
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Requisition(Base):
    """What a station asked for, for a delivery date (entered by the chef the evening before)."""

    __tablename__ = "requisitions"
    __table_args__ = (UniqueConstraint("date", "station_id", "item_id", name="uq_requisition"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = outlet_fk()
    date: Mapped[date] = mapped_column(Date, index=True)  # the day the station needs it
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    qty: Mapped[float] = mapped_column(Qty)  # consumption units
    late: Mapped[bool] = mapped_column(Boolean, default=False)  # changed after the vendor order was sent
    updated_by: Mapped[str | None] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismiss_reason: Mapped[str | None] = mapped_column(String(160))


class DailyOrder(Base):
    """One vendor's order for a delivery date: planned -> sent on WhatsApp -> received."""

    __tablename__ = "daily_orders"
    __table_args__ = (UniqueConstraint("date", "vendor_id", name="uq_daily_order"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = outlet_fk()
    date: Mapped[date] = mapped_column(Date, index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True)
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft | sent | received
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    changed_after_send: Mapped[bool] = mapped_column(Boolean, default=False)
    purchase_bill_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_bills.id", ondelete="SET NULL"))
    lines: Mapped[list["DailyOrderLine"]] = relationship(cascade="all, delete-orphan", order_by="DailyOrderLine.id")
    vendor: Mapped[Vendor] = relationship()


class DailyOrderLine(Base):
    __tablename__ = "daily_order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("daily_orders.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    qty_ordered: Mapped[float] = mapped_column(Qty)  # purchase units
    qty_received: Mapped[float | None] = mapped_column(Qty)  # purchase units, set on receipt
    rate: Mapped[float | None] = mapped_column(Money)
