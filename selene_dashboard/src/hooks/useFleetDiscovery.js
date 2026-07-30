// A15: Dynamic fleet discovery.
//
// The dashboard used to derive every per-robot subscription from a hardcoded
// four-element ROBOT_IDS array. The launch file supports num_scouts /
// num_excavators / num_haulers, so a five-robot fleet produced four cards, no
// map icon for the fifth robot, and a task queue that named an invisible robot
// as the assignee of a task that never appeared to progress.
//
// Discovery asks rosbridge_suite's rosapi node which topics currently publish
// selene_msgs/RobotState and derives the robot ids from those topic names.
// If rosapi is unavailable (mock bridge, rosapi not launched) we fall back to
// the explicitly-labelled FALLBACK_ROBOT_IDS list so the dashboard still works.
//
// The rosapi request type string was subsequently MEASURED against a live
// rosapi node on ROS 2 Jazzy (2026-07-29): 'selene_msgs/msg/RobotState' matches
// and 'selene_msgs/RobotState' returns an empty topic list with result=True.
// See ROBOT_STATE_TYPE_CANDIDATES in ../utils/rosTopics for the measurement.
// The surrounding polling/merge behaviour has still not been exercised against a
// live rosapi node end to end.
import { useState, useEffect, useRef, useMemo } from 'react';
import ROSLIB from 'roslib';
import {
  FALLBACK_ROBOT_IDS,
  ROBOT_STATE_TYPE_CANDIDATES,
  ROSAPI,
  ROSAPI_TOPICS_FOR_TYPE_TYPES,
} from '../utils/rosTopics';

// How often to re-ask rosapi, so robots that come up later are picked up
// without a page reload.
export const DISCOVERY_POLL_MS = 3000;

// A robot id is dropped from the set only after this many consecutive polls
// without its /state topic. Prevents the subscription set from thrashing on a
// single dropped introspection reply.
export const ABSENT_POLLS_BEFORE_DROP = 3;

const STATE_SUFFIX = '/state';

/**
 * Derive robot ids from a list of RobotState topic names.
 * '/scout_01/state' -> 'scout_01'. Nested namespaces and anything that is not
 * a bare `<id>/state` topic are ignored rather than guessed at.
 */
export function robotIdsFromStateTopics(topics) {
  const ids = [];
  const list = Array.isArray(topics) ? topics : [];
  list.forEach((topic) => {
    if (typeof topic !== 'string') return;
    const trimmed = topic.startsWith('/') ? topic.slice(1) : topic;
    if (!trimmed.endsWith(STATE_SUFFIX)) return;
    const id = trimmed.slice(0, -STATE_SUFFIX.length);
    if (!id || id.includes('/')) return;
    if (!ids.includes(id)) ids.push(id);
  });
  return ids.sort();
}

/**
 * Merge a poll result into the previously-known set, tolerating transient
 * absences. Returns the previous array unchanged when nothing moved, so the
 * caller's effect dependencies stay stable.
 */
export function mergeDiscovered(prev, found, misses) {
  const prevList = Array.isArray(prev) ? prev : [];
  const foundSet = new Set(found);
  const next = [];

  prevList.forEach((id) => {
    if (foundSet.has(id)) {
      misses[id] = 0;
      next.push(id);
    } else {
      misses[id] = (misses[id] || 0) + 1;
      if (misses[id] < ABSENT_POLLS_BEFORE_DROP) next.push(id);
      else delete misses[id];
    }
  });
  found.forEach((id) => {
    if (!next.includes(id)) {
      misses[id] = 0;
      next.push(id);
    }
  });
  next.sort();

  if (prevList.length === next.length && prevList.every((v, i) => v === next[i])) {
    return prev;
  }
  return next;
}

/**
 * @returns {{robotIds: string[], discoverySource: 'rosapi'|'fallback'}}
 */
export default function useFleetDiscovery(ros, connected) {
  // null => rosapi has never answered, so we are on the fallback list.
  const [discovered, setDiscovered] = useState(null);
  const missesRef = useRef({});
  const typeIdxRef = useRef(0);
  // Which ROBOT_STATE_TYPE_CANDIDATES entry the request body currently uses,
  // and whether a non-empty reply has confirmed it. Rotating on an empty
  // success is what escapes the wrong-spelling case; locking on the first
  // non-empty reply stops us rotating away from a string that works.
  const msgTypeIdxRef = useRef(0);
  const msgTypeLockedRef = useRef(false);

  useEffect(() => {
    if (!ros || !connected) {
      // Reset so a reconnect (possibly to a restarted backend with a different
      // fleet size) re-discovers from scratch instead of inheriting stale ids.
      missesRef.current = {};
      typeIdxRef.current = 0;
      msgTypeIdxRef.current = 0;
      msgTypeLockedRef.current = false;
      setDiscovered(null);
      return undefined;
    }

    let cancelled = false;

    const poll = () => {
      if (cancelled) return;
      const serviceType = ROSAPI_TOPICS_FOR_TYPE_TYPES[
        typeIdxRef.current % ROSAPI_TOPICS_FOR_TYPE_TYPES.length
      ];
      let service;
      try {
        service = new ROSLIB.Service({
          ros,
          name: ROSAPI.TOPICS_FOR_TYPE,
          serviceType,
        });
      } catch (err) {
        return;
      }
      const msgType = ROBOT_STATE_TYPE_CANDIDATES[
        msgTypeIdxRef.current % ROBOT_STATE_TYPE_CANDIDATES.length
      ];
      const request = new ROSLIB.ServiceRequest({ type: msgType });
      try {
        service.callService(
          request,
          (response) => {
            if (cancelled) return;
            const found = robotIdsFromStateTopics(response?.topics);
            if (found.length > 0) {
              // This spelling works against this graph — stop rotating.
              msgTypeLockedRef.current = true;
            } else if (!msgTypeLockedRef.current) {
              // rosapi answered successfully with nothing. That is either a
              // genuinely empty fleet or the wrong type spelling, and the two
              // are indistinguishable from here, so try the other spelling on
              // the next poll. Harmless when the fleet really is empty.
              msgTypeIdxRef.current += 1;
            }
            setDiscovered((prev) => mergeDiscovered(prev, found, missesRef.current));
          },
          () => {
            if (cancelled) return;
            // rosapi missing, or this service-type string was rejected.
            // Rotate to the next candidate for the following poll and stay on
            // the fallback list until something answers.
            typeIdxRef.current += 1;
          },
        );
      } catch (err) {
        typeIdxRef.current += 1;
      }
    };

    poll();
    const timer = setInterval(poll, DISCOVERY_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [ros, connected]);

  const robotIds = useMemo(
    () => (discovered !== null ? discovered : FALLBACK_ROBOT_IDS),
    [discovered],
  );

  return {
    robotIds,
    discoverySource: discovered !== null ? 'rosapi' : 'fallback',
  };
}
