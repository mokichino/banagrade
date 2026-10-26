import { onBeforeUnmount, onMounted, ref } from 'vue'
import { wsUrl } from './useApi.js'

const DATA_EVENTS = new Set(['scan_completed', 'scan_disputed', 'dispute_deleted', 'session_updated'])

/** WebSocket link to /ws/live with reconnect. Tracks LED + FSM state and signals data refreshes. */
export function useLive(onDataChanged) {
  const connection = ref('Connecting')
  const led = ref('offline')
  const fsmState = ref(null)
  const lastScan = ref(null)
  let socket
  let retry
  let attempt = 0
  let closed = false

  function connect() {
    socket = new WebSocket(wsUrl('/ws/live'))
    socket.onopen = () => { connection.value = 'Connected'; attempt = 0 }
    socket.onmessage = message => {
      let event
      try { event = JSON.parse(message.data) } catch { return }
      if (event.led) led.value = event.led
      if (event.pipeline?.led?.state) led.value = event.pipeline.led.state
      if (event.state) fsmState.value = event.state
      if (event.pipeline?.state) fsmState.value = event.pipeline.state
      if (event.event_type === 'scan_completed' && event.scan) lastScan.value = event.scan
      if (DATA_EVENTS.has(event.event_type)) onDataChanged?.(event)
    }
    socket.onclose = () => {
      connection.value = 'Disconnected'
      led.value = 'offline'
      if (closed) return
      attempt += 1
      retry = window.setTimeout(connect, Math.min(15000, 1000 * 2 ** attempt))
    }
    socket.onerror = () => { connection.value = 'Unavailable' }
  }

  onMounted(connect)
  onBeforeUnmount(() => { closed = true; window.clearTimeout(retry); socket?.close() })
  return { connection, led, fsmState, lastScan }
}
