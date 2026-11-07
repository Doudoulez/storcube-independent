"""Constantes de l’intégration indépendante StorCube."""

DOMAIN = "storcube_independent"
CONF_DEVICE_IDS = "device_ids"
CONF_LOGIN_NAME = "login_name"
CONF_PASSWORD = "password"
CONF_APP_CODE = "app_code"
DEFAULT_APP_CODE = "Storcube"

TOKEN_URL = "http://baterway.com/api/user/app/login"
WS_URI = "ws://baterway.com:9501/equip/info/"
SCENE_URL = "http://baterway.com/api/scene/user/list/V2"
THRESHOLD_URL = "http://baterway.com/api/scene/threshold/query"
FIRMWARE_URL = "http://baterway.com/api/equip/version/need/upgrade"
HEARTBEAT_SECONDS = 45
REST_INTERVAL_SECONDS = 60
