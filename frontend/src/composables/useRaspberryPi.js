import { onBeforeUnmount, ref } from 'vue'

export function useRaspberryPi() {
  const enabled = ref(false)
  const connected = ref(false)
  let socket

  function connect() {
    if (!enabled.value) return
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    socket = new WebSocket(`${protocol}://${window.location.host}/ws/telemetry`)
    socket.onopen = () => { connected.value = true }
    socket.onclose = () => { connected.value = false }
  }

  function disconnect() {
    socket?.close()
    socket = undefined
    connected.value = false
  }

  onBeforeUnmount(disconnect)
  return { enabled, connected, connect, disconnect }
}
