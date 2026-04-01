"""TicketForge load testing suite using Locust."""

import os

from locust import HttpUser, between, tag, task


class TicketForgeUser(HttpUser):
    """Simulates a typical TicketForge API consumer."""

    wait_time = between(1, 3)

    def on_start(self):
        """Set up authentication headers for the session."""
        api_key = os.getenv("TICKETFORGE_API_KEY", "test-api-key")
        self.client.headers.update({"X-API-Key": api_key})

    @tag("smoke", "load", "stress")
    @task(5)
    def health_check(self):
        """GET /health — lightweight liveness probe."""
        self.client.get("/health", name="/health")

    @tag("load", "stress")
    @task(3)
    def get_analytics(self):
        """GET /analytics — fetch analytics dashboard data."""
        self.client.get("/analytics", name="/analytics")

    @tag("load", "stress")
    @task(3)
    def list_tickets(self):
        """GET /tickets — list tickets (cached endpoint)."""
        self.client.get("/tickets", name="/tickets")

    @tag("load", "stress")
    @task(2)
    def create_ticket(self):
        """POST /portal/tickets — create a new support ticket."""
        payload = {
            "title": "Load test ticket",
            "description": "This ticket was created by the Locust load testing suite.",
            "priority": "medium",
            "category": "general",
        }
        self.client.post("/portal/tickets", json=payload, name="/portal/tickets")

    @tag("load", "stress")
    @task(2)
    def search_kb(self):
        """POST /kb/search — search the knowledge base."""
        payload = {"query": "how to reset password"}
        self.client.post("/kb/search", json=payload, name="/kb/search")

    @tag("load")
    @task(1)
    def get_audit_logs(self):
        """GET /audit-log — retrieve audit log entries."""
        self.client.get("/audit-log", name="/audit-log")
