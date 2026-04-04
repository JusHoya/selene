import React from 'react';
import { batteryColor } from '../utils/colors';
import './BatteryGauge.css';

export default function BatteryGauge({ level = 0, charging = false, size = 100 }) {
  const radius = 40;
  const circumference = 2 * Math.PI * radius;
  const clampedLevel = Math.max(0, Math.min(1, level));
  const offset = circumference * (1 - clampedLevel);
  const color = batteryColor(clampedLevel);
  const percentText = `${Math.round(clampedLevel * 100)}%`;
  const fontSize = size * 0.2;

  return (
    <div className="battery-gauge" style={{ width: size, height: size }}>
      <svg
        className="battery-gauge__svg"
        width={size}
        height={size}
        viewBox="0 0 100 100"
      >
        <circle
          className="battery-gauge__track"
          cx="50"
          cy="50"
          r={radius}
        />
        <circle
          className="battery-gauge__fill"
          cx="50"
          cy="50"
          r={radius}
          stroke={color}
          style={{
            strokeDasharray: circumference,
            strokeDashoffset: offset,
          }}
        />
      </svg>
      <div className="battery-gauge__center">
        <span
          className="battery-gauge__percent"
          style={{ fontSize: `${fontSize}px` }}
        >
          {percentText}
        </span>
        {charging && (
          <span className="battery-gauge__charging" style={{ color }}>
            ⚡
          </span>
        )}
      </div>
    </div>
  );
}
