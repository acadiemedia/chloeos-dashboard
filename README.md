# ChloeOS · God Mode Dashboard

Part of the ChloeOS system.

Live status dashboard for all ChloeOS agents and services. Shows agent online/offline status, audio server health with queue depth, and Pulse mailbox activity. Auto-refreshes every 30 seconds.

## Run

```bash
python3 dashboard.py
```

Serves on port 8199. Access via Tailscale: `http://<node-ip>:8199/`

Built for ChloeOS.
