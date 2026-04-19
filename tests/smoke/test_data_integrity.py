"""
tests/smoke/test_data_integrity.py — Data integrity smoke tests.

Requirements: 11.1–11.4, 6.4
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_DATA_DIR = Path(__file__).parent.parent.parent / "data"

VIP_CUSTOMERS = {"Alice", "Emma"}
PREMIUM_CUSTOMERS = {"Carol", "Grace", "Irene"}
STANDARD_CUSTOMERS = {"Bob", "Dave", "Frank", "Henry", "Jane"}


def _load(filename: str):
    with open(_DATA_DIR / filename, encoding="utf-8") as fh:
        return json.load(fh)


class TestDataIntegrity:
    def test_tickets_json_has_exactly_20_tickets(self):
        tickets = _load("tickets.json")
        assert len(tickets) == 20, f"Expected 20 tickets, got {len(tickets)}"

    def test_customers_json_has_exactly_10_customers(self):
        customers = _load("customers.json")
        assert len(customers) == 10, f"Expected 10 customers, got {len(customers)}"

    def test_products_json_has_exactly_8_products(self):
        products = _load("products.json")
        assert len(products) == 8, f"Expected 8 products, got {len(products)}"

    def test_vip_customers_are_alice_and_emma(self):
        customers = _load("customers.json")
        vip_names = {c["name"] for c in customers if c.get("tier") == "vip"}
        assert vip_names == VIP_CUSTOMERS, (
            f"VIP customers must be {VIP_CUSTOMERS}, got {vip_names}"
        )

    def test_premium_customers_are_carol_grace_irene(self):
        customers = _load("customers.json")
        premium_names = {c["name"] for c in customers if c.get("tier") == "premium"}
        assert premium_names == PREMIUM_CUSTOMERS, (
            f"Premium customers must be {PREMIUM_CUSTOMERS}, got {premium_names}"
        )

    def test_standard_customers_are_correct(self):
        customers = _load("customers.json")
        standard_names = {c["name"] for c in customers if c.get("tier") == "standard"}
        assert standard_names == STANDARD_CUSTOMERS, (
            f"Standard customers must be {STANDARD_CUSTOMERS}, got {standard_names}"
        )

    def test_products_have_distinct_return_windows(self):
        products = _load("products.json")
        windows = {p["return_window_days"] for p in products}
        assert len(windows) >= 2, (
            f"Products must have at least 2 distinct return windows, got {windows}"
        )

    def test_products_have_distinct_warranty_periods(self):
        products = _load("products.json")
        warranties = {p["warranty_months"] for p in products}
        assert len(warranties) >= 2, (
            f"Products must have at least 2 distinct warranty periods, got {warranties}"
        )

    def test_orders_have_in_window_and_out_of_window_dates(self):
        """orders.json must contain both in-window and out-of-window purchase dates."""
        import datetime
        orders = _load("orders.json")
        products = {p["product_id"]: p for p in _load("products.json")}
        customers = {c["customer_id"]: c for c in _load("customers.json")}

        in_window_count = 0
        out_of_window_count = 0
        today = datetime.date.today()

        for order in orders:
            product = products.get(order.get("product_id", ""), {})
            customer = customers.get(order.get("customer_id", ""), {})
            purchase_date = datetime.date.fromisoformat(order["purchase_date"])
            days_since = (today - purchase_date).days

            return_window = product.get("return_window_days", 30)
            if customer.get("tier") == "vip":
                vip_window = customer.get("vip_exceptions", {}).get("extended_return_window_days")
                if vip_window:
                    return_window = vip_window

            if days_since <= return_window:
                in_window_count += 1
            else:
                out_of_window_count += 1

        assert in_window_count > 0, "orders.json must have at least one in-window order"
        assert out_of_window_count > 0, "orders.json must have at least one out-of-window order"

    def test_all_ticket_customer_ids_exist_in_customers(self):
        tickets = _load("tickets.json")
        customers = {c["customer_id"] for c in _load("customers.json")}
        for ticket in tickets:
            cid = ticket.get("customer_id")
            if cid:
                assert cid in customers, f"Ticket {ticket['ticket_id']} references unknown customer {cid}"

    def test_all_ticket_order_ids_exist_in_orders(self):
        tickets = _load("tickets.json")
        orders = {o["order_id"] for o in _load("orders.json")}
        for ticket in tickets:
            oid = ticket.get("order_id")
            if oid:
                assert oid in orders, f"Ticket {ticket['ticket_id']} references unknown order {oid}"

    def test_tickets_cover_all_resolution_types(self):
        """tickets.json must include tickets for APPROVE, DENY, and ESCALATE scenarios."""
        tickets = _load("tickets.json")
        issue_types = {t.get("issue_type") for t in tickets}
        # Must have at least refund_request (APPROVE/DENY) and at least one escalation type
        assert "refund_request" in issue_types, "Must have refund_request tickets"
        escalation_types = {"warranty_claim", "replacement_request", "threat", "social_engineering"}
        assert issue_types & escalation_types, (
            f"Must have at least one escalation-type ticket, got issue_types={issue_types}"
        )

    def test_each_customer_has_at_least_2_tickets(self):
        """Each customer must appear in at least 2 tickets (for cross-ticket memory testing)."""
        tickets = _load("tickets.json")
        from collections import Counter
        counts = Counter(t.get("customer_id") for t in tickets if t.get("customer_id"))
        for cid, count in counts.items():
            assert count >= 2, (
                f"Customer {cid} must appear in at least 2 tickets for session memory testing, "
                f"got {count}"
            )
