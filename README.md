# Dreamegg Sunrise Controls

A small Home Assistant custom integration that adds the controls currently
missing from the official Tuya integration for the **Dreamegg Sunrise 1+**.

It reuses Home Assistant's official Tuya session. It does not ask for Tuya
developer credentials, replace the built-in Tuya integration, or require you to
pair the clock again.

## Added entities

For every supported Dreamegg in the selected Tuya account, the integration adds:

- **Countdown** — 0 to 1,440 minutes
- **Display brightness** — 0 to 100
- **Time format** — 12-hour or 24-hour
- **Work mode** — Scene, Custom scene, or Colour
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

These are not writable Home Assistant controls yet. The official Tuya
Device-Sharing command interface sends datapoint codes, but these raw table DPs
have no code in the device specification or local strategy. A verified outbound
raw-DP route is needed before safely adding alarm or routine editors.

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

This project uses internal details of Home Assistant's Tuya integration and may
need an update if those internals change.
