// Wave2-A4: ROSLIB service client wrapper hook.
// Mirrors useRosBridge's style — exposes a Promise-returning caller that
// takes (serviceName, serviceType, payload) and resolves with the response.
import { useCallback } from 'react';
import ROSLIB from 'roslib';

export default function useRosService(ros, connected) {
  const callService = useCallback(
    (serviceName, serviceType, payload) => {
      return new Promise((resolve, reject) => {
        if (!ros || !connected) {
          reject(new Error('rosbridge not connected'));
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
          reject(new Error(err?.message || 'failed to build service client'));
          return;
        }
        const request = new ROSLIB.ServiceRequest(payload || {});
        try {
          service.callService(
            request,
            (response) => resolve(response),
            (error) => reject(new Error(error || 'service call failed')),
          );
        } catch (err) {
          reject(new Error(err?.message || 'service call threw'));
        }
      });
    },
    [ros, connected],
  );

  return callService;
}
