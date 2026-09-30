"""Base entity for Dreamegg Sunrise Controls."""

from typing import Any, override

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity, EntityDescription

from . import DreameggRuntimeData
from .const import TUYA_DOMAIN, TUYA_UPDATE_ENTITY


class DreameggEntity(Entity):
    """Entity backed by the official Tuya integration's live manager."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        runtime: DreameggRuntimeData,
        device_id: str,
        description: EntityDescription,
    ) -> None:
        """Initialize a Dreamegg entity."""
        self._runtime = runtime
        self._device_id = device_id
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"
        device = runtime.device(device_id)
        device_registry = dr.async_get(runtime.hass)
        if existing_device := device_registry.async_get_device_by_identifier(
            (TUYA_DOMAIN, device_id), runtime.tuya_entry_id
        ):
            self.device_entry = existing_device
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={(TUYA_DOMAIN, device_id)},
                name=getattr(device, "name", None),
            )

    @property
    def device(self) -> Any | None:
        """Return the current device object after any Tuya reload."""
        return self._runtime.device(self._device_id)

    @property
    @override
    def available(self) -> bool:
        """Return whether the device is online."""
        return bool(
            (device := self.device) is not None and getattr(device, "online", False)
        )

    def _status_value(self) -> Any:
        """Return the current value of this entity's datapoint."""
        device = self.device
        status = getattr(device, "status", None)
        if not isinstance(status, dict):
            return None
        return status.get(self.entity_description.key)

    @override
    async def async_added_to_hass(self) -> None:
        """Subscribe to official Tuya push updates."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{TUYA_UPDATE_ENTITY}_{self._device_id}",
                self._handle_tuya_update,
            )
        )

    @callback
    def _handle_tuya_update(
        self,
        updated_status_properties: list[str] | None,
        dp_timestamps: dict[str, int] | None,
    ) -> None:
        """Write state when this datapoint or availability changes."""
        if (
            updated_status_properties is None
            or self.entity_description.key in updated_status_properties
        ):
            self.async_write_ha_state()

    async def _async_send_value(self, value: bool | int | str) -> None:
        """Send one datapoint command through the official Tuya manager."""
        manager = self._runtime.manager
        send_commands = getattr(manager, "send_commands", None)
        if not callable(send_commands) or self.device is None:
            raise HomeAssistantError("The official Tuya integration is unavailable")
        try:
            await self.hass.async_add_executor_job(
                send_commands,
                self._device_id,
                [{"code": self.entity_description.key, "value": value}],
            )
        except Exception as error:
            raise HomeAssistantError(
                "Unable to send the command to Dreamegg"
            ) from error
