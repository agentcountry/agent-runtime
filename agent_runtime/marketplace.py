"""
Plugin Marketplace — registry, install, uninstall, search.

Phase 3: Community plugin ecosystem. Plugins are Python packages
with a plugin.json manifest. The marketplace queries a registry
(initially local, pluggable to remote) for discovery.
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from . import Runtime

logger = logging.getLogger("agent-runtime.marketplace")

PLUGINS_DIR = Path(os.path.expanduser("~/.agent-runtime/plugins"))
REGISTRY_FILE = PLUGINS_DIR / "registry.json"


@dataclass
class PluginInfo:
    """Metadata for a marketplace plugin."""
    name: str
    version: str
    description: str = ""
    author: str = ""
    license: str = "Apache 2.0"
    capabilities: list = field(default_factory=list)
    dependencies: list = field(default_factory=list)
    homepage: str = ""
    install_count: int = 0
    rating: float = 0.0
    tags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "license": self.license,
            "capabilities": self.capabilities,
            "dependencies": self.dependencies,
            "homepage": self.homepage,
            "install_count": self.install_count,
            "rating": self.rating,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PluginInfo":
        return cls(**{k: data.get(k, v.default if v.default != field(default_factory=list) else [])
                      for k, v in cls.__dataclass_fields__.items()})


class PluginMarketplace:
    """Plugin discovery and lifecycle management."""

    def __init__(self, runtime: "Runtime"):
        self.runtime = runtime
        self._registry: dict[str, PluginInfo] = {}
        self._installed: dict[str, PluginInfo] = {}
        self._load_registry()

    def _load_registry(self):
        """Load local plugin registry."""
        PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        if REGISTRY_FILE.exists():
            try:
                data = json.loads(REGISTRY_FILE.read_text())
                self._registry = {
                    name: PluginInfo.from_dict(info)
                    for name, info in data.get("plugins", {}).items()
                }
                logger.debug(f"Registry loaded: {len(self._registry)} plugins")
            except Exception as e:
                logger.warning(f"Failed to load registry: {e}")

    def _save_registry(self):
        """Save local plugin registry."""
        data = {
            "updated_at": _now_iso(),
            "plugins": {name: info.to_dict() for name, info in self._registry.items()},
        }
        REGISTRY_FILE.write_text(json.dumps(data, indent=2))

    # ── Registry Operations ────────────────────────────

    async def register(self, info: PluginInfo):
        """Register a plugin in the marketplace."""
        if info.name in self._registry:
            logger.warning(f"Plugin already registered: {info.name}")
            return False

        self._registry[info.name] = info
        self._save_registry()

        self.runtime.storage.audit("plugin_registered", {
            "name": info.name,
            "version": info.version,
        })
        logger.info(f"Plugin registered: {info.name} v{info.version}")
        return True

    async def unregister(self, name: str) -> bool:
        """Remove a plugin from the marketplace registry."""
        if name not in self._registry:
            return False

        del self._registry[name]
        self._save_registry()
        logger.info(f"Plugin unregistered: {name}")
        return True

    def search(self, query: str = "", tags: list = None, capability: str = "") -> list[PluginInfo]:
        """Search the registry for plugins."""
        results = list(self._registry.values())

        if query:
            q = query.lower()
            results = [
                p for p in results
                if q in p.name.lower()
                or q in p.description.lower()
                or any(q in tag.lower() for tag in p.tags)
            ]

        if tags:
            results = [p for p in results if all(t in p.tags for t in tags)]

        if capability:
            results = [p for p in results if capability in p.capabilities]

        return sorted(results, key=lambda p: (-p.rating, -p.install_count))

    # ── Install / Uninstall ────────────────────────────

    async def install(self, name: str, version: str = "") -> Optional[PluginInfo]:
        """Install a plugin from the registry."""
        plugin_info = self._registry.get(name)
        if not plugin_info:
            logger.error(f"Plugin not found in registry: {name}")
            return None

        if name in self._installed:
            logger.warning(f"Plugin already installed: {name}")
            return self._installed[name]

        target_version = version or plugin_info.version

        # Install into plugins directory
        plugin_dir = PLUGINS_DIR / name
        plugin_dir.mkdir(parents=True, exist_ok=True)

        # Write plugin manifest
        manifest = plugin_info.to_dict()
        manifest["installed_version"] = target_version
        manifest["installed_at"] = _now_iso()
        (plugin_dir / "plugin.json").write_text(json.dumps(manifest, indent=2))

        # Install dependencies
        if plugin_info.dependencies:
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install"] + plugin_info.dependencies,
                    capture_output=True,
                    timeout=120,
                    check=False,
                )
            except Exception as e:
                logger.error(f"Failed to install dependencies for {name}: {e}")

        # Load into runtime
        await self._load_plugin(name, plugin_dir)

        plugin_info.install_count += 1
        self._installed[name] = plugin_info
        self._save_registry()

        self.runtime.storage.audit("plugin_installed", {
            "name": name,
            "version": target_version,
        })
        logger.info(f"Plugin installed: {name} v{target_version}")
        return plugin_info

    async def uninstall(self, name: str) -> bool:
        """Uninstall a plugin."""
        if name not in self._installed:
            logger.warning(f"Plugin not installed: {name}")
            return False

        # Unload from runtime
        self.runtime.plugins.unregister(name)

        # Remove plugin directory
        plugin_dir = PLUGINS_DIR / name
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir)

        del self._installed[name]

        self.runtime.storage.audit("plugin_uninstalled", {"name": name})
        logger.info(f"Plugin uninstalled: {name}")
        return True

    # ── Listing ─────────────────────────────────────────

    def list_installed(self) -> list[PluginInfo]:
        return list(self._installed.values())

    def list_registry(self) -> list[PluginInfo]:
        return list(self._registry.values())

    # ── Remote Sync (Phase 3+ stub) ────────────────────

    async def sync_remote(self, registry_url: str = "") -> bool:
        """Sync with a remote plugin registry. Stub for Phase 3+."""
        logger.info("Remote registry sync not yet implemented")
        return False

    # ── Internal ────────────────────────────────────────

    async def _load_plugin(self, name: str, plugin_dir: Path):
        """Dynamically load a plugin module."""
        import importlib.util

        init_file = plugin_dir / "__init__.py"
        if not init_file.exists():
            # Create a minimal entry point
            init_file.write_text(
                f'"""Plugin: {name}"""\n'
                f'from agent_runtime.plugins import plugin\n\n'
                f'@plugin(name="{name}")\n'
                f'async def main(params):\n'
                f'    return "Plugin {name} loaded"\n'
            )

        spec = importlib.util.spec_from_file_location(
            f"agent_runtime_plugin_{name}",
            init_file,
        )
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
