# Systemd User Service Setup

This guide shows how to run MCPDoc Daemon as a systemd user service.

## Prerequisites

- MCPDoc Daemon installed via pipx or container image available
- Systemd with user service support
- XDG Base Directory specification support (most modern Linux distributions)

## Configuration Directory

The service uses the XDG config directory for configuration files:

```bash
# Default location
~/.config/mcpdoc/
```

Create the configuration directory and add your files:

```bash
mkdir -p ~/.config/mcpdoc
```

Add your configuration files:
- `~/.config/mcpdoc/config.yaml` - Main mcpdoc configuration
- `~/.config/mcpdoc/*.llms.txt` - Documentation source files

## Method 1: Using Python Package

### Installation

```bash
# Install via pipx
pipx install mcpdoc-daemon
```

### Systemd Service File

Create the systemd user service file:

```bash
mkdir -p ~/.config/systemd/user
```

Create `~/.config/systemd/user/mcpdoc-daemon.service`:

```ini
[Unit]
Description=MCPDoc Daemon - MCP Documentation Server
After=network.target
Wants=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/mcpdoc-daemon --config-dir %h/.config/mcpdoc --host 127.0.0.1 --port 8080 --log-level INFO
Restart=always
RestartSec=5
Environment="PATH=%h/.local/bin:/usr/bin:/bin"

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=mcpdoc-daemon

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=%h/.config/mcpdoc
BindReadOnlyPaths=%h/.config/mcpdoc

[Install]
WantedBy=default.target
```

### Enable and Start Service

```bash
# Reload systemd user configuration
systemctl --user daemon-reload

# Enable service to start automatically and start immediately
systemctl --user enable --now mcpdoc-daemon.service

# Check service status
systemctl --user status mcpdoc-daemon.service
```

## Method 2: Using Container Image

### Systemd Service File

Create `~/.config/systemd/user/mcpdoc-daemon.service`:

```ini
[Unit]
Description=MCPDoc Daemon - MCP Documentation Server (Container)
After=network.target
Wants=network.target

[Service]
Type=simple
ExecStartPre=/usr/bin/podman pull ghcr.io/abn/mcpdoc-daemon:latest
ExecStart=/usr/bin/podman run --rm --name mcpdoc-daemon \
    -p 127.0.0.1:8080:8080 \
    -v %h/.config/mcpdoc:/config:ro,Z \
    -e MCPDOC_HOST=0.0.0.0 \
    -e MCPDOC_PORT=8080 \
    -e MCPDOC_LOG_LEVEL=INFO \
    ghcr.io/abn/mcpdoc-daemon:latest
ExecStop=/usr/bin/podman stop mcpdoc-daemon
Restart=always
RestartSec=5

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=mcpdoc-daemon

# Security
NoNewPrivileges=true

[Install]
WantedBy=default.target
```

You can follow the instructions in the previous section to enable and start the service.

## Configuration

### Environment Variables

The service supports these environment variables:

- `MCPDOC_CONFIG_DIR`: Configuration directory (default: `~/.config/mcpdoc`)
- `MCPDOC_HOST`: Server host (default: `127.0.0.1`)
- `MCPDOC_PORT`: Server port (default: `8080`)
- `MCPDOC_LOG_LEVEL`: Logging level (default: `INFO`)

## Access

Once running, the service will be available at:
- **Local access**: http://127.0.0.1:8080
- **Health check**: http://127.0.0.1:8080/health

## Troubleshooting

### Service Won't Start

1. Check service status:
   ```bash
   systemctl --user status mcpdoc-daemon.service
   ```

2. View detailed logs:
   ```bash
   journalctl --user -u mcpdoc-daemon.service --no-pager
   ```

3. Verify configuration directory exists:
   ```bash
   ls -la ~/.config/mcpdoc/
   ```

### Port Already in Use

If port 8080 is already in use, modify the service file to use a different port:

```ini
# For Python package method
ExecStart=%h/.local/bin/mcpdoc-daemon --config-dir %h/.config/mcpdoc --host 127.0.0.1 --port 8081 --log-level INFO

# For container method
ExecStart=/usr/bin/podman run --rm --name mcpdoc-daemon \
    -p 127.0.0.1:8081:8081 \
    -v %h/.config/mcpdoc:/config:ro,Z \
    -e MCPDOC_HOST=0.0.0.0 \
    -e MCPDOC_PORT=8081 \
    -e MCPDOC_LOG_LEVEL=INFO \
    ghcr.io/abn/mcpdoc-daemon:latest
```

### Container Image Issues

1. Ensure podman is installed and accessible:
   ```bash
   podman --version
   ```

2. Test pulling the image manually:
   ```bash
   podman pull ghcr.io/abn/mcpdoc-daemon:latest
   ```

3. Check container logs:
   ```bash
   podman logs mcpdoc-daemon
   ```

## Security Considerations

- The service runs with user privileges (not root)
- Container runs with read-only access to config directory
- Network binding is restricted to localhost (127.0.0.1)
- Service includes security hardening options (NoNewPrivileges, PrivateTmp, etc.)
- Configuration files should have appropriate permissions (600 or 644)
