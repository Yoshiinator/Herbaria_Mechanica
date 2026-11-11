#!/bin/bash
set -e

# Mount network shares if configured
NETWORK_MOUNTS="${NETWORK_MOUNTS:-}"
if [ -n "$NETWORK_MOUNTS" ]; then
    echo "Mounting network shares..."
    IFS=',' read -ra MOUNTS <<< "$NETWORK_MOUNTS"
    for MOUNT in "${MOUNTS[@]}"; do
        MOUNT=$(echo "$MOUNT" | xargs)  # trim whitespace
        if [ -n "$MOUNT" ]; then
            echo "Mounting: $MOUNT"
            mount.cifs "$MOUNT" /mnt/share -o guest,uid=1000,gid=1000 || echo "Warning: Failed to mount $MOUNT"
        fi
    done
fi

# Also check legacy NETWORK_SHARE variable for single share
NETWORK_SHARE="${NETWORK_SHARE:-}"
if [ -n "$NETWORK_SHARE" ]; then
    echo "Mounting legacy network share: $NETWORK_SHARE"
    mount.cifs "$NETWORK_SHARE" /mnt/share -o guest,uid=1000,gid=1000 || echo "Warning: Failed to mount $NETWORK_SHARE"
fi

# Run the application
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 "$@"
