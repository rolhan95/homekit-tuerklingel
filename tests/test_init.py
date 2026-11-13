"""Einrichten und Entladen."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant


async def test_setup_unload(hass: HomeAssistant, mock_entry, aioclient_mock) -> None:
    """Entry lässt sich einrichten und entladen; Webhook ist registriert."""
    aioclient_mock.get("http://192.168.1.50/shelly", json={"mac": "AABBCCDDEEFF", "type": "SHSW-1"})
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state is ConfigEntryState.LOADED
    assert "test_webhook_id_0123456789" in hass.data["webhook"]
    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state is ConfigEntryState.NOT_LOADED
    assert "test_webhook_id_0123456789" not in hass.data["webhook"]
