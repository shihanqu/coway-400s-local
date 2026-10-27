# Coway 400S Local

Control a **Coway Airmega 400S (AP-2015E, WizFi250)** over your local network: factory fan speeds **1 / 2 / 3**, lighting, sensitivity, and fresh device state. The controller runs on an Ethernet or Wi-Fi computer and keeps working with the purifier's internet access blocked.

You do **not** need to repeat the reverse engineering, capture traffic, or run the Coway app. An optional pairing command sends your Wi-Fi settings directly to the purifier.

**Validation scope:** working on one AP-2015E/WizFi250; the complete setup on a factory-fresh, never-registered unit remains untested. See the verification table below.

**The unavoidable setup step:** stock firmware contacts a hard-coded DNS server. Your router must redirect **this purifier's DNS requests** to the local controller. Changing the router's normal DHCP DNS setting alone is insufficient.

## Quick start

Requirements: an always-on computer with Docker Compose, a configurable router, and the purifier's 18-character label serial. The two helper scripts use Python 3.10+ without extra packages. The controller's Python version and OpenSSL are supplied by Docker.

### 1. Start the controller

```sh
git clone https://github.com/shihanqu/coway-400s-local.git
cd coway-400s-local
python3 tools/setup.py
docker compose up -d --build
```

The wizard asks for the label serial and the **server computer's stable LAN IP**. It creates a private `.env`; certificates, device identity, and the API token are generated locally in a persistent Docker volume.

Alternatively, copy `.env.example` to `.env` and fill in `COWAY_SERIAL` and `COWAY_HOST_IP` before starting Compose.

### 2. Put the purifier on Wi-Fi, if needed

**Skip this step if it already joins your home Wi-Fi.**

On a Wi-Fi-equipped computer with this checkout:

1. Turn on the purifier and hold **Wi-Fi + Light** for more than three seconds.
2. Connect that computer to **Airmega_400s**.
3. Run:

```sh
python3 tools/pair.py
```

Enter your 2.4 GHz Wi-Fi name and password. The password is entered privately and is never saved. Then reconnect the computer to your normal network. The final setup reply can disappear as the purifier switches Wi-Fi; check your router before retrying.

The always-on controller computer does **not** need a Wi-Fi adapter. Only the computer doing this optional pairing step does.

### 3. Redirect DNS for this purifier, then restart it

Reserve stable IPs for the controller and purifier. On the router:

- Redirect the purifier's **UDP traffic to `8.8.8.8:53`** to **`CONTROLLER_IP:1053`**.
- Provide the reply path, usually a narrowly scoped source-NAT rule when both are on the same LAN.
- Block the purifier's internet access while allowing it to reach the controller.

See the [exact UniFi fields and generic packet path](docs/network.md). These are per-device rules; your other devices keep their usual DNS.

Power-cycle the purifier normally after configuring the rules. Do not enter pairing mode again.

```sh
docker compose exec coway coway400s status
docker compose exec coway coway400s speed 2
```

A successful setting command waits for the device acknowledgement **and queries the setting back**. If the purifier is unavailable, it returns an error instead of claiming the setting changed.

## Controls

```sh
docker compose exec coway coway400s speed 1
docker compose exec coway coway400s speed 2
docker compose exec coway coway400s speed 3
docker compose exec coway coway400s light off
docker compose exec coway coway400s light on
docker compose exec coway coway400s sensitivity moderate
```

Sensitivity choices: `sensitive`, `moderate`, `insensitive`. The purifier must be on before changing settings. Speed is a factory step, not a percentage or RPM. Power switching, arbitrary PWM, and other models are not implemented.

An [authenticated JSON API](docs/api.md) is available for dashboards and automation. Its Docker port is published on **localhost only** by default. The device listener and DNS listener must remain reachable from the purifier's LAN. Do not forward these ports from the internet.

## What is verified?

Tested on a real **400S / AP-2015E containing FCC ID XR2WIZFI250**:

| Behavior | Evidence |
| --- | --- |
| Direct Wi-Fi setup without an app | SSID, password and serial acknowledged; router join confirmed |
| Local startup and status | Actual device connected to the replacement server and returned fresh state |
| Fan speeds | All three app commands decoded; local physical changes 3 → 2 → 3 confirmed |
| Reconnect after power cycle | Fresh startup and speed 2 readback with the cloud blocked |
| Lighting and sensitivity | Real app commands captured and matched; separate local physical tests remain unverified |

**Fresh-unit limitation:** the investigation unit was registered with Coway once to discover the commands. App-free Wi-Fi setup and subsequent local control were verified separately. The complete sequence on a factory-fresh, never-registered unit has not yet been tested. No account, registration, or cloud client exists in this controller; reports from fresh units are welcome.

Newer Bluetooth-equipped 400S revisions and other Airmega models are untested. Check your module/label before expecting compatibility.

## Native installation

With Python **3.13+** and OpenSSL installed:

```sh
python3 -m venv .venv
.venv/bin/pip install .
python3 tools/setup.py
.venv/bin/coway400s serve
```

In another terminal, run `.venv/bin/coway400s status` or `.venv/bin/coway400s speed 2`. Configuration is loaded from `.env` and overridden by environment variables. Runtime data defaults to `.coway/`; `COWAY_DATA_DIR` changes it.

The older Wi-Fi module requires **TLS 1.0, RSA/AES and a SHA-1-signed local certificate**. This compatibility is restricted to the purifier listener; no system trust store or global TLS settings are changed. Each installation generates its own key and token. Put this device on a trusted or isolated IoT network.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

Tests use synthetic identities and loopback connections. Personal identifiers, Wi-Fi credentials, keys, account data, app binaries and original captures are excluded from this repository.

See [protocol notes](docs/protocol.md) for the observed wire format. Background: [Josh Spicer's earlier Airmega investigation](https://joshspicer.com/hack-air-purifier/). This project is independent of Coway.

MIT license.
