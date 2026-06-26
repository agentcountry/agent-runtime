"""Plugin interface — extensibility via @runtime.plugin decorator."""

import logging
from typing import Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from . import Runtime
    from .decision import IntentResult

logger = logging.getLogger("agent-runtime.plugins")


class PluginManager:
    """Manages plugin registration, loading, and invocation."""
    
    def __init__(self):
        self._plugins: dict[str, Any] = {}
    
    def register(self, name: str, plugin: Any):
        """Register a plugin."""
        self._plugins[name] = plugin
        logger.info(f"Plugin registered: {name}")
    
    def unregister(self, name: str):
        """Unregister a plugin."""
        if name in self._plugins:
            del self._plugins[name]
            logger.info(f"Plugin unregistered: {name}")
    
    def get(self, name: str) -> Optional[Any]:
        """Get a plugin by name."""
        return self._plugins.get(name)
    
    def list(self) -> list[str]:
        """List all registered plugin names."""
        return list(self._plugins.keys())
    
    async def load_all(self):
        """Load all registered plugins."""
        for name, plugin in self._plugins.items():
            if hasattr(plugin, 'on_load'):
                try:
                    await plugin.on_load()
                    logger.debug(f"Plugin loaded: {name}")
                except Exception as e:
                    logger.error(f"Plugin '{name}' on_load failed: {e}")
    
    async def on_message(self, message: Any, intent: "IntentResult"):
        """Notify all plugins of an incoming message."""
        for name, plugin in self._plugins.items():
            if hasattr(plugin, 'on_message'):
                try:
                    await plugin.on_message(message, intent)
                except Exception as e:
                    logger.error(f"Plugin '{name}' on_message failed: {e}")
    
    async def call_api(self, api_name: str, params: dict = None) -> Optional[str]:
        """Call an API through registered plugins."""
        for name, plugin in self._plugins.items():
            if hasattr(plugin, 'api_name') and plugin.api_name == api_name:
                if hasattr(plugin, 'call'):
                    try:
                        result = await plugin.call(params or {})
                        return str(result)
                    except Exception as e:
                        logger.error(f"Plugin '{name}' API call failed: {e}")
                        return f"Error: {e}"
        return None


def plugin(name: str = "", api_name: str = ""):
    """Decorator to create a simple plugin from a function."""
    def decorator(func: Callable):
        class SimplePlugin:
            def __init__(self):
                self.name = name or func.__name__
                self.api_name = api_name
            
            async def on_load(self):
                pass
            
            async def call(self, params: dict = None) -> Any:
                return await func(params or {})
        
        return SimplePlugin()
    return decorator
