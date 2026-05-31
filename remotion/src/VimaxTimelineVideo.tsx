import React from 'react';
import {AbsoluteFill, Audio, Series} from 'remotion';
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
    strength: number;
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

  return (
    <AbsoluteFill style={{backgroundColor: '#05070a'}}>
      {audio?.bgm ? <Audio src={audio.bgm} /> : null}
      <Series>
        {shots.map((shot) => (
          <Series.Sequence key={shot.shot_id} durationInFrames={Math.max(1, Math.ceil(shot.duration_seconds * fps))}>
            <ShotScene shot={shot} title={title} isMV={isMV} lyricsLines={lyrics_timeline?.[shot.shot_id] || []} />
          </Series.Sequence>
        ))}
      </Series>
    </AbsoluteFill>
  );
};
