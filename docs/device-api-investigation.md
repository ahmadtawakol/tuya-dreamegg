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
path is still required for the schedule/scene datapoints.

### Full web product schema and Music selection

Later on 2026-10-06, inspecting the authenticated web panel's own schema response
revealed that DP 10 is a read/write enum with the command code `music_set`.
The response is from `/open-api/v3.0/m/sdf/ss/panels/device/<id>/DESKTOP/component`.
It supplies string values `1` through `34` and stock sound labels. It names `10`
Rainstorm and `18` Campfire; these names were initially trusted but later proved
incorrect for the clock's firmware. The apparent difference from schedule sound
IDs did not establish a separate sound enumeration. See the native app capture
below for the correction.

A bounded web test sent `ctrl_dp` over the panel socket with
`{"dps":{"10":"10"},"protocol":5}`. The socket replied `ctrl_dp_res` with
status `ok`, followed by a `notify_dp` report containing `{"10":"10"}`.
Restoring the previous value sent `{"10":"18"}` and produced the corresponding
report. This confirmed numeric writes, not the audible sound labels.

Version 0.4.0 adds a Music selection entity that sends
`{"code":"music_set","value":"<enum value>"}` through the existing official
HA Tuya manager. It reads selection from raw DP 10 reports because HA's reduced
function/strategy schema omits this code. No optimistic state is set after a
command; the select updates when a report arrives. Live HA transport validation
is required in addition to the verified web write.

The full schema also names DPs 6/7 as `bright_value`/`temp_value`, DP 13 as
`customize_scene`, DP 14 as `customize_scene_set`, DP 15 as `wake_up_set`, and
DP 112 as `alarm`. Those additional writable controls are not part of the Music
selection change and their HA command behavior remains untested.

### Verified HA local Music transport

The live diagnostic action returned code `2008` for `music_set` and `1100` for
the `dpId: 10` body through the existing cloud command endpoint. Its local probe
found the same clock on HA's LAN with protocol 3.5 and an existing local key.
The local test read DP 10 as `18`, wrote `10`, read `10` back, restored `18`, and
read `18` back. The independent Tuya web socket emitted matching `notify_dp`
reports for `10` and `18`.

Version 0.6.0 uses this confirmed local transport for Music selection. The
clock's current key is resolved from the official HA Tuya device object on each
operation; no new credential is stored. The discovered IP/protocol is cached
only in memory, with rediscovery after an error. The control writes only DP 10,
verifies the actual value, and refreshes it once per minute. Other existing
controls continue using their established cloud manager. The colour-light patch
is retained in the same release.

### Native app sound labels supersede desktop stock labels

After v0.6.0, the user reported that selecting HA's Campfire kept playing Brown
Noise. HA and the clock both reported DP 10 `18`. The user then selected Campfire
in the actual Dreamegg app, and the independent device socket reported
`{"10":"10"}`. Thus Campfire is firmware value `10`; value `18` is Brown Noise 1,
consistent with the native schedule mapping previously recorded. The existing
Morning `32` match is retained.

Version 0.6.1 corrects these labels in the select and diagnostic sensor. Other
direct sound IDs remain available as Sound 1, Sound 2, etc. Their desktop stock
names are removed until native app/playback evidence confirms them. The local
transport itself required no change: it was writing and reading the requested
numeric values correctly. Native capture fixtures prevent the desktop labels
from being reintroduced accidentally.

The user additionally selected Harp in the native app, which the independent
socket reported as `{"10":"34"}`. The old desktop label called `34` Cheerful.
Version 0.6.2 corrects it to Harp; the subsequent native Campfire selection
reported `{"10":"10"}` again.

The user subsequently supplied the complete native sound ID list, 1–34, and
clarified that ID 17 is Pink Noise 2. Version 0.6.3 applies that catalog to the
Music select, its diagnostic sensor, and decoded alarm/routine sound fields.
The native catalog also matches the previously observed schedule sound IDs;
these consumers now share one source map. Numeric command values and transport
behavior are unchanged. All 34 labels are covered by the native source fixture
and translation/schedule regression checks.
