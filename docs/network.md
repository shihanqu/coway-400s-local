# Router setup

The purifier makes its own outbound TLS connection to port **9090**. It does not expose a fan-control HTTP port. This service answers its Coway DNS lookup with the controller's LAN IP and acknowledges the resulting local connection.

Example addresses below are placeholders:

- Purifier: `192.168.10.50`
- Controller: `192.168.10.20`
- Router: `192.168.10.1`

Use DHCP reservations or another stable address assignment. The controller must stay running and reachable; a sleeping laptop is not a permanent controller.

## UniFi

Create these policies for the purifier's actual network/interface. Existing firewall policies can affect ordering; preserve unrelated rules.

### Destination NAT: purifier DNS

| Field | Value |
| --- | --- |
| Type | Destination NAT |
| Interface | Network receiving the purifier's traffic |
| IP version / protocol | IPv4 / UDP |
| Source IP | Purifier reserved IP |
| Source port | Any |
| Destination IP | `8.8.8.8` |
| Destination port | `53` |
| Translated IP | Controller LAN IP |
| Translated port | `1053` |

### Source NAT: DNS reply path on the same LAN

When the controller and purifier share a subnet, the reply must pass back through the router so reverse NAT restores its apparent source to `8.8.8.8:53`.

| Field | Value |
| --- | --- |
| Type | Source NAT |
| Interface | Controller's LAN network |
| IP version / protocol | IPv4 / UDP |
| Source IP | Purifier reserved IP |
| Source port | Any |
| Destination IP | Controller LAN IP |
| Destination port | `1053` |
| Translated source IP | Router's address on that LAN |

For separate subnets or router implementations with automatic hairpin NAT, the reply-path rule may differ. Verify that requests arrive and replies return before adding broader rules.

### Internet block

Block **this purifier** from the external/WAN zone. Keep access to the controller's UDP 1053 and TCP 9090. Match the purifier's reserved IP or its router-observed MAC; do not block the entire LAN.

The DNS service is deliberately not a recursive resolver: it answers Coway A queries with the local controller address and refuses unrelated names. Because hairpin NAT can make requests appear to come from the router, DNS source restrictions belong on the per-device router rule. `COWAY_DEVICE_IP` restricts the incoming **TLS** connection, not gateway-forwarded DNS.

Docker Desktop can change the apparent source address of forwarded TCP connections. If the service logs `Unexpected source IP`, leave optional `COWAY_DEVICE_IP` empty and retain the router's per-device rule. The configured serial and learned MAC are still checked.

## Other routers

You need the same packet path:

```text
purifier -> 8.8.8.8 UDP/53
         -> router DNAT -> controller UDP/1053
         <- reply through router/reverse NAT

purifier -> controller TCP/9090 (TLS)
```

An ordinary DNS override or DHCP DNS setting works only if it also intercepts the purifier's hard-coded resolver traffic. If your router cannot redirect per-device DNS, this LAN setup will need a different router or an isolated gateway/access-point setup. This project does not automatically modify router settings.

## Troubleshooting

Run `docker compose logs --tail=50 coway` and `docker compose exec coway coway400s status`.

- **No connection:** check the purifier joined Wi-Fi, both reservations, the DNS redirect and local firewall access. Restart the purifier after the redirect is ready.
- **DNS arrives but no TLS:** check the advertised `COWAY_HOST_IP` is the server's LAN address and port 9090 is reachable from the purifier.
- **Identity mismatch:** use the full 18-character label serial. Letter O and digit 0 are different. Use a separate data volume when changing purifiers.
- **OpenSSL/certificate error:** use the provided Docker image build. Its isolated TLS context enables the legacy algorithms the module needs.

No new pairing is needed after a normal reboot. Docker Compose restarts the service after host restarts when Docker itself starts.
