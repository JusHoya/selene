import { useState, useEffect, useRef, useCallback } from 'react';
import ROSLIB from 'roslib';

const DEFAULT_URL = 'ws://localhost:9090';
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 10000];

export default function useRosBridge(url = DEFAULT_URL) {
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(null);
  const rosRef = useRef(null);
  const retryRef = useRef(0);
  const timerRef = useRef(null);

  const connect = useCallback(() => {
    if (rosRef.current) {
      try { rosRef.current.close(); } catch (e) { /* ignore */ }
    }

    const ros = new ROSLIB.Ros({ url });

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
  }, [url]);

  useEffect(() => {
    connect();
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      if (rosRef.current) {
        try { rosRef.current.close(); } catch (e) { /* ignore */ }
      }
    };
  }, [connect]);

  return { ros: rosRef.current, connected, error };
}
