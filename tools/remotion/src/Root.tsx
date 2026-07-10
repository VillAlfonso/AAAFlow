import React from 'react';
import {Composition} from 'remotion';
import {RefCard, refCardDefaults} from './RefCard';
import {DateChip, dateChipDefaults} from './DateChip';

// Overlay compositions render on a TRANSPARENT canvas and are composited
// over the finished scene by the assembler:
//   npx remotion render src/index.ts RefCard out.webm
//       --props='{"img":"file:///...","label":"Victor Lustig"}'
//       --codec=vp8 --pixel-format=yuva420p
export const Root: React.FC = () => (
  <>
    <Composition
      id="RefCard"
      component={RefCard}
      durationInFrames={120}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={refCardDefaults}
    />
    <Composition
      id="DateChip"
      component={DateChip}
      durationInFrames={90}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={dateChipDefaults}
    />
  </>
);
