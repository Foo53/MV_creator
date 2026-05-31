import React from 'react';
import {AbsoluteFill, Audio, Sequence} from 'remotion';
import {ShotScene} from './ShotScene';

export type TimelineShot = {
  shot_id: string;
  order: number;
  image_path?: string | null;
  image_src?: string | null;
  status: string;
  duration_seconds: number;
  caption: string;
  narration: string;
  motion: {
    type: string;
    start_scale: number;
    end_scale: number;
    start_x_percent: number;
    end_x_percent: number;
    start_y_percent: number;
    end_y_percent: number;
  };
  transition: {
    type: string;
    duration_seconds: number;
  };
};

export type TimelineManifest = {
  project: string;
  title: string;
  output_mode: string;
  fps: number;
  width: number;
  height: number;
  shots: TimelineShot[];
  lyrics_timeline: Record<string, string[]>;
  audio: Record<string, string | null>;
  todos: string[];
};

export const VimaxTimelineVideo: React.FC<TimelineManifest> = ({title, shots, fps, output_mode, lyrics_timeline, audio}) => {
  if (!shots || shots.length === 0) {
    return (
      <AbsoluteFill style={{backgroundColor: '#111827', color: 'white', alignItems: 'center', justifyContent: 'center'}}>
        <h1>{title}</h1>
      </AbsoluteFill>
    );
  }
  const isMV = output_mode === 'mv';
  let elapsedFrames = 0;

  return (
    <AbsoluteFill style={{backgroundColor: '#05070a'}}>
      {audio?.bgm ? <Audio src={audio.bgm} /> : null}
      {shots.map((shot, index) => {
        const shotFrames = Math.max(1, Math.ceil(shot.duration_seconds * fps));
        const requestedTransitionFrames = shot.transition.type === 'crossfade'
          ? Math.max(0, Math.ceil(shot.transition.duration_seconds * fps))
          : 0;
        const transitionInFrames = index === 0 ? 0 : Math.min(requestedTransitionFrames, shotFrames - 1, elapsedFrames);
        const from = Math.max(0, elapsedFrames - transitionInFrames);
        const durationInFrames = shotFrames + transitionInFrames;
        elapsedFrames += shotFrames;
        return (
          <Sequence key={shot.shot_id} from={from} durationInFrames={durationInFrames}>
            <ShotScene
              shot={shot}
              isMV={isMV}
              lyricsLines={lyrics_timeline?.[shot.shot_id] || []}
              transitionInFrames={transitionInFrames}
              isLast={index === shots.length - 1}
            />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
