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

The gaps in standard DP numbering suggested hidden product-specific functions.
Later raw captures confirmed separate six-slot alarm and routine tables.

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

## Decoded schedule reports

Later diagnostics exposed two separate, base64-encoded 120-byte raw datapoints:

- DP `112` contains six alarm records.
- DP `15` contains six routine records.

Each table is six 20-byte records. Controlled app edits support these mappings
within each record (offsets are zero-based):

| Offset | Meaning | Evidence |
| --- | --- | --- |
| 0 | Enabled | Alarm and routine cards follow the boolean value |
| 2 | Light preset/mode code | Mode changes with the app's selected light style |
| 9–10 | Light brightness, big-endian, 0–1000 | 100% → 90% changed 1000 → 900 |
| 12 | Sound ID | Bird → Sea Wave changed 1 → 2 |
| 13 | Sound volume, 0–100 | 100% → 90% changed 100 → 90 |
| 14–15 | Start time in minutes after midnight, big-endian | 06:00 → 06:02 changed 360 → 362 |
| 16–17 | Duration in minutes, big-endian | A 15 → 30 minute edit changed the low byte |
| 18 | Repeat-day bitmask; bit 0 is Sunday through bit 6 Saturday | Everyday → Monday–Saturday changed 127 → 126 |
| 19 | Alarm Wake-Up Light or routine WindDown Light enabled | The field follows the corresponding app toggle |

Offsets 1, 3–8, and 11 are not fully understood. Light mode codes 2, 3, and 4
were observed as Solid Color, Sunlight, and Sunrise, respectively; the exact
meaning of all related color bytes remains incomplete. Confirmed sound IDs are
1 Bird, 2 Sea Wave, 8 Rainstorm, 15 White Noise, 18 Brown Noise 1, 20 Green
Noise, and 32 Morning. Other sound labels have not been verified. Routine names
follow the six UI slots, but neither schedule table contains names as strings.

DP 104 is the countdown-remaining value in seconds: captures show it decreasing
from values such as 600, 1800, and 9420 to zero, with one-second reports during
the final minute. The custom integration exposes this as a read-only sensor.

On 2026-10-06, the Tuya Smart Life Web device log exposed these product labels:

| DP ID | Tuya Web label | Evidence / limits |
| --- | --- | --- |
| 6 | Brightness | Device-log reports include 30–1000; observed only, not a confirmed spec range |
| 7 | Colour Temperature | Reports include 0–1000; observed only, unit/range semantics still unknown |
| 10 | Music | Sound selection ID; raw `32` matches Morning in the routine table |
| 13 | Scene | The panel offers Mode1–Mode8; exact values and write mapping not established |
| 14 | Customize Scene Set | Opaque base64 scene payload; layout not decoded |
| 15 | Wake Up Set | Its 120-byte base64 value matches the six-record routine table decoded above |
| 17 | Snooze | Matches the advertised `snooze` command code |
| 18 | Alarm Stop | Matches the advertised `stop` command code |

The panel showed brightness 130, colour temperature 0, Campfire selected while
Music Switch was off, Scene Mode1, and a Wake Up Set report. This confirms
labels and current UI values, but not a writable command code for DPs 6, 7, 10,
13, 14, or 15. Those IDs are absent from the official Tuya device's
`function`/`local_strategy` command map used by Home Assistant's code-based
manager. DP 112 remains the separate six-record alarm table and is not exposed
in the web datapoint filter. DP 102 still reports `1` and remains unidentified.
The panel also showed Alarm master switch on, Alarm start slot 1, and Schedule
start slot 6, but did not expose raw IDs or enough evidence to map those
controls. No device control was changed during this inspection.

The custom integration now exposes read-only raw sensors for DP 6, 7, 10, 13,
14, and 102, plus enabled-slot summaries with decoded fields for DP 15 and 112.
These are useful for HA dashboards and future mapping but do not send commands.
The official Tuya Device Sharing manager currently sends commands by datapoint
code, and IDs 6, 7, 10, 13, 14, 15, 102, and 112 are absent from the device's
advertised `function`/`local_strategy` command map. A verified outbound raw-DP
path is still required before writable controls for those datapoints can be
added safely.
