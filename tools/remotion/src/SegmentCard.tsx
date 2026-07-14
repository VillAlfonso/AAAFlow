import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame,
        useVideoConfig} from 'remotion';

export const segmentCardDefaults = {
  title: 'THE POLITE ONE',
  kicker: 'PART II',
  bg: '#f4efe4',
  ink: '#17161a',
  accent: '#b33a2b',
  font: 'Georgia, serif',
};

// Full-frame typeset segment card (the study-sanctioned burned text: real
// fonts, one accent element). Renders OPAQUE — it IS the scene, cut in and
// out like any other shot. Channel colors come in as props.
export const SegmentCard: React.FC<typeof segmentCardDefaults> = ({
  title, kicker, bg, ink, accent, font,
}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const barGrow = spring({frame, fps, config: {damping: 16, stiffness: 120}});
  const titleUp = spring({frame: frame - 4, fps,
                          config: {damping: 14, stiffness: 90}});
  const kickerO = interpolate(frame, [8, 16], [0, 1],
                              {extrapolateLeft: 'clamp',
                               extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{backgroundColor: bg, alignItems: 'center',
                          justifyContent: 'center'}}>
      <div style={{textAlign: 'center', maxWidth: width * 0.82}}>
        <div style={{
          fontFamily: font, fontWeight: 700, letterSpacing: '0.28em',
          fontSize: height * 0.032, color: accent, opacity: kickerO,
          textTransform: 'uppercase',
        }}>
          {kicker}
        </div>
        <div style={{
          height: 6, background: accent, margin: '18px auto',
          width: width * 0.14 * barGrow,
        }} />
        <div style={{
          fontFamily: font, fontWeight: 900, color: ink,
          fontSize: height * 0.105, lineHeight: 1.05,
          textTransform: 'uppercase', letterSpacing: '0.01em',
          opacity: Math.min(1, titleUp * 1.4),
          transform: `translateY(${(1 - titleUp) * height * 0.04}px)`,
        }}>
          {title}
        </div>
      </div>
    </AbsoluteFill>
  );
};
