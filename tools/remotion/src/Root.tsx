import React from 'react';
import {Composition} from 'remotion';
import {RefCard, refCardDefaults} from './RefCard';
import {DateChip, dateChipDefaults} from './DateChip';
import {SegmentCard, segmentCardDefaults} from './SegmentCard';
import {KineticTitle, kineticTitleDefaults} from './KineticTitle';
import {ArrowCallout, arrowCalloutDefaults} from './ArrowCallout';

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
      calculateMetadata={({props, defaultProps: _d, abortSignal: _a, compositionId: _c}: any) =>
        ({durationInFrames: (props as any).durationInFrames ?? 120})}
    />
    <Composition
      id="DateChip"
      component={DateChip}
      durationInFrames={90}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={dateChipDefaults}
      calculateMetadata={({props}: any) =>
        ({durationInFrames: (props as any).durationInFrames ?? 90})}
    />
    <Composition
      id="SegmentCard"
      component={SegmentCard}
      durationInFrames={75}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={segmentCardDefaults}
      calculateMetadata={({props}: any) =>
        ({durationInFrames: (props as any).durationInFrames ?? 75})}
    />
    <Composition
      id="KineticTitle"
      component={KineticTitle}
      durationInFrames={80}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={kineticTitleDefaults}
      calculateMetadata={({props}: any) =>
        ({durationInFrames: (props as any).durationInFrames ?? 80})}
    />
    <Composition
      id="ArrowCallout"
      component={ArrowCallout}
      durationInFrames={70}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={arrowCalloutDefaults}
      calculateMetadata={({props}: any) =>
        ({durationInFrames: (props as any).durationInFrames ?? 70})}
    />
  </>
);
