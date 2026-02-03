"""Get manufacturer from mac address."""

from __future__ import annotations

import aiooui

from .const import EMPTY_MAC_ADDRESS


async def get_manufacturer_from_mac(mac_address: str) -> str | None:
    """Get manufacturer from mac address."""
    if not aiooui.is_loaded():
        await aiooui.async_load()
    if mac_address == EMPTY_MAC_ADDRESS:
        return None
    return aiooui.get_vendor(mac_address)
