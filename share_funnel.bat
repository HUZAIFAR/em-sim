@echo off
REM ============================================================
REM  share_funnel.bat  -  expose the running bridge publicly via
REM  Tailscale Funnel so ONE remote tester can use the whole tool.
REM
REM  1) Start the bridge first (run_bridge.bat) in another window,
REM     confirm http://localhost:8731 works locally.
REM  2) Then run this. It maps a PUBLIC https URL to local :8731.
REM
REM  WARNING: the Funnel URL is PUBLIC and UNAUTHENTICATED. Anyone
REM  who has the link can load the page and trigger openEMS solves
REM  on this PC. Only give the link to someone you trust, and stop
REM  sharing when done:   tailscale funnel --https=443 off
REM ============================================================
set "TS=C:\Program Files\Tailscale\tailscale.exe"

echo Enabling Tailscale Funnel on port 8731 ...
"%TS%" funnel 8731

REM (Ctrl-C to stop foreground sharing. Your public URL:)
REM   "%TS%" funnel status
