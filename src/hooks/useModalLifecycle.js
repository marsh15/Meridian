import { useCallback, useEffect, useRef, useState } from 'react'

/* Escape to close, body scroll lock, and a short exit animation
   before the caller actually unmounts the modal */
export function useModalLifecycle(onClose) {
  const [closing, setClosing] = useState(false)
  const timer = useRef(null)

  const close = useCallback(() => {
    if (closing) return
    setClosing(true)
    timer.current = setTimeout(onClose, 190)
  }, [closing, onClose])

  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [close])

  /* clear any pending unmount only on real teardown, never mid-close */
  useEffect(() => () => clearTimeout(timer.current), [])

  return { closing, close }
}
