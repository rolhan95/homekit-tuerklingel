"""Tests für Repair-Hinweise, Reparatur-Flow und HomeKit-Anbindung."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_tuerklingel import homekit as hk
from custom_components.homekit_tuerklingel import issues
from custom_components.homekit_tuerklingel.const import (
    DOMAIN,
    ISSUE_GONG_SELECT,
    ISSUE_HOMEKIT_SETUP,
    ISSUE_NOT_DETACHED_V1,
    KEY_CAMERA,
)
from custom_components.homekit_tuerklingel.homekit import HomeKitResult
from custom_components.homekit_tuerklingel.repairs import (
    HomeKitSetupRepairFlow,
    async_create_fix_flow,
)

from .conftest import CAMERA


@pytest.fixture(autouse=True)
def _no_homekit_port_socket():
    """HomeKit prüft Ports per Test-Socket (auch beim Entladen nach dem Test).

    Unter Linux blockiert das Test-Plugin echte Sockets; deshalb für die ganze
    Testdauer inkl. Teardown ersetzen.
    """
    with patch(
        "homeassistant.components.homekit.util._get_test_socket", return_value=MagicMock()
    ):
        yield

PROXY_CAMERA = "camera.haustur_kamera"


def _register_proxy_camera(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    """Registry-Eintrag der Proxy-Kamera mit fester entity_id vorab anlegen."""
    return er.async_get(hass).async_get_or_create(
        "camera",
        DOMAIN,
        f"{entry.entry_id}_{KEY_CAMERA}",
        suggested_object_id="haustur_kamera",
        config_entry=entry,
    ).entity_id


def _homekit_entry(camera: str, *, in_options: bool = False, **kwargs) -> MockConfigEntry:
    target = {
        "name": "Haustür",
        "port": 21065,
        "mode": "accessory",
        "filter": {
            "include_domains": [],
            "exclude_domains": [],
            "include_entities": [camera],
            "exclude_entities": [],
        },
    }
    if in_options:
        return MockConfigEntry(
            domain="homekit",
            data={"name": "Haustür", "port": 21065},
            options={k: v for k, v in target.items() if k not in ("name", "port")},
            **kwargs,
        )
    return MockConfigEntry(domain="homekit", data=target, **kwargs)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    """Quellkamera-Zustand anlegen, Proxy-Kamera registrieren, Entry einrichten."""
    hass.states.async_set(CAMERA, "idle", {"friendly_name": "Eingang"})
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        entry.add_to_hass(hass)
    proxy = _register_proxy_camera(hass, entry)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return proxy


def _issue(hass: HomeAssistant, prefix: str, entry: MockConfigEntry) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{prefix}_{entry.entry_id}")


# --------------------------------------------------------------------- Issues
async def test_issues_created(hass: HomeAssistant, mock_entry) -> None:
    """Ohne HomeKit-Zubehör: fixbarer Hinweis; kein Shelly-Hinweis mehr."""
    await _setup(hass, mock_entry)
    issue = _issue(hass, ISSUE_HOMEKIT_SETUP, mock_entry)
    assert issue is not None
    assert issue.is_fixable is True
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == ISSUE_HOMEKIT_SETUP
    assert issue.translation_placeholders == {"name": "Haustür"}
    assert issue.data == {"entry_id": mock_entry.entry_id}
    assert _issue(hass, ISSUE_NOT_DETACHED_V1, mock_entry) is None
    assert _issue(hass, ISSUE_GONG_SELECT, mock_entry) is None


async def test_issue_ids(hass: HomeAssistant, mock_entry) -> None:
    """IDs der Hinweise enthalten die entry_id."""
    assert issues.homekit_issue_id(mock_entry) == f"homekit_einrichten_{mock_entry.entry_id}"
    assert issues.gong_issue_id(mock_entry) == f"gong_waehlen_{mock_entry.entry_id}"


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"in_options": True}, {"disabled_by": ConfigEntryDisabler.USER}],
    ids=["data", "options", "deaktiviert"],
)
async def test_homekit_issue_absent_with_accessory(
    hass: HomeAssistant, mock_entry, kwargs
) -> None:
    """Vorhandenes Zubehör (data/options, auch deaktiviert) → kein HomeKit-Hinweis."""
    _homekit_entry(PROXY_CAMERA, **kwargs).add_to_hass(hass)
    await _setup(hass, mock_entry)
    assert _issue(hass, ISSUE_HOMEKIT_SETUP, mock_entry) is None


async def test_homekit_issue_other_entries(
    hass: HomeAssistant, mock_entry
) -> None:
    """Bridge-Modus, andere Kamera oder kaputte Daten zählen nicht."""
    MockConfigEntry(domain="homekit", data={"mode": "bridge"}).add_to_hass(hass)
    MockConfigEntry(
        domain="homekit", data={"mode": "accessory", "filter": "kaputt"}
    ).add_to_hass(hass)
    MockConfigEntry(
        domain="homekit", data={"mode": "accessory", "filter": {}}
    ).add_to_hass(hass)
    _homekit_entry(CAMERA).add_to_hass(hass)  # Quellkamera, nicht die Proxy-Kamera
    await _setup(hass, mock_entry)
    assert _issue(hass, ISSUE_HOMEKIT_SETUP, mock_entry) is not None


async def test_homekit_issue_follows_homekit_entries(
    hass: HomeAssistant, mock_entry
) -> None:
    """Änderungen an HomeKit-Einträgen werden sofort berücksichtigt."""
    await _setup(hass, mock_entry)
    assert _issue(hass, ISSUE_HOMEKIT_SETUP, mock_entry) is not None

    hk_entry = MockConfigEntry(domain="homekit", data={"name": "x", "port": 21070})
    hk_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        hk_entry,
        options={"mode": "accessory", "filter": {"include_entities": [PROXY_CAMERA]}},
    )
    assert _issue(hass, ISSUE_HOMEKIT_SETUP, mock_entry) is None

    # Änderungen an fremden Einträgen ändern nichts
    other = MockConfigEntry(domain="sun", data={})
    other.add_to_hass(hass)
    hass.config_entries.async_update_entry(other, title="Sonne")
    assert _issue(hass, ISSUE_HOMEKIT_SETUP, mock_entry) is None

    await hass.config_entries.async_remove(hk_entry.entry_id)
    await hass.async_block_till_done()
    assert _issue(hass, ISSUE_HOMEKIT_SETUP, mock_entry) is not None

    # Nach dem Entladen der Klingel kein Listener mehr
    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_HOMEKIT_SETUP}_{mock_entry.entry_id}")
    hass.config_entries.async_update_entry(other, title="Mond")
    hk2 = MockConfigEntry(domain="homekit", data={})
    hk2.add_to_hass(hass)
    hass.config_entries.async_update_entry(hk2, title="neu")
    assert _issue(hass, ISSUE_HOMEKIT_SETUP, mock_entry) is None


async def test_issues_removed_with_entry(hass: HomeAssistant, mock_entry) -> None:
    """Löschen der Klingel entfernt HomeKit- und Gong-Hinweis."""
    await _setup(hass, mock_entry)
    ir.async_create_issue(
        hass, DOMAIN, f"{ISSUE_GONG_SELECT}_{mock_entry.entry_id}",
        is_fixable=False, severity=ir.IssueSeverity.WARNING, translation_key=ISSUE_GONG_SELECT,
    )
    assert _issue(hass, ISSUE_HOMEKIT_SETUP, mock_entry) is not None
    assert _issue(hass, ISSUE_GONG_SELECT, mock_entry) is not None
    await hass.config_entries.async_remove(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert _issue(hass, ISSUE_HOMEKIT_SETUP, mock_entry) is None
    assert _issue(hass, ISSUE_GONG_SELECT, mock_entry) is None


async def test_issue_without_proxy_camera(hass: HomeAssistant, mock_entry) -> None:
    """Fehlt die Proxy-Kamera in der Registry, gibt es kein Zubehör → Hinweis."""
    mock_entry.add_to_hass(hass)
    assert hk.async_get_proxy_camera_entity_id(hass, mock_entry) is None
    assert hk.async_has_homekit_accessory(hass, mock_entry) is False
    from custom_components.homekit_tuerklingel.issues import async_check_homekit_issue

    async_check_homekit_issue(hass, mock_entry)
    assert _issue(hass, ISSUE_HOMEKIT_SETUP, mock_entry) is not None


# ------------------------------------------------------------ homekit.py
async def test_create_accessory_camera_missing(hass: HomeAssistant, mock_entry) -> None:
    """Keine Proxy-Kamera bzw. kein Zustand → CAMERA_MISSING, kein Flow."""
    mock_entry.add_to_hass(hass)
    with patch.object(hass.config_entries.flow, "async_init") as init:
        assert await hk.async_create_homekit_accessory(hass, mock_entry) is HomeKitResult.CAMERA_MISSING
        _register_proxy_camera(hass, mock_entry)
        assert await hk.async_create_homekit_accessory(hass, mock_entry) is HomeKitResult.CAMERA_MISSING
    init.assert_not_called()


async def test_create_accessory_already_exists(hass: HomeAssistant, mock_entry) -> None:
    """Vorhandenes Zubehör → ALREADY_EXISTS."""
    mock_entry.add_to_hass(hass)
    proxy = _register_proxy_camera(hass, mock_entry)
    hass.states.async_set(proxy, "idle")
    _homekit_entry(proxy).add_to_hass(hass)
    assert await hk.async_create_homekit_accessory(hass, mock_entry) is HomeKitResult.ALREADY_EXISTS


async def test_create_accessory_import_error(hass: HomeAssistant, mock_entry) -> None:
    """HomeKit nicht importierbar → FAILED."""
    mock_entry.add_to_hass(hass)
    proxy = _register_proxy_camera(hass, mock_entry)
    hass.states.async_set(proxy, "idle")
    with patch.dict(sys.modules, {"homeassistant.components.homekit.util": None}):
        assert await hk.async_create_homekit_accessory(hass, mock_entry) is HomeKitResult.FAILED


@pytest.mark.parametrize(
    "init",
    [
        AsyncMock(side_effect=RuntimeError("kaputt")),
        AsyncMock(return_value={"type": FlowResultType.ABORT, "reason": "nein"}),
    ],
    ids=["exception", "abort"],
)
async def test_create_accessory_flow_fails(hass: HomeAssistant, mock_entry, init) -> None:
    """Fehler oder Abbruch im HomeKit-Flow → FAILED."""
    mock_entry.add_to_hass(hass)
    proxy = _register_proxy_camera(hass, mock_entry)
    hass.states.async_set(proxy, "idle")
    with (
        patch("homeassistant.components.homekit.util._get_test_socket", return_value=MagicMock()),
        patch.object(hass.config_entries.flow, "async_init", init),
    ):
        assert await hk.async_create_homekit_accessory(hass, mock_entry) is HomeKitResult.FAILED


async def test_create_accessory_real_homekit(
    hass: HomeAssistant, mock_entry
) -> None:
    """Echter HomeKit-Flow: Zubehör angelegt, eingerichtet, Klingel verknüpft.

    Nur der Start des HAP-Servers (Zeroconf/Netz) ist ersetzt.
    """
    proxy = await _setup(hass, mock_entry)
    assert proxy == PROXY_CAMERA
    used = hk.HOMEKIT_START_PORT
    MockConfigEntry(domain="homekit", data={"name": "Bridge", "port": used}).add_to_hass(hass)
    with (
        patch("homeassistant.components.homekit.util._get_test_socket", return_value=MagicMock()),
        patch("homeassistant.components.homekit.HomeKit.async_start", AsyncMock()) as start,
    ):
        result = await hk.async_create_homekit_accessory(hass, mock_entry)
        await hass.async_block_till_done()
    assert result is HomeKitResult.CREATED
    entries = hk.async_homekit_accessory_entries(hass, proxy)
    assert len(entries) == 1
    hk_entry = entries[0]
    assert hk_entry.state is ConfigEntryState.LOADED
    assert hk_entry.data["port"] == used + 1
    assert hk_entry.options["entity_config"] == {proxy: {"video_codec": "copy"}}
    assert hk_entry.options["mode"] == "accessory"
    # Beim Laden von homekit starten alle Einträge (Bridge-Attrappe + neues Zubehör)
    # sofort, da HA bereits läuft.
    assert start.await_count == 2

    # Hinweis ist über den Dispatcher bereits verschwunden
    assert _issue(hass, ISSUE_HOMEKIT_SETUP, mock_entry) is None

    # HomeKit verknüpft das Klingel-Event desselben Geräts mit der Kamera
    homekit = hk_entry.runtime_data.homekit
    states = await homekit.async_configure_accessories()
    assert [s.entity_id for s in states] == [proxy]
    ent_reg = er.async_get(hass)
    doorbell = [
        e.entity_id
        for e in er.async_entries_for_config_entry(ent_reg, mock_entry.entry_id)
        if e.domain == "event"
    ]
    assert len(doorbell) == 1
    assert homekit._config[proxy]["linked_doorbell_sensor"] == doorbell[0]

    # Zweiter Versuch: bereits vorhanden
    assert await hk.async_create_homekit_accessory(hass, mock_entry) is HomeKitResult.ALREADY_EXISTS
    assert await hass.config_entries.async_unload(hk_entry.entry_id)


# ------------------------------------------------------------- Reparatur-Flow
async def _start_fix_flow(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    assert await async_setup_component(hass, "repairs", {})
    flow_mgr = hass.data["repairs"]["flow_manager"]
    result = await flow_mgr.async_init(
        DOMAIN, context={"issue_id": f"{ISSUE_HOMEKIT_SETUP}_{entry.entry_id}"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    return result


async def _confirm(hass: HomeAssistant, flow_id: str) -> dict:
    return await hass.data["repairs"]["flow_manager"].async_configure(flow_id, {})


async def test_fix_flow_created(hass: HomeAssistant, mock_entry) -> None:
    """Bestätigen → Zubehör angelegt, Hinweis verschwindet."""
    await _setup(hass, mock_entry)
    result = await _start_fix_flow(hass, mock_entry)
    assert result["description_placeholders"] == {"camera_entity_id": PROXY_CAMERA}
    with (
        patch("homeassistant.components.homekit.util._get_test_socket", return_value=MagicMock()),
        patch("homeassistant.components.homekit.HomeKit.async_start", AsyncMock()),
    ):
        result = await _confirm(hass, result["flow_id"])
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _issue(hass, ISSUE_HOMEKIT_SETUP, mock_entry) is None
    assert hk.async_has_homekit_accessory(hass, mock_entry) is True
    for hk_entry in hass.config_entries.async_entries("homekit"):
        assert await hass.config_entries.async_unload(hk_entry.entry_id)


async def test_fix_flow_already_exists(hass: HomeAssistant, mock_entry) -> None:
    """Zubehör inzwischen vorhanden → Abbruch already_exists, Hinweis gelöscht."""
    await _setup(hass, mock_entry)
    result = await _start_fix_flow(hass, mock_entry)
    _homekit_entry(PROXY_CAMERA).add_to_hass(hass)  # ohne Dispatcher-Signal
    result = await _confirm(hass, result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_exists"
    assert result["description_placeholders"] == {"camera_entity_id": PROXY_CAMERA}
    assert _issue(hass, ISSUE_HOMEKIT_SETUP, mock_entry) is None


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [(HomeKitResult.CAMERA_MISSING, "camera_missing"), (HomeKitResult.FAILED, "homekit_failed")],
)
async def test_fix_flow_abort(
    hass: HomeAssistant, mock_entry, outcome, reason
) -> None:
    """Kamera fehlt bzw. HomeKit-Fehler → Abbruch, Hinweis bleibt."""
    await _setup(hass, mock_entry)
    result = await _start_fix_flow(hass, mock_entry)
    with patch(
        "custom_components.homekit_tuerklingel.repairs.async_create_homekit_accessory",
        AsyncMock(return_value=outcome),
    ):
        result = await _confirm(hass, result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    assert _issue(hass, ISSUE_HOMEKIT_SETUP, mock_entry) is not None


async def test_fix_flow_camera_missing_real(
    hass: HomeAssistant, mock_entry
) -> None:
    """Proxy-Kamera ohne Zustand (z. B. Plattform noch nicht geladen) → camera_missing."""
    await _setup(hass, mock_entry)
    result = await _start_fix_flow(hass, mock_entry)
    hass.states.async_remove(PROXY_CAMERA)
    result = await _confirm(hass, result["flow_id"])
    assert result["reason"] == "camera_missing"


async def test_fix_flow_entry_gone(hass: HomeAssistant, mock_entry) -> None:
    """Hinweis zu einem nicht (mehr) vorhandenen Entry → Platzhalter '?', camera_missing."""
    await _setup(hass, mock_entry)  # lädt die Integration (repairs.py)
    ir.async_create_issue(
        hass, DOMAIN, f"{ISSUE_HOMEKIT_SETUP}_weg", is_fixable=True,
        severity=ir.IssueSeverity.WARNING, translation_key=ISSUE_HOMEKIT_SETUP,
        translation_placeholders={"name": "x"}, data={"entry_id": "weg"},
    )
    assert await async_setup_component(hass, "repairs", {})
    flow_mgr = hass.data["repairs"]["flow_manager"]
    result = await flow_mgr.async_init(DOMAIN, context={"issue_id": f"{ISSUE_HOMEKIT_SETUP}_weg"})
    assert result["description_placeholders"] == {"camera_entity_id": "?"}
    result = await flow_mgr.async_configure(result["flow_id"], {})
    assert result["reason"] == "camera_missing"


async def test_fix_flow_placeholder_source_camera(hass: HomeAssistant, mock_entry) -> None:
    """Ohne Proxy-Kamera in der Registry zeigt der Flow die Quellkamera."""
    mock_entry.add_to_hass(hass)
    flow = await async_create_fix_flow(
        hass, f"{ISSUE_HOMEKIT_SETUP}_{mock_entry.entry_id}", None
    )
    assert isinstance(flow, HomeKitSetupRepairFlow)
    flow.hass = hass
    assert flow._camera_entity_id() == CAMERA


async def test_create_fix_flow_other_issue(hass: HomeAssistant) -> None:
    """Unbekannte Hinweise bekommen den Standard-Bestätigungsflow."""
    from homeassistant.components.repairs import ConfirmRepairFlow

    flow = await async_create_fix_flow(hass, "irgendwas", None)
    assert isinstance(flow, ConfirmRepairFlow)
    flow = await async_create_fix_flow(hass, f"{ISSUE_HOMEKIT_SETUP}_abc", {})
    assert isinstance(flow, HomeKitSetupRepairFlow)
    assert flow._entry_id == "abc"
