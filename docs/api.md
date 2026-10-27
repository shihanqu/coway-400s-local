# JSON API

All control/state endpoints require `Authorization: Bearer TOKEN`. Read the generated token with:

```sh
docker compose exec coway coway400s token
```

Treat it as a private control credential. The CLI automatically reads it when running in the container or with access to the same data directory.

| Method | Path | JSON body |
| --- | --- | --- |
| GET | `/health` | None; unauthenticated process health and connection presence |
| GET | `/api/state` | None; fresh device state |
| POST | `/api/speed` | `{"value": 2}`; choices 1, 2, 3 |
| POST | `/api/light` | `{"value": "on"}`; on, off |
| POST | `/api/sensitivity` | `{"value": "moderate"}`; sensitive, moderate, insensitive |

Successful response:

```json
{"ok": true, "connected": true, "power": 1, "speed": 2, "mode": 0, "light": "on", "sensitivity": "moderate", "attributes": {"0001": 1, "0003": 2}}
```

Actual responses include the complete attribute map returned by the purifier. Mode 0 was observed during manual speed control; other mode meanings are not implemented as controls.

Setting operations serialize requests, read state, send a captured setting command, wait for its acknowledgement, then read the setting back. Errors return `ok: false` and a non-success HTTP status. The CLI also exits nonzero on an error. There are no automatic setting retries.

## Access from another computer

The Compose file publishes the API on `127.0.0.1:8080` by default. To permit another trusted host, change that port binding to the controller's **specific private LAN address**, restrict the host firewall to the caller, and supply the bearer token to that caller. An SSH tunnel is another option. Plain HTTP is intended for localhost or a trusted protected transport; the bearer token is not encrypted by HTTP itself.

The device's TLS listener on 9090 is separate from this control API. Wi-Fi is not required on the computer hosting either service.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `COWAY_SERIAL` | Required | Label serial, 18 characters |
| `COWAY_HOST_IP` | Required | Address returned in local DNS answers |
| `COWAY_DEVICE_IP` | Empty | Optional allowed TLS peer IP |
| `COWAY_DATA_DIR` | `.coway` (`/data` in Docker) | Generated key, certificate, token and learned identity |
| `COWAY_BIND` | `0.0.0.0` | Device/DNS bind address |
| `COWAY_TLS_PORT` | `9090` | Purifier TLS port; stock device expects 9090 |
| `COWAY_DNS_PORT` | `1053` | DNS redirect target |
| `COWAY_API_BIND` | `127.0.0.1` (`0.0.0.0` inside Docker) | API bind address |
| `COWAY_API_PORT` | `8080` | API port |
| `COWAY_URL` | `http://127.0.0.1:8080` | CLI target URL |
| `COWAY_API_TOKEN` | Read from local data directory | CLI token for a remote server |

Changing listener ports also requires corresponding Compose/router changes. Do not publish your `.env` or data directory.
