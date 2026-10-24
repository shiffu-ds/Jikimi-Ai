# Runbook: device key rotation / revocation

1. Suspected theft: set the device `status` to `revoked` in the server (`devices` table) - its token and
   signatures are rejected immediately; past evidence signed before revocation stays verifiable.
2. On the replacement edge: move the old key away, run `python -m jikimi_edge keygen` (new key), re-run
   the seed/registration so the server stores the new public key and issues a new token.
3. Record the rotation in the audit log and the site's incident register.

## Server key (evidence manifests and rule bundles)

The server's Ed25519 key (`data/server/keys/evidence.key`) signs evidence manifests and the rule
bundle and event calendar the edge pulls from `/v1/edge/rules` and `/v1/edge/calendar`
(ADR-0022, ADR-0023). Each edge pins that key on the first
bundle it accepts (`data/edge/keys/server.pub`) and refuses bundles signed by any other key.

1. Rotate on the server: `python -m jikimi_server retire-key`. It saves the public key to
   `keys/retired/<key id>.pub` (evidence signed with it stays verifiable on `/verify`) and renames
   the private key to `evidence.key.retired-YYYYMMDD`: move that file to offline storage. Restart
   the API; it creates a new key.
2. On every edge: after confirming the new key id out of band, delete `data/edge/keys/server.pub`
   so the edge re-pins on the next bundle (or write the new public key into it). Until then the edge
   keeps running its last accepted rules and logs
   `rules bundle refused: signed by a server key other than the pinned one` (and the same for
   `calendar`).
3. Record the rotation in the audit log and the site's incident register.
