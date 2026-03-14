"""
TicketForge — Plugin system

Provides a pluggable architecture for custom enrichment processors.
Plugins can hook into pre-analysis, post-analysis, or custom enrichment stages.
"""
from __future__ import annotations

import abc
from typing import Any

import structlog

log = structlog.get_logger(__name__)


class Plugin(abc.ABC):
    """Abstract base class for TicketForge plugins."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique plugin name."""

    @property
    def version(self) -> str:
        """Plugin version string."""
        return "0.1.0"

    @property
    def description(self) -> str:
        """Human-readable description."""
        return ""

    @property
    @abc.abstractmethod
    def hook(self) -> str:
        """Hook point: pre_analysis, post_analysis, or custom_enrichment."""

    async def on_pre_analysis(self, ticket_data: dict[str, Any]) -> dict[str, Any]:
        """
        Called before ticket analysis. Can modify or enrich the raw ticket data.
        Return the (possibly modified) ticket data dict.
        """
        return ticket_data

    async def on_post_analysis(self, enriched_data: dict[str, Any]) -> dict[str, Any]:
        """
        Called after ticket analysis. Can modify or extend enrichment results.
        Return the (possibly modified) enriched data dict.
        """
        return enriched_data

    async def on_custom_enrichment(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Custom enrichment hook. Can add new fields or data to the result.
        Return the enriched data dict.
        """
        return data


class PluginRegistry:
    """Registry for managing TicketForge plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._enabled: dict[str, bool] = {}

    def register(self, plugin: Plugin) -> None:
        """Register a plugin. Overwrites any existing plugin with the same name."""
        if plugin.name in self._plugins:
            log.warning("plugin.overwritten", name=plugin.name)
        self._plugins[plugin.name] = plugin
        self._enabled[plugin.name] = True
        log.info(
            "plugin.registered",
            name=plugin.name,
            version=plugin.version,
            hook=plugin.hook,
        )

    def unregister(self, name: str) -> bool:
        """Remove a plugin by name. Returns True if found and removed."""
        if name in self._plugins:
            del self._plugins[name]
            self._enabled.pop(name, None)
            log.info("plugin.unregistered", name=name)
            return True
        return False

    def enable(self, name: str) -> bool:
        """Enable a registered plugin. Returns True if found."""
        if name in self._plugins:
            self._enabled[name] = True
            return True
        return False

    def disable(self, name: str) -> bool:
        """Disable a registered plugin. Returns True if found."""
        if name in self._plugins:
            self._enabled[name] = False
            return True
        return False

    def is_enabled(self, name: str) -> bool:
        """Check if a plugin is enabled."""
        return self._enabled.get(name, False)

    def list_plugins(self) -> list[dict[str, Any]]:
        """Return metadata for all registered plugins."""
        return [
            {
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "hook": p.hook,
                "enabled": self._enabled.get(p.name, False),
            }
            for p in self._plugins.values()
        ]

    def get_plugins_for_hook(self, hook: str) -> list[Plugin]:
        """Return all enabled plugins registered for a specific hook."""
        return [
            p
            for p in self._plugins.values()
            if p.hook == hook and self._enabled.get(p.name, False)
        ]

    async def run_pre_analysis(self, ticket_data: dict[str, Any]) -> dict[str, Any]:
        """Execute all enabled pre_analysis plugins in registration order."""
        for plugin in self.get_plugins_for_hook("pre_analysis"):
            try:
                ticket_data = await plugin.on_pre_analysis(ticket_data)
                log.debug("plugin.pre_analysis.ok", plugin=plugin.name)
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "plugin.pre_analysis.failed",
                    plugin=plugin.name,
                    error=str(e),
                )
        return ticket_data

    async def run_post_analysis(self, enriched_data: dict[str, Any]) -> dict[str, Any]:
        """Execute all enabled post_analysis plugins in registration order."""
        for plugin in self.get_plugins_for_hook("post_analysis"):
            try:
                enriched_data = await plugin.on_post_analysis(enriched_data)
                log.debug("plugin.post_analysis.ok", plugin=plugin.name)
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "plugin.post_analysis.failed",
                    plugin=plugin.name,
                    error=str(e),
                )
        return enriched_data

    async def run_custom_enrichment(self, data: dict[str, Any]) -> dict[str, Any]:
        """Execute all enabled custom_enrichment plugins in registration order."""
        for plugin in self.get_plugins_for_hook("custom_enrichment"):
            try:
                data = await plugin.on_custom_enrichment(data)
                log.debug("plugin.custom_enrichment.ok", plugin=plugin.name)
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "plugin.custom_enrichment.failed",
                    plugin=plugin.name,
                    error=str(e),
                )
        return data


# Module-level singleton registry
plugin_registry = PluginRegistry()
