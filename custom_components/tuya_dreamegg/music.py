"""DP 10 sound labels verified against the Dreamegg app and playback."""

MUSIC_DP_ID = 10

# Desktop Tuya enum labels are not accurate for this firmware. Preserve all
# valid sound values, but name only those backed by native app/playback evidence.
VERIFIED_MUSIC_NAMES = {
    "10": "Campfire",
    "18": "Brown Noise 1",
    "32": "Morning",
    "34": "Harp",
}
MUSIC_NAMES = {
    str(music_id): VERIFIED_MUSIC_NAMES.get(str(music_id), f"Sound {music_id}")
    for music_id in range(1, 35)
}
