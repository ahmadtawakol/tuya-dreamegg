# Dreamegg Sunrise 1+ device API investigation

## Confirmed product features

Dreamegg documents 34 sounds, up to six alarms, sunrise and sunset behavior,
and daily sleep/wake routines for the Sunrise 1+. Its official how-to video
shows an alarm object with these fields:

- name and enabled state
- alarm time and repeat weekdays
- alarm sound and volume
- light brightness
- light wake-up enabled state and duration
- wake-up light selection

The same video shows routines with a name, start time, duration, sound, volume,
light, and brightness.

Sources:

- https://dreamegg.com/products/dreamegg-sunrise-1-plus
- https://dreamegg.com/pages/howtouse

## What the official Tuya session exposes

Diagnostics from two devices with product ID `yible1syyda3s5iv` expose the
same 11 writable datapoints:

| DP ID | Code | Type |
| --- | --- | --- |
| 1 | `switch` | Boolean |
| 2 | `work_mode` | Enum |
| 3 | `switch_led` | Boolean |
| 5 | `colour_data` | String/JSON |
| 8 | `switch_music` | Boolean |
| 9 | `volume_set` | Integer |
| 17 | `snooze` | Boolean |
| 18 | `stop` | Boolean |
| 20 | `countdown` | Integer |
| 21 | `time_mode` | Enum |
| 22 | `backlight` | Integer |

No alarm slot, sound selection, weekday, sunrise duration, or routine object is
present in the device instruction/status specification returned to Home
Assistant.

Tuya's Device Sharing SDK can query and trigger home scenes, and Home Assistant
already exposes those as scene entities. The SDK does not provide a timer or
alarm repository. Tuya's broader App SDK and OpenAPI do document device
schedules and cloud timers, but those interfaces are separate from the helper
surface currently available to Home Assistant's free Device Sharing session.

Sources:

- https://developer.tuya.com/en/docs/cloud/device-control?id=K95zu01ksols7
- https://developer.tuya.com/en/docs/app-development/extension-sdk-tutorial-timer?id=Kdjkom7glni25
- https://developer.tuya.com/en/docs/cloud/device-timer?id=Kconlsdnhs0u3

## Current assessment

The missing controls are probably implemented through one of these paths:

1. Tuya home scenes or automations.
2. Cloud timer records whose actions contain one or more device datapoints.
3. Product-specific raw datapoints omitted from the standard specification.
4. Private storage/API calls made by the Dreamegg device panel.

The raw DP numbering has gaps at 4, 6–7, 10–16, and 19. That is consistent
with, but does not prove, hidden product-specific functions. The fixed six-slot
alarm UI makes raw alarm-slot datapoints a plausible hypothesis.

## Evidence collection in v0.2.0

Version 0.2.0 captures raw MQTT datapoint reports for supported Dreamegg clocks
only. Reports are held in memory, limited to 200 per device, and never written
to logs or disk automatically. Downloaded diagnostics also include the home
scenes visible through the official Tuya session.

For a controlled comparison:

1. Reload **Dreamegg Sunrise Controls**.
2. Change exactly one setting in the Dreamegg app and save it.
3. Download integration diagnostics from Home Assistant.
4. Repeat separately for alarm enable, alarm time, repeat days, sound, sunrise
   duration, routine start time, and routine duration.

If a new raw DP ID/value appears, it can be mapped and tested without guessing.
If a Tuya scene changes, that scene path can be used instead. If neither
changes, the remaining route is an HTTPS capture of the app's API traffic. That
step depends on whether the app uses certificate pinning and should be done as
a separate, explicit test.
