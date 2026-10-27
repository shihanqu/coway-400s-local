# Observed legacy 400S protocol

These details were recovered from a real AP-2015E with a WizFi250 module. They are observations, not a complete specification for other Coway models.

## Device connection

The device looked up `iocgwo.coway.co.kr` using `8.8.8.8:53`, then connected with TLS 1.0 to TCP 9090. It accepted a locally generated RSA/SHA-1 self-signed certificate. No app or account token was present in the implemented command exchange.

```text
STX | 0101 | serial[18] | MAC[12 hex ASCII] | field[16]
    | length[4 hex ASCII] | payload | checksum[2 hex ASCII] | ETX
```

- STX/ETX are bytes `02` and `03`.
- All observed 16-character fields were `FFFFFFFFFFFFFFFF`. Its general meaning is unknown.
- `length = len(payload) + 3`, counting checksum and ETX.
- `checksum = sum(all bytes from STX through payload) & 0xff`.

## Observed messages

| Direction | Payload | Meaning supported by observation |
| --- | --- | --- |
| Device → server | `A1000QMV...` | Initial version-looking message |
| Server → device | `A1000SG` | Acknowledgement that enabled subsequent traffic |
| Server → device | `A1012QG` | Request current operating state |
| Device → server | `A1012SM` + map | State response |
| Server → device | `A1011QG` + map | Write setting |
| Device → server | `A1011SM` | Setting acknowledgement |
| Device → server | `A1010RM` + map | Operating-state notification |
| Server → device | `A1010SG` | Notification acknowledgement |
| Device → server | `A1020RM` + map | Sensor notification |
| Server → device | `A1020SG` | Sensor acknowledgement |

Map format is a four-hex-digit count, then that many pairs of four-hex-digit keys and four-hex-digit unsigned values. For example, speed 2:

```text
A1011QG 0001 0003 0002
```

Spaces above are explanatory and are not transmitted.

| Attribute | Observed mapping |
| --- | --- |
| `0001` | Power; 1 observed on |
| `0002` | Mode; 0 observed with manual fan speed |
| `0003` | Fan speed: 1, 2, 3 |
| `0007` | Lighting: 0 off, 2 on |
| `000A` | Sensitivity: 1 Sensitive, 2 Moderate, 3 Insensitive |

Only the captured settings above are writable through this project. The generic numeric map is not exposed as an unrestricted control endpoint.

## App-free Wi-Fi setup

In pairing mode, the observed open network was `Airmega_400s`; the device gateway was `192.168.12.101`, TCP port 5000.

```text
STX | length[2 hex ASCII] | command[2 hex ASCII] | UTF-8 payload
    | checksum[2 hex ASCII] | ETX
```

Here `length = payload bytes + 5`; the checksum uses the same sum rule. Send command 1 (SSID), 2 (password), 3 (18-character serial), then 4 (two zero bytes). Valid command `FE` replies acknowledge setup messages. The radio can switch before the final reply arrives.

App-free provisioning was observed before the investigation unit was registered. Local operation was verified after registration and with its internet blocked, including after a power cycle. A factory-fresh, never-registered unit remains an end-to-end validation gap.
