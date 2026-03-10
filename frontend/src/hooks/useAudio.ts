import { useCallback, useEffect, useRef, useState } from 'react'

export interface AudioState {
  playing: boolean
  progress: number  // 0..1
  currentTime: number
  duration: number
}

export function useAudio(src: string | null) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [state, setState] = useState<AudioState>({
    playing: false,
    progress: 0,
    currentTime: 0,
    duration: 0,
  })

  useEffect(() => {
    if (!src) return
    const audio = new Audio(src)
    audioRef.current = audio

    const onUpdate = () => {
      setState({
        playing: !audio.paused,
        progress: audio.duration ? audio.currentTime / audio.duration : 0,
        currentTime: audio.currentTime,
        duration: audio.duration || 0,
      })
    }

    audio.addEventListener('timeupdate', onUpdate)
    audio.addEventListener('ended', onUpdate)
    audio.addEventListener('pause', onUpdate)
    audio.addEventListener('play', onUpdate)
    audio.addEventListener('loadedmetadata', onUpdate)

    return () => {
      audio.pause()
      audio.src = ''
      audio.removeEventListener('timeupdate', onUpdate)
      audio.removeEventListener('ended', onUpdate)
      audio.removeEventListener('pause', onUpdate)
      audio.removeEventListener('play', onUpdate)
      audio.removeEventListener('loadedmetadata', onUpdate)
      audioRef.current = null
    }
  }, [src])

  const play = useCallback(() => { audioRef.current?.play() }, [])
  const pause = useCallback(() => { audioRef.current?.pause() }, [])
  const stop = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.currentTime = 0
    }
  }, [])

  return { state, play, pause, stop }
}
