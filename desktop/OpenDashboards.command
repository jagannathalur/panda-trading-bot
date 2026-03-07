#!/bin/bash
# =============================================================
# OpenDashboards.command — Open all dashboards in browser.
# Use this if dashboards closed but bot is still running.
# =============================================================

open "http://127.0.0.1:8081/ui/"
open "http://127.0.0.1:8080"

echo "Opened FreqUI (8081) and Ops Dashboard (8080)"
sleep 1
