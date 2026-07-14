import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame,
        useVideoConfig} from 'remotion';

export const arrowCalloutDefaults = {
  x: 0.62,          // circle center, fraction of frame width
  y: 0.38,          // fraction of frame height
  r: 0.09,          // radius, fraction of frame height
  label: 'right here',
  accent: '#d21f1f',
  font: 'Georgia, serif',
};

// Hand-annotation style callout on a TRANSPARENT canvas: a circle draws on
// around the target, a short label settles next to it. Covers the reference
// channels' highlight/arrow device (technique_executors: highlight-or-arrow).
export const ArrowCallout: React.FC<typeof arrowCalloutDefaults> = ({
  x, y, r, label, accent, font,
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames, width, height} = useVideoConfig();
  const cx = x * width;
  const cy = y * height;
  const rad = r * height;
  const circ = 2 * Math.PI * rad;
  const draw = interpolate(frame, [0, 14], [circ, 0],
                           {extrapolateLeft: 'clamp',
                            extrapolateRight: 'clamp'});
  const labelIn = spring({frame: frame - 10, fps,
                          config: {damping: 14, stiffness: 120}});
  const outO = interpolate(frame, [durationInFrames - 8, durationInFrames],
                           [1, 0], {extrapolateLeft: 'clamp'});
  const labelLeft = cx + rad + 24 + (1 - labelIn) * 18;
  return (
    <AbsoluteFill style={{backgroundColor: 'transparent', opacity: outO}}>
      <svg width={width} height={height}>
        <circle
          cx={cx} cy={cy} r={rad}
          fill="none" stroke={accent} strokeWidth={Math.max(4, rad * 0.09)}
          strokeDasharray={circ} strokeDashoffset={draw}
          strokeLinecap="round"
          transform={`rotate(-80 ${cx} ${cy})`}
        />
      </svg>
      <div style={{
        position: 'absolute', left: labelLeft, top: cy - height * 0.024,
        fontFamily: font, fontWeight: 800, fontSize: height * 0.042,
        color: accent, opacity: Math.min(1, labelIn * 1.4),
        textShadow: '0 2px 10px rgba(0,0,0,0.8)',
        whiteSpace: 'nowrap',
      }}>
        {label}
      </div>
    </AbsoluteFill>
  );
};
