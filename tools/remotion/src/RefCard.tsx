import React from 'react';
import {AbsoluteFill, Img, interpolate, spring, useCurrentFrame,
        useVideoConfig} from 'remotion';

export const refCardDefaults = {
  img: '',
  label: 'Victor Lustig',
  accent: '#c9a227',
  tilt: 2.2,
  side: 'right' as 'right' | 'left',
};

// The first-mention reference card: a tilted polaroid springs in from the
// side, floats gently, and fades out. Mirrors app/refcards.py so either
// engine produces the same move.
export const RefCard: React.FC<typeof refCardDefaults> = ({
  img, label, accent, tilt, side,
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames, width, height} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 14, mass: 0.7}});
  const out = interpolate(frame, [durationInFrames - 12, durationInFrames],
                          [1, 0], {extrapolateLeft: 'clamp'});
  const bob = Math.sin((frame / fps + 0.4) * 1.3) * 4;
  const slide = (1 - enter) * 140 * (side === 'right' ? 1 : -1);
  const cardW = width * 0.24;
  return (
    <AbsoluteFill style={{backgroundColor: 'transparent'}}>
      <div
        style={{
          position: 'absolute',
          top: height * 0.1 + bob,
          [side]: width * 0.035,
          transform: `translateX(${slide}px) rotate(${tilt}deg)`,
          opacity: Math.min(enter * 1.2, 1) * out,
          background: '#f0ecE2',
          padding: 12,
          paddingBottom: 8,
          boxShadow: '10px 16px 34px rgba(0,0,0,0.6)',
          width: cardW,
        }}
      >
        {img ? (
          <Img src={img} style={{width: '100%', display: 'block'}} />
        ) : null}
        {label ? (
          <div
            style={{
              fontFamily: 'Georgia, serif',
              fontWeight: 700,
              fontSize: height * 0.028,
              color: '#26221c',
              padding: '10px 2px 2px',
            }}
          >
            {label}
            <div style={{height: 3, width: '38%', background: accent,
                         marginTop: 4}} />
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
