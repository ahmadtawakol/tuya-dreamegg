# Dreamegg Sunrise Controls

A small Home Assistant custom integration that adds the controls currently
missing from the official Tuya integration for the **Dreamegg Sunrise 1+**.

It reuses Home Assistant's official Tuya session. It does not ask for Tuya
developer credentials, replace the built-in Tuya integration, or require you to
pair the clock again.

## Added entities

For every supported Dreamegg in the selected Tuya account, the integration adds:

- **Colour light** — the lamp in colour mode on the clock's own 0–1000 scale.
  The official Tuya light assumes 0–255, so it tops out at about a quarter of
  the lamp's brightness and saturation and reports out-of-range values. Use
  this entity for automations that need full brightness or saturated colours.
  Turning it on with a colour switches the clock's work mode to Colour.
- **Countdown** — 0 to 1,440 minutes
- **Display brightness** — 0 to 100
- **Time format** — 12-hour or 24-hour
- **Work mode** — Scene, Custom scene, or Colour
- **Music selection** — all 34 firmware sound IDs, with confirmed names for
  Campfire, Brown Noise 1, and Morning; other IDs show as Sound 1, Sound 2, etc.
- **Stop** — a momentary button for the device's `stop` datapoint
- **Countdown remaining** — read-only seconds from the clock's raw timer report
- **Raw datapoint sensors** — observed light brightness, colour temperature,
  music selection, scene selection, the opaque Customize Scene Set payload, and
  unidentified DP 102, with no assumed units for raw values
- **Wake Up Set / Alarm Set** — read-only enabled-slot counts with decoded
  fields in entity attributes; no schedule write control is exposed

The entities are attached to the same Home Assistant device as the official
Tuya light, switches, and volume control.

## Supported devices

| Product | Tuya category | Product ID |
| --- | --- | --- |
| Dreamegg Sunrise 1+ | `bzyd` | `yible1syyda3s5iv` |

## Prerequisites

- Home Assistant 2026.9.0 or newer
- The official **Tuya** integration configured and loaded
- The Dreamegg already visible in the official Tuya integration
- For Music selection, HA must reach the clock on its LAN (Tuya TCP 6668 and
  UDP discovery), and the existing Tuya device object must contain its local key

## Install with HACS

1. In HACS, open the three-dot menu and select **Custom repositories**.
2. Add `https://github.com/ahmadtawakol/tuya-dreamegg` as an **Integration**.
3. Open **Dreamegg Sunrise Controls** in HACS and download it.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration**.
6. Search for **Dreamegg Sunrise Controls** and select the Tuya account that
   contains your clocks.

## Manual installation

Copy `custom_components/tuya_dreamegg` into your Home Assistant configuration
directory so the final path is:

```text
config/custom_components/tuya_dreamegg
```

Restart Home Assistant, then add **Dreamegg Sunrise Controls** from
**Settings → Devices & services**.

## Removal

Remove the integration from **Settings → Devices & services**, uninstall it in
HACS, and restart Home Assistant. The official Tuya entities are unaffected.

Once Home Assistant Core includes these standard datapoint mappings in a
release, remove this integration to avoid duplicate base controls. Keep it if
you still need the alarm/routine diagnostics below.

## Alarm and routine mapping status

Diagnostics now capture two app-only schedule tables: raw DP 112 contains six
alarm records, and raw DP 15 contains six routine records. The downloaded
diagnostics decode the fields confirmed by controlled comparisons and retain
unknown bytes for further mapping. A local payload builder can edit confirmed
fields without overwriting the unknown bytes.

These are not writable Home Assistant controls yet. The full Tuya web product
schema identifies the table codes as `wake_up_set` and `alarm`, but their write
transport and payload semantics still need live validation before alarm or
routine editors can be exposed.

To collect fresh evidence:

1. Reload **Dreamegg Sunrise Controls** after installing or updating it.
2. In the Dreamegg/D26 app, edit one alarm or routine and save it.
3. In Home Assistant, open **Settings → Devices & services → Dreamegg Sunrise
   Controls → Download diagnostics**.

The integration retains at most 200 raw datapoint reports per supported clock,
in memory only. It filters out all other devices and does not log Tuya tokens or
credentials. Diagnostics also include the Tuya home scenes visible through the
official Device Sharing session.

See the current [device API investigation](docs/device-api-investigation.md) for
the evidence, likely API boundaries, and controlled capture procedure.

## How it works

The integration stores only the config-entry ID of your official Tuya account.
Commands and live updates use that integration's current Device Sharing manager,
including after the official Tuya entry reloads.

Music selection uses a local connection from HA to write numeric DP 10 with
string enum values `1` through `34`. It reuses the local key already held by
the official Tuya session and discovers the matching clock's LAN address and
protocol automatically. Every change is verified by reading the device back.
The select refreshes once per minute and also listens to raw reports; its state
is never updated optimistically. Volume and playback switches remain separate.

### Music transport diagnostics

The HA cloud gateway rejects the confirmed `music_set` code with error `2008`
and a numeric `dpId` command body with `1100`. A local HA test on protocol 3.5
successfully changed DP 10 from `18` to `10`, read it back, and restored `18`;
the Tuya web panel independently reported both changes.
Version 0.5.0 includes the **Dreamegg Sunrise Controls: Test music transport**
action to report the exact cloud error and test DP 10 by numeric ID through the
same authenticated endpoint. It also provides a read-only LAN probe and a
bounded local write test that reads the original selection, verifies a different
selection, then restores the original. Local tests use the key already held by
the official Tuya integration; keys are not stored or returned by this action.
All transport diagnostics are restricted to supported clocks and Music DP 10.

The desktop Tuya schema's sound names do not match this clock's firmware.
Selecting Campfire in the actual Dreamegg app reports DP 10 value `10`; value
`18` plays Brown Noise 1. Version 0.6.1 corrects these labels and retains the
existing Morning (`32`) mapping. Unverified values use neutral Sound ID labels
until confirmed against the native app, rather than the inaccurate stock names.

This project uses internal details of Home Assistant's Tuya integration and may
need an update if those internals change.
