"""Einrichten und Entladen."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .conftest import TRIGGER, WEBHOOK_ID


async def test_setup_unload(hass: HomeAssistant, mock_entry) -> None:
    """Entry lässt sich einrichten und entladen; Webhook ist registriert."""
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state is ConfigEntryState.LOADED
    assert WEBHOOK_ID in hass.data["webhook"]
    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state is ConfigEntryState.NOT_LOADED
    assert WEBHOOK_ID not in hass.data["webhook"]


async def test_unload_removes_trigger_listener(hass: HomeAssistant, mock_entry) -> None:
    """Nach dem Entladen löst die Auslöser-Entität nichts mehr aus."""
    hass.states.async_set(TRIGGER, "off")
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    hub = mock_entry.runtime_data
    hub.gong_enabled = False
    hass.states.async_set(TRIGGER, "on")
    await hass.async_block_till_done()
    assert hub.stats["entity_triggers"] == 1

    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert hub._unsub_triggers is None
    hass.states.async_set(TRIGGER, "off")
    hass.states.async_set(TRIGGER, "on")
    await hass.async_block_till_done()
    assert hub.stats["entity_triggers"] == 1


async def test_options_update_reloads(hass: HomeAssistant, mock_entry) -> None:
    """Geänderte Optionen laden die Klingel neu (neuer Hub)."""
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    old_hub = mock_entry.runtime_data
    hass.config_entries.async_update_entry(
        mock_entry, options={**mock_entry.options, "auto_off": 9}
    )
    await hass.async_block_till_done()
    assert mock_entry.state is ConfigEntryState.LOADED
    assert mock_entry.runtime_data is not old_hub
    assert mock_entry.runtime_data.auto_off == 9
