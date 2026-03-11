import { useAudio } from '@shared/hooks/useAudio'
import '@shared/styles/components.css'

function fmt(sec: number) {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

interface AudioPlayerProps {
  src: string | null
}

export function AudioPlayer({ src }: AudioPlayerProps) {
  const { state, play, pause, stop } = useAudio(src)

  return (
    <div className="audio-player">
      <button
        className="btn-ghost"
        style={{ padding: '3px 8px', fontSize: '14px' }}
        disabled={!src}
        onClick={state.playing ? pause : play}
        title={state.playing ? 'Pause' : 'Play'}
      >
        {state.playing ? '⏸' : '▶'}
      </button>
      <button
        className="btn-ghost"
        style={{ padding: '3px 8px', fontSize: '14px' }}
        disabled={!src}
        onClick={stop}
        title="Stop"
      >
        ⏹
      </button>
      <div className="audio-progress">
        <div
          className="audio-progress-fill"
          style={{ width: `${state.progress * 100}%` }}
        />
      </div>
      <span className="audio-time">
        {fmt(state.currentTime)} / {fmt(state.duration)}
      </span>
    </div>
  )
}
