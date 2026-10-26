// Digital mirror of the Raspberry Pi 5 floor LEDs (thesis 3.6.5).
export const LED_STATES = {
  ready: { tone: 'ready', color: 'Green', label: 'System ready', detail: 'Waiting for a bunch in the detection zone' },
  capture: { tone: 'capture', color: 'White burst', label: 'Capturing', detail: 'Snapshot taken' },
  class_a: { tone: 'class-a', color: 'Yellow', label: 'Class A result', detail: 'Large hand (width ≥ 2730.07 px)' },
  class_b: { tone: 'class-b', color: 'Blue', label: 'Class B result', detail: 'Small hand (width < 2730.07 px)' },
  rejected: { tone: 'rejected', color: 'Red', label: 'Rejected', detail: 'Unhealthy at Stage 1' },
  booting: { tone: 'booting', color: 'Slow red blink', label: 'Booting / calibrating', detail: 'Camera starting, autofocus locking' },
  error: { tone: 'error', color: 'Fast red blink', label: 'Hardware error', detail: 'Camera blocked, lighting or pipeline fault' },
  check: { tone: 'error', color: 'Fast red blink', label: 'Check by hand', detail: 'Last bunch not graded · reason on its box and in Recent Scans' },
  offline: { tone: 'offline', color: 'Off', label: 'Backend offline', detail: 'No connection to the edge device' }
}

export const LED_LEGEND = ['ready', 'class_a', 'class_b', 'rejected', 'booting', 'check', 'error']

export function ledInfo(state) {
  return LED_STATES[state] || LED_STATES.offline
}

// How each of the four physical lamps behaves in a given state (thesis 3.6.5).
// Values: 'on' (steady), 'pulse', 'flash', 'slow' (slow blink), 'fast' (fast blink), 'off'.
export const LAMPS = [
  { key: 'green', label: 'Green', meaning: 'System ready' },
  { key: 'yellow', label: 'Yellow', meaning: 'Class A' },
  { key: 'blue', label: 'Blue', meaning: 'Class B' },
  { key: 'red', label: 'Red', meaning: 'Rejected / error' }
]

const ALL_OFF = { green: 'off', yellow: 'off', blue: 'off', red: 'off' }

export function lampPattern(state) {
  switch (state) {
    case 'ready': return { ...ALL_OFF, green: 'on' }
    case 'class_a': return { ...ALL_OFF, yellow: 'on' }
    case 'class_b': return { ...ALL_OFF, blue: 'on' }
    case 'rejected': return { ...ALL_OFF, red: 'on' }
    case 'booting': return { ...ALL_OFF, red: 'slow' }
    case 'error':
    case 'check': return { ...ALL_OFF, red: 'fast' }
    case 'capture': return { green: 'flash', yellow: 'flash', blue: 'flash', red: 'flash' }
    default: return { ...ALL_OFF }
  }
}

export const DEMO_SEQUENCE = ['booting', 'ready', 'capture', 'class_a', 'ready', 'class_b', 'ready', 'rejected', 'error']
