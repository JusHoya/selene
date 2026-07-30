// Wave2-A4: ROSLIB service client wrapper hook.
// Exposes a Promise-returning caller that takes
// (serviceName, serviceType, payload) and resolves with the response.
//
// A8: the hook now returns `null` when there is no usable rosbridge
// connection, instead of always handing back a callable that rejects. Callers
// can therefore distinguish "we are not connected, this control is unavailable"
// (falsy callService) from "the call was attempted and failed" (rejected
// promise), and can disable/annotate their controls accordingly.
import { useCallback } from 'react';
import ROSLIB from 'roslib';

/** Error codes attached to rejections so callers can branch without string matching. */
export const SERVICE_ERROR = {
  NOT_CONNECTED: 'NOT_CONNECTED',
  CLIENT_FAILED: 'CLIENT_FAILED',
  CALL_FAILED: 'CALL_FAILED',
};

function serviceError(code, message) {
  const err = new Error(message);
  err.code = code;
  return err;
}

export default function useRosService(ros, connected) {
  const callService = useCallback(
    (serviceName, serviceType, payload) => {
      return new Promise((resolve, reject) => {
        if (!ros || !connected) {
          // Still guarded: `connected` can go false between render and click.
          reject(serviceError(
            SERVICE_ERROR.NOT_CONNECTED,
            'rosbridge not connected',
          ));
          return;
        }
        let service;
        try {
          service = new ROSLIB.Service({
            ros,
            name: serviceName,
            serviceType,
          });
        } catch (err) {
          reject(serviceError(
            SERVICE_ERROR.CLIENT_FAILED,
            err?.message || 'failed to build service client',
          ));
          return;
        }
        const request = new ROSLIB.ServiceRequest(payload || {});
        try {
          service.callService(
            request,
            (response) => resolve(response),
            (error) => reject(serviceError(
              SERVICE_ERROR.CALL_FAILED,
              error || 'service call failed',
            )),
          );
        } catch (err) {
          reject(serviceError(
            SERVICE_ERROR.CALL_FAILED,
            err?.message || 'service call threw',
          ));
        }
      });
    },
    [ros, connected],
  );

  // A8: null when disconnected — unambiguous to callers.
  return ros && connected ? callService : null;
}
