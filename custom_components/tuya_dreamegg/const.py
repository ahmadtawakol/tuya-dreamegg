"""Constants for Dreamegg Sunrise Controls."""

from homeassistant.const import Platform

DOMAIN = "tuya_dreamegg"
TUYA_DOMAIN = "tuya"

CONF_TUYA_ENTRY_ID = "tuya_entry_id"

SUPPORTED_CATEGORY = "bzyd"
SUPPORTED_PRODUCT_IDS = frozenset({"yible1syyda3s5iv"})

DP_BACKLIGHT = "backlight"
DP_COUNTDOWN = "countdown"
DP_MUSIC_SET = "music_set"
DP_STOP = "stop"
DP_TIME_MODE = "time_mode"
DP_WORK_MODE = "work_mode"

TUYA_DISCOVERY_NEW = "tuya_discovery_new"
TUYA_UPDATE_ENTITY = "tuya_entry_update"
TUYA_RAW_DP_UPDATE = "tuya_dreamegg_raw_dp_update"

PLATFORMS = (Platform.NUMBER, Platform.SELECT, Platform.BUTTON, Platform.SENSOR)
