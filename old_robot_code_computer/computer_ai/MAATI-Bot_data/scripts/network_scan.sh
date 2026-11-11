#!/bin/bash
# Network device scanner - discovers all devices on 192.168.1.x network

LOGFILE="/home/pairaiworkstation/MAATI-Bot_data/network_scan.log"
TIMESTAMP=$(date "+%Y-%m-%d %H:%M")

echo "=== Network Scan $TIMESTAMP ===" >> $LOGFILE

# Scan ARP table for known devices
echo "Active devices:" >> $LOGFILE
ip neigh show 2>/dev/null | grep "192.168.1" | awk '{print $1, $3}' | sort -t. -k3 -n >> $LOGFILE

# Try to identify each device
echo "" >> $LOGFILE
echo "Device identification:" >> $LOGFILE
for ip in $(ip neigh show 2>/dev/null | grep "192.168.1" | awk '{print $1}' | cut -d' ' -f1); do
    result=""
    # Check for HTTP service
    if timeout 1 curl -sf http://$ip:8000/health >/dev/null 2>&1; then
        result="$result:Gantry"
    fi
    if timeout 1 nc -z $ip 22 2>/dev/null; then
        result="$result:SSH"
    fi
    if timeout 1 nc -z $ip 554 2>/dev/null; then
        result="$result:RTSP"
    fi
    if timeout 1 curl -sf http://$ip:8224/health >/dev/null 2>&1; then
        result="$result:IPCam"
    fi
    echo "  $ip: $result" >> $LOGFILE
done

echo "" >> $LOGFILE

# Known device map
echo "Known devices:" >> $LOGFILE
echo "  192.168.1.1   - UniFi Gateway (router)" >> $LOGFILE
echo "  192.168.1.2   - MATI Bot (gantry API)" >> $LOGFILE
echo "  192.168.1.52  - IP Camera 0" >> $LOGFILE
echo "  192.168.1.57  - IP Camera 1" >> $LOGFILE

echo "---" >> $LOGFILE

# Print last scan to stdout
tail -20 $LOGFILE