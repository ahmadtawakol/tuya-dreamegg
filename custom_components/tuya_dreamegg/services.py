"""Bounded DP 10 transport diagnostics using the existing Tuya session."""

from typing import Any

import tinytuya
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from tinytuya import scanner
from tuya_sharing.exceptions import ApiRequestException

from .const import DOMAIN, DP_MUSIC_SET, TUYA_DOMAIN
from .helpers import is_supported_device
from .music import MUSIC_DP_ID, MUSIC_NAMES

TEST_MUSIC_TRANSPORT = "test_music_transport"
TRANSPORTS = ("code", "dp_id", "local_probe", "local_test")


def _resolve_device(hass: HomeAssistant, registry_id: str) -> tuple[Any, Any]:
    """Resolve only a supported clock in a loaded companion account."""
    registry_device = dr.async_get(hass).async_get(registry_id)
    if registry_device is not None:
        for domain, device_id in registry_device.identifiers:
            if domain != TUYA_DOMAIN:
                continue
            for entry in hass.config_entries.async_entries(DOMAIN):
                if entry.state is not ConfigEntryState.LOADED:
                    continue
                runtime = entry.runtime_data
                device = runtime.device(device_id)
                if device is not None and is_supported_device(device):
                    return device, runtime
    raise ServiceValidationError("Select a loaded Dreamegg Sunrise 1+ device")


def _test_cloud(manager: Any, device_id: str, transport: str, option: str) -> dict:
    """Use the exact SDK command endpoint and retain its actual response."""
    command = (
        {"code": DP_MUSIC_SET, "value": option}
        if transport == "code"
        else {"dpId": MUSIC_DP_ID, "value": option}
    )
    try:
        response = manager.customer_api.post(
            f"/v1.1/m/thing/{device_id}/commands", None, {"commands": [command]}
        )
    except ApiRequestException as error:
        return {
            "accepted": False,
            "error_code": error.error_code,
            "error_message": error.error_message,
        }
    except Exception as error:
        return {"accepted": False, "error_type": type(error).__name__}
    if not isinstance(response, dict):
        return {"accepted": False, "error_message": "No cloud response"}
    result = {
        "accepted": response.get("success") is True
        and response.get("result") is not False
    }
    if isinstance(response.get("result"), bool):
        result["command_result"] = response["result"]
    return result


def _music_value(status: Any) -> str | None:
    """Read a valid enum value from an actual LAN status response."""
    if isinstance(status, dict) and isinstance(status.get("dps"), dict):
        value = str(status["dps"].get(str(MUSIC_DP_ID)))
        if value in MUSIC_NAMES:
            return value
    return None


def _test_local(device: Any, transport: str, option: str) -> dict:
    """Probe the matching LAN clock, or test DP 10 and restore its value."""
    local_key = getattr(device, "local_key", None)
    if not isinstance(local_key, str) or not local_key:
        return {"local_key_available": False, "discovered": False}
    result: dict[str, Any] = {"local_key_available": True}
    clock = None
    try:
        discovered = scanner.devices(
            verbose=False,
            scantime=8,
            poll=False,
            forcescan=False,
            byID=True,
            wantids=(device.id,),
        ).get(device.id)
        if not discovered:
            return result | {"discovered": False}
        result.update(discovered=True, protocol_version=discovered["version"])
        clock = tinytuya.Device(
            device.id,
            address=discovered["ip"],
            local_key=local_key,
            version=float(discovered["version"]),
            connection_timeout=3,
            connection_retry_limit=1,
            connection_retry_delay=0,
            persist=True,
        )
        before = clock.status()
        baseline = _music_value(before)
        if baseline is None and isinstance(before, dict) and "dps" in before:
            clock.set_dpsUsed({"1": None, str(MUSIC_DP_ID): None})
            before = clock.status()
            baseline = _music_value(before)
        result["music_before"] = baseline
        if isinstance(before, dict):
            result["status_error"] = before.get("Error")
            result["status_error_code"] = before.get("Err")
        if transport == "local_probe" or baseline is None:
            return result
        if baseline == option:
            return result | {"unchanged": True, "write_verified": False}
        try:
            clock.set_value(MUSIC_DP_ID, option)
            result["music_after"] = _music_value(clock.status())
            result["write_verified"] = result["music_after"] == option
        finally:
            clock.set_value(MUSIC_DP_ID, baseline)
            result["music_restored"] = _music_value(clock.status())
            result["restore_verified"] = result["music_restored"] == baseline
        return result
    except Exception as error:
        result["error_type"] = type(error).__name__
        return result
    finally:
        if clock is not None:
            clock.close()


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register one explicit diagnostic action, limited to Music DP 10."""
    if hass.services.has_service(DOMAIN, TEST_MUSIC_TRANSPORT):
        return

    async def async_test_music_transport(call: ServiceCall) -> dict[str, Any]:
        device, runtime = _resolve_device(hass, call.data["device_id"])
        transport = call.data["transport"]
        option = call.data["option"]
        if transport.startswith("local_"):
            async with runtime.music.operation_lock:
                result = await hass.async_add_executor_job(
                    _test_local, device, transport, option
                )
        else:
            result = await hass.async_add_executor_job(
                _test_cloud, runtime.manager, device.id, transport, option
            )
        return {"transport": transport, "dp_id": MUSIC_DP_ID, "option": option} | result

    hass.services.async_register(
        DOMAIN,
        TEST_MUSIC_TRANSPORT,
        async_test_music_transport,
        schema=vol.Schema(
            {
                vol.Required("device_id"): str,
                vol.Required("transport"): vol.In(TRANSPORTS),
                vol.Optional("option", default="18"): vol.In(MUSIC_NAMES),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )


@callback
def async_remove_services_if_unused(hass: HomeAssistant, unloading_id: str) -> None:
    """Remove the action after the last companion account unloads."""
    if not any(
        entry.entry_id != unloading_id and entry.state is ConfigEntryState.LOADED
        for entry in hass.config_entries.async_entries(DOMAIN)
    ):
        hass.services.async_remove(DOMAIN, TEST_MUSIC_TRANSPORT)
