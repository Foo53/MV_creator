import React from 'react';
import {AbsoluteFill, Easing, Img, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {TimelineShot} from './VimaxTimelineVideo';

type Props = {
  shot: TimelineShot;
  isMV?: boolean;
  lyricsLines?: string[];
  transitionInFrames?: number;
  isLast?: boolean;
};

const META_TAG_RE = /^\[.+\]\s*$/;

export const ShotScene: React.FC<Props> = ({shot, isMV, lyricsLines, transitionInFrames = 0, isLast = false}) => {
  const frame = useCurrentFrame();
  const {durationInFrames, width} = useVideoConfig();
  const fadeOutFrames = isLast ? Math.min(18, Math.floor(durationInFrames * 0.18)) : 0;
  const fadeInOpacity = transitionInFrames > 0
    ? interpolate(frame, [0, transitionInFrames], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})
    : 1;
  const fadeOutOpacity = fadeOutFrames > 0
    ? interpolate(frame, [durationInFrames - fadeOutFrames, durationInFrames], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})
    : 1;
  const opacity = Math.min(fadeInOpacity, fadeOutOpacity);
  const progress = durationInFrames <= 1 ? 0 : frame / (durationInFrames - 1);
  const transform = motionTransform(shot.motion, progress);

  const scale = width / 1920;
  const baseFontSize = 42 * scale;

  const currentLyric = isMV && lyricsLines && lyricsLines.length > 0
    ? lyricAtFrame(lyricsLines, frame, durationInFrames)
    : null;

  return (
    <AbsoluteFill style={{backgroundColor: '#05070a', opacity}}>
      {shot.image_src ? (
        <Img
          src={shot.image_src}
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            transform,
          }}
        />
      ) : (
        <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', color: 'white'}}>
          <div style={{fontSize: 54 * scale, fontWeight: 700}}>{shot.shot_id}</div>
          <div style={{fontSize: 28 * scale, marginTop: 16}}>Missing image</div>
        </AbsoluteFill>
      )}
      {isMV && currentLyric ? (
        <div
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            bottom: 80 * scale,
            display: 'flex',
            justifyContent: 'center',
            padding: `0 ${48 * scale}px`,
            pointerEvents: 'none',
          }}
        >
          <div
            style={{
              padding: `${18 * scale}px ${32 * scale}px`,
              background: 'rgba(5, 7, 10, 0.65)',
              borderRadius: 8 * scale,
              color: 'white',
              fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
              fontSize: baseFontSize,
              fontWeight: 700,
              lineHeight: 1.5,
              textAlign: 'center',
              textShadow: '0 2px 12px rgba(0,0,0,0.6)',
              maxWidth: '90%',
            }}
          >
            {currentLyric}
          </div>
        </div>
      ) : (
        <div
          style={{
            position: 'absolute',
            left: 96 * scale,
            right: 96 * scale,
            bottom: 72 * scale,
            padding: `${24 * scale}px ${30 * scale}px`,
            background: 'rgba(5, 7, 10, 0.68)',
            color: 'white',
            fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
            fontSize: baseFontSize,
            fontWeight: 700,
            lineHeight: 1.32,
            textShadow: '0 2px 12px rgba(0,0,0,0.6)',
            borderLeft: `${8 * scale}px solid #2dd4bf`,
          }}
        >
          {shot.caption}
        </div>
      )}
    </AbsoluteFill>
  );
};

const lyricAtFrame = (lines: string[], frame: number, totalFrames: number): string | null => {
  const visibleLines = lines.filter((l) => !META_TAG_RE.test(l.trim()));
  if (visibleLines.length === 0) return null;
  const framesPerLine = Math.max(1, totalFrames / visibleLines.length);
  const index = Math.min(Math.floor(frame / framesPerLine), visibleLines.length - 1);
  return visibleLines[index];
};

const motionTransform = (motion: TimelineShot['motion'], progress: number): string => {
  const eased = Easing.inOut(Easing.cubic)(progress);
  const scale = interpolate(eased, [0, 1], [motion.start_scale, motion.end_scale]);
  const x = interpolate(eased, [0, 1], [motion.start_x_percent, motion.end_x_percent]);
  const y = interpolate(eased, [0, 1], [motion.start_y_percent, motion.end_y_percent]);
  return `scale(${scale}) translate(${x}%, ${y}%)`;
};
