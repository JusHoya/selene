import React, { useRef, useEffect } from 'react';
import { iceConcentrationColor } from '../utils/colors';
import './ResourceLegend.css';

function ResourceLegend({ heatmapVisible, onToggleHeatmap }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;

    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    // Draw gradient bar
    const grad = ctx.createLinearGradient(0, 0, width, 0);
    const steps = 20;
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      const value = t * 10;
      grad.addColorStop(t, iceConcentrationColor(value, 1.0));
    }
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.roundRect(0, 0, width, height, 2);
    ctx.fill();
  }, []);

  return (
    <div className="resource-legend">
      <div className="resource-legend__title">Ice Concentration</div>
      <div className="resource-legend__bar-container">
        <canvas
          ref={canvasRef}
          className="resource-legend__bar"
          style={{ width: '100%', height: 10 }}
        />
      </div>
      <div className="resource-legend__labels">
        <span>0</span>
        <span>5</span>
        <span>10 wt%</span>
      </div>
      <button
        className={
          'resource-legend__toggle' +
          (heatmapVisible ? ' resource-legend__toggle--active' : '')
        }
        onClick={onToggleHeatmap}
      >
        <span className="resource-legend__indicator" />
        {heatmapVisible ? 'Heatmap On' : 'Heatmap Off'}
      </button>
    </div>
  );
}

export default ResourceLegend;
