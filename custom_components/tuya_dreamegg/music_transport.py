"""Local Music DP 10 transport with device-confirmed readback."""

from asyncio import Lock
from collections.abc import Callable
from typing import Any

import tinytuya
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from tinytuya import scanner

from .capture import RawDpCapture
from .music import MUSIC_DP_ID, MUSIC_NAMES


class LocalMusicTransport:
    """Reuse the current official Tuya local key without storing credentials."""

    def __init__(
        self,
        hass: HomeAssistant,
        capture: RawDpCapture,
        device_provider: Callable[[str], Any | None],
    ) -> None:
        self._hass = hass
        self._capture = capture
        self._device_provider = device_provider
        self._endpoints: dict[str, tuple[str, float]] = {}
        self._lock = Lock()

    @property
    def operation_lock(self) -> Lock:
        """Serialize explicit diagnostics with normal music reads/writes."""
        return self._lock

    async def async_read(self, device_id: str) -> str:
        """Read the clock's actual selection."""
        return await self._async_operate(device_id, None)

    async def async_write(self, device_id: str, option: str) -> str:
        """Set only DP 10 and verify its readback."""
        if option not in MUSIC_NAMES:
            raise HomeAssistantError("Unsupported Dreamegg music value")
        return await self._async_operate(device_id, option)

    async def _async_operate(self, device_id: str, option: str | None) -> str:
        async with self._lock:
            device = self._device_provider(device_id)
            if device is None:
                raise HomeAssistantError("The official Tuya integration is unavailable")
            value = await self._hass.async_add_executor_job(
                self._operate, device, option
            )
            self._capture.record_local_music(device_id, value)
            return value

    @staticmethod
    def _read_music(clock: Any) -> str:
        status = clock.status()
        if isinstance(status, dict) and isinstance(status.get("dps"), dict):
            if str(MUSIC_DP_ID) not in status["dps"]:
                clock.set_dpsUsed({"1": None, str(MUSIC_DP_ID): None})
                status = clock.status()
            if isinstance(status, dict) and isinstance(status.get("dps"), dict):
                value = str(status["dps"].get(str(MUSIC_DP_ID)))
                if value in MUSIC_NAMES:
                    return value
        raise HomeAssistantError("The clock did not return a valid Music DP 10 value")

    def forget_clock(self, device_id: str) -> None:
        """Drop a cached LAN endpoint so the next session rediscovers the clock."""
        self._endpoints.pop(device_id, None)

    def open_clock(self, device: Any) -> Any:
        """Open a LAN session to one clock. Blocking: call from the executor.

        The light transport shares this session factory, endpoint cache and
        ``operation_lock`` so the clock only ever sees one local session.
        """
        key = getattr(device, "local_key", None)
        if not isinstance(key, str) or not key:
            raise HomeAssistantError("Tuya did not provide this clock's local key")
        if device.id not in self._endpoints:
            try:
                found = scanner.devices(
                    verbose=False,
                    scantime=8,
                    poll=False,
                    forcescan=False,
                    byID=True,
                    wantids=(device.id,),
                ).get(device.id)
            except Exception as error:
                raise HomeAssistantError(
                    "Unable to discover the clock on the LAN"
                ) from error
            if not found:
                raise HomeAssistantError(
                    "The clock was not found on Home Assistant's LAN"
                )
            try:
                address, version = found["ip"], float(found["version"])
            except (KeyError, TypeError, ValueError) as error:
                raise HomeAssistantError(
                    "The clock returned invalid LAN discovery data"
                ) from error
            if not isinstance(address, str) or version not in {3.1, 3.2, 3.3, 3.4, 3.5}:
                raise HomeAssistantError(
                    "The clock returned unsupported LAN discovery data"
                )
            self._endpoints[device.id] = (address, version)
        address, version = self._endpoints[device.id]
        return tinytuya.Device(
            device.id,
            address=address,
            local_key=key,
            version=version,
            connection_timeout=3,
            connection_retry_limit=1,
            connection_retry_delay=0,
            persist=True,
        )

    def _operate(self, device: Any, option: str | None) -> str:
        clock = None
        try:
            clock = self.open_clock(device)
            value = self._read_music(clock)
            if option is not None and value != option:
                clock.set_value(MUSIC_DP_ID, option)
                value = self._read_music(clock)
                if value != option:
                    raise HomeAssistantError(
                        "The clock did not confirm the music selection"
                    )
            return value
        except HomeAssistantError:
            self.forget_clock(device.id)
            raise
        except Exception as error:
            self.forget_clock(device.id)
            raise HomeAssistantError(
                "Unable to contact the clock on the local network"
            ) from error
        finally:
            if clock is not None:
                clock.close()
