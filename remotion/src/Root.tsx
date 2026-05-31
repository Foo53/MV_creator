import React from 'react';
import {Composition} from 'remotion';
import {TimelineManifest, VimaxTimelineVideo} from './VimaxTimelineVideo';

const defaultProps: TimelineManifest = {
  project: 'preview',
  title: 'ViMax Lite Preview',
  output_mode: 'remotion',
  fps: 30,
  width: 1920,
  height: 1080,
  shots: [],
  audio: {bgm: null, se: null, narration: null},
  todos: [],
};

export const Root: React.FC = () => {
  return (
    <Composition
      id="VimaxTimelineVideo"
      component={VimaxTimelineVideo}
      defaultProps={defaultProps}
      fps={30}
      width={1920}
      height={1080}
      durationInFrames={150}
      calculateMetadata={({props}) => {
        const fps = props.fps || 30;
        const durationInFrames = Math.max(
          1,
          Math.ceil((props.shots || []).reduce((sum, shot) => sum + shot.duration_seconds, 0) * fps),
        );
        return {
          fps,
          width: props.width || 1920,
          height: props.height || 1080,
          durationInFrames,
        };
      }}
    />
  );
};
