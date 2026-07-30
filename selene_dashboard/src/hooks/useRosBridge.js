import { useState, useEffect, useRef, useCallback } from 'react';
import ROSLIB from 'roslib';

const DEFAULT_PORT = 9090;
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 10000];

/**
 * A8: Resolve the rosbridge websocket URL.
 *
 * The URL used to be hardcoded to ws://localhost:9090, which only works when
 * the browser is on the same machine as rosbridge. Resolution order:
 *   1. ?rosbridge=... query parameter (host, host:port, or a full ws:// URL)
 *   2. REACT_APP_ROSBRIDGE_URL at build time
 *   3. the host the dashboard itself was served from, on port 9090
 *   4. localhost:9090
 */
export function resolveRosbridgeUrl() {
  const fallback = `ws://localhost:${DEFAULT_PORT}`;
  if (typeof window === 'undefined' || !window.location) return fallback;

  // 1. Query override — highest priority so an operator can repoint the
  //    dashboard at a different bridge without a rebuild.
  try {
    const params = new URLSearchParams(window.location.search || '');
    const override = params.get('rosbridge');
    if (override) {
      if (/^wss?:\/\//i.test(override)) return override;
      return override.includes(':')
        ? `ws://${override}`
        : `ws://${override}:${DEFAULT_PORT}`;
    }
  } catch (e) { /* URLSearchParams unavailable — fall through */ }

  // 2. Build-time env override.
  const envUrl = process.env.REACT_APP_ROSBRIDGE_URL;
  if (envUrl) return envUrl;

  // 3. Same host as the page. Covers "open the dashboard from a laptop on the
  //    same network as the robot machine", which is the briefing scenario.
  const host = window.location.hostname;
  if (host) {
    const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
    return `${scheme}://${host}:${DEFAULT_PORT}`;
  }

  // 4. file:// or otherwise hostless.
  return fallback;
}

export default function useRosBridge(url) {
  // Resolved once per hook call; a plain string so the useCallback dep below
  // compares by value.
  const resolvedUrl = url || resolveRosbridgeUrl();

  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(null);
  const rosRef = useRef(null);
  const retryRef = useRef(0);
  const timerRef = useRef(null);
  // Bump on every new ROSLIB.Ros so consumers re-run their subscribe effects.
  const [, setRosGeneration] = useState(0);

  const connect = useCallback(() => {
    if (rosRef.current) {
      try { rosRef.current.close(); } catch (e) { /* ignore */ }
    }

    const ros = new ROSLIB.Ros({ url: resolvedUrl });

    ros.on('connection', () => {
      setConnected(true);
      setError(null);
      retryRef.current = 0;
    });

    ros.on('close', () => {
      setConnected(false);
      const delay = RECONNECT_DELAYS[Math.min(retryRef.current, RECONNECT_DELAYS.length - 1)];
      retryRef.current += 1;
      timerRef.current = setTimeout(connect, delay);
    });

    ros.on('error', (err) => {
      setError(err?.message || 'Connection error');
    });

    rosRef.current = ros;
    setRosGeneration((n) => n + 1);
  }, [resolvedUrl]);

  useEffect(() => {
    connect();
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      if (rosRef.current) {
        try { rosRef.current.close(); } catch (e) { /* ignore */ }
      }
    };
  }, [connect]);

  return { ros: rosRef.current, connected, error, url: resolvedUrl };
}
