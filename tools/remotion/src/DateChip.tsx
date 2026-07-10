import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame,
        useVideoConfig} from 'remotion';

export const dateChipDefaults = {
  text: '1945',
  accent: '#c9a227',
};

// The sanctioned on-screen date: typeset text pops in low-left with a gold
// underline, then fades. Mirrors assemble._date_chip.
export const DateChip: React.FC<typeof dateChipDefaults> = ({text, accent}) => {
  const frame = useCurrentFrame();
  const {durationInFrames, width, height} = useVideoConfig();
  const inO = interpolate(frame, [0, 6], [0, 1], {extrapolateRight: 'clamp'});
  const outO = interpolate(frame, [durationInFrames - 12, durationInFrames],
                           [1, 0], {extrapolateLeft: 'clamp'});
  const rise = interpolate(frame, [0, 6], [10, 0],
                           {extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{backgroundColor: 'transparent'}}>
      <div
        style={{
          position: 'absolute',
          left: width * 0.055,
          top: height * 0.82 + rise,
          opacity: inO * outO,
          fontFamily: 'Georgia, serif',
          fontWeight: 700,
          fontSize: height * 0.046,
          color: '#e8e0cc',
          textShadow: '0 2px 10px rgba(0,0,0,0.85)',
        }}
      >
        {text}
        <div style={{height: 4, background: accent, marginTop: 4,
                     width: Math.max(60, text.length * height * 0.027)}} />
      </div>
    </AbsoluteFill>
  );
};
