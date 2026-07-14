import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame,
        useVideoConfig} from 'remotion';

export const kineticTitleDefaults = {
  text: 'He robbed *politely*',
  accent: '#b33a2b',
  ink: '#f2ede0',
  font: 'Georgia, serif',
  position: 'lower' as 'lower' | 'center',
};

// Word-by-word typeset line on a TRANSPARENT canvas, composited over a
// scene. One *starred* word takes the accent color. Only used when the
// channel's study documents burned-text moments (typeset rule, 2026-07-12).
export const KineticTitle: React.FC<typeof kineticTitleDefaults> = ({
  text, accent, ink, font, position,
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames, height} = useVideoConfig();
  const words = text.split(/\s+/).filter(Boolean);
  const perWord = 4;
  const outO = interpolate(frame, [durationInFrames - 10, durationInFrames],
                           [1, 0], {extrapolateLeft: 'clamp'});
  return (
    <AbsoluteFill style={{backgroundColor: 'transparent',
                          alignItems: 'center',
                          justifyContent: position === 'center' ? 'center'
                                                                : 'flex-end'}}>
      <div style={{
        display: 'flex', flexWrap: 'wrap', gap: '0.32em',
        justifyContent: 'center', maxWidth: '80%',
        marginBottom: position === 'lower' ? height * 0.12 : 0,
        opacity: outO,
      }}>
        {words.map((w, i) => {
          const starred = /^\*.+\*[.,!?]?$/.test(w);
          const clean = w.replace(/\*/g, '');
          const s = spring({frame: frame - i * perWord, fps,
                            config: {damping: 13, stiffness: 140}});
          return (
            <span key={i} style={{
              fontFamily: font, fontWeight: 800,
              fontSize: height * (starred ? 0.062 : 0.055),
              color: starred ? accent : ink,
              textShadow: '0 2px 12px rgba(0,0,0,0.75)',
              opacity: Math.min(1, s * 1.5),
              transform: `translateY(${(1 - s) * 24}px)`,
              display: 'inline-block',
            }}>
              {clean}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
