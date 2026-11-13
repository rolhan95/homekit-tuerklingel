"""Tests für die Migration der Config-Entries von Version 1 (Shelly Gen1) auf Version 2."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_tuerklingel.const import (
    CONF_ALLOWED_SOURCES,
    CONF_AUTO_OFF,
    CONF_GONG_ENTITY,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_SERVICES,
    CONF_RESTRICT_IP,
    CONF_TRIGGER_ENTITIES,
    CONF_WEBHOOK_ENABLED,
    CONFIG_VERSION,
    DOMAIN,
    ISSUE_GONG_SELECT,
    ISSUE_NOT_DETACHED_V1,
    KEY_CONNECTIVITY_V1,
)

from .conftest import CAMERA, SHELLY_HOST, WEBHOOK_ID

MAC = "AABBCCDDEEFF"
"""So hat 0.1.x die MAC gespeichert (wie von /shelly gemeldet, ohne Doppelpunkte)."""


def _v1_entry(*, mac: str | None = MAC, host: str = SHELLY_HOST, **options) -> MockConfigEntry:
    data = {
        "shelly_host": host,
        "shelly_username": "admin",
        "shelly_password": "geheim",
        "camera_entity": CAMERA,
        "webhook_id": WEBHOOK_ID,
    }
    if mac is not None:
        data["shelly_mac"] = mac
    return MockConfigEntry(
        domain=DOMAIN,
        title="Haustür",
        version=1,
        data=data,
        options={
            "connectivity": True,
            CONF_AUTO_OFF: 7,
            CONF_NOTIFY_ENABLED: True,
            CONF_NOTIFY_SERVICES: ["mobile_app_iphone"],
            **options,
        },
    )


def _shelly_device(
    hass: HomeAssistant, switches: int = 1, *, disabled_extra: bool = False
) -> list[str]:
    """Gerät der Shelly-Integration mit MAC-Connection und switch-Entitäten anlegen."""
    shelly_entry = MockConfigEntry(domain="shelly", data={})
    shelly_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=shelly_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, dr.format_mac(MAC))},
        name="Shelly 1",
    )
    ent_reg = er.async_get(hass)
    ids = [
        ent_reg.async_get_or_create(
            "switch",
            "shelly",
            f"relay_{i}",
            device_id=device.id,
            config_entry=shelly_entry,
            suggested_object_id=f"shelly_relais_{i}",
        ).entity_id
        for i in range(switches)
    ]
    # Andere Domains am Gerät zählen nicht
    ent_reg.async_get_or_create(
        "sensor", "shelly", "power", device_id=device.id, config_entry=shelly_entry
    )
    if disabled_extra:
        ent_reg.async_get_or_create(
            "switch",
            "shelly",
            "relay_disabled",
            device_id=device.id,
            config_entry=shelly_entry,
            disabled_by=er.RegistryEntryDisabler.USER,
        )
    return ids


async def _migrate(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _issue(hass: HomeAssistant, prefix: str, entry: MockConfigEntry) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{prefix}_{entry.entry_id}")


async def test_migrate_with_gong(hass: HomeAssistant) -> None:
    """Gong über die MAC gefunden; Daten bereinigt, Optionen umgestellt, Setup geladen."""
    (gong,) = _shelly_device(hass, disabled_extra=True)
    entry = _v1_entry()
    await _migrate(hass, entry)

    assert entry.version == CONFIG_VERSION == 2
    assert entry.state is ConfigEntryState.LOADED
    assert dict(entry.data) == {"webhook_id": WEBHOOK_ID, "camera_entity": CAMERA}
    assert dict(entry.options) == {
        CONF_AUTO_OFF: 7,
        CONF_NOTIFY_ENABLED: True,
        CONF_NOTIFY_SERVICES: ["mobile_app_iphone"],
        CONF_WEBHOOK_ENABLED: True,
        CONF_RESTRICT_IP: True,
        CONF_ALLOWED_SOURCES: [SHELLY_HOST],
        CONF_TRIGGER_ENTITIES: [],
        CONF_GONG_ENTITY: gong,
    }
    assert _issue(hass, ISSUE_GONG_SELECT, entry) is None
    hub = entry.runtime_data
    assert hub.gong_entity_id == gong
    assert hub.ip_allowed(SHELLY_HOST) is True
    assert WEBHOOK_ID in hass.data["webhook"]


async def test_migrate_allowed_ip_and_restrict_off(hass: HomeAssistant) -> None:
    """Abweichende erlaubte IP wird übernommen, ausgeschalteter Filter bleibt aus."""
    entry = _v1_entry(mac=None, allowed_ip=" 192.168.1.99 ", restrict_ip=False)
    await _migrate(hass, entry)
    assert entry.options[CONF_ALLOWED_SOURCES] == ["192.168.1.99"]
    assert entry.options[CONF_RESTRICT_IP] is False
    assert "allowed_ip" not in entry.options
    assert "connectivity" not in entry.options


async def test_migrate_empty_sources(hass: HomeAssistant) -> None:
    """Weder erlaubte IP noch Host → leere Quellenliste."""
    entry = _v1_entry(mac=None, host="", allowed_ip="")
    await _migrate(hass, entry)
    assert entry.options[CONF_ALLOWED_SOURCES] == []


@pytest.mark.parametrize(
    ("mac", "switches"),
    [
        (None, 1),
        (MAC, 0),
        (MAC, 2),
        ("112233445566", 1),
    ],
    ids=["ohne_mac", "kein_switch", "mehrere_switches", "fremde_mac"],
)
async def test_migrate_without_gong(hass: HomeAssistant, mac, switches) -> None:
    """Kein eindeutiger Gong → None und Issue gong_waehlen."""
    _shelly_device(hass, switches)
    entry = _v1_entry(mac=mac)
    await _migrate(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.options[CONF_GONG_ENTITY] is None
    issue = _issue(hass, ISSUE_GONG_SELECT, entry)
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.is_persistent is True
    assert issue.translation_key == ISSUE_GONG_SELECT
    assert issue.translation_placeholders == {"name": "Haustür"}


async def test_migrate_cleans_registry_and_issues(hass: HomeAssistant) -> None:
    """Alte Erreichbarkeits-Entität und Hinweis 'Eingang nicht entkoppelt' verschwinden."""
    entry = _v1_entry(mac=None)
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    old = ent_reg.async_get_or_create(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_{KEY_CONNECTIVITY_V1}", config_entry=entry
    ).entity_id
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{ISSUE_NOT_DETACHED_V1}_{entry.entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_NOT_DETACHED_V1,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert ent_reg.async_get(old) is None
    assert _issue(hass, ISSUE_NOT_DETACHED_V1, entry) is None


async def test_migrate_future_version_fails(hass: HomeAssistant) -> None:
    """Neuere Version als bekannt → Migration schlägt fehl, Daten bleiben."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Zukunft",
        version=CONFIG_VERSION + 1,
        data={"webhook_id": WEBHOOK_ID, "camera_entity": CAMERA},
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.MIGRATION_ERROR
    assert entry.version == CONFIG_VERSION + 1


async def test_migrate_current_version_untouched(hass: HomeAssistant, mock_entry) -> None:
    """Version 2 wird nicht verändert."""
    options = dict(mock_entry.options)
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.version == 2
    assert dict(mock_entry.options) == options


async def test_migrate_disabled_device_entities(hass: HomeAssistant) -> None:
    """Deaktivierter einziger Switch zählt nicht → kein Gong."""
    shelly_entry = MockConfigEntry(domain="shelly", data={})
    shelly_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=shelly_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, dr.format_mac(MAC))},
    )
    er.async_get(hass).async_get_or_create(
        "switch",
        "shelly",
        "relay_0",
        device_id=device.id,
        config_entry=shelly_entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    entry = _v1_entry()
    await _migrate(hass, entry)
    assert entry.options[CONF_GONG_ENTITY] is None


async def test_migrate_entry_rejects_newer_version(hass: HomeAssistant) -> None:
    """async_migrate_entry selbst lehnt unbekannte, neuere Versionen ab.

    (HA ruft die Funktion bei einer Herabstufung meist gar nicht erst auf.)
    """
    from custom_components.homekit_tuerklingel import async_migrate_entry

    entry = MockConfigEntry(domain=DOMAIN, version=CONFIG_VERSION + 1, data={})
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry) is False
    assert entry.version == CONFIG_VERSION + 1
