import { ref } from 'vue'
import { request } from './useApi.js'

export const POWER_ACTIONS = {
  reboot: { label: 'Reboot', confirm: 'Reboot the Pi? Grading stops for about a minute, then the dashboard reconnects on its own.', done: 'Rebooting. The dashboard reconnects in about a minute.' },
  shutdown: { label: 'Shut down', confirm: 'Shut down the Pi? It stays off until someone unplugs it and plugs it back in.', done: 'Shutting down. Wait until the Pi’s green activity light stops blinking before unplugging it.' }
}

export const POWER_RULE_MISSING = 'The service is not allowed to reboot or shut down the Pi yet. Install deploy/50-banagrade-power.rules (see README).'

/** Pick an action, confirm it, then POST it. Shared by the System Status card and the sidebar shortcut. */
export function usePowerAction() {
  const pending = ref('')
  const busy = ref(false)
  const message = ref('')
  const error = ref('')
  const done = ref(false)

  function choose(action) {
    pending.value = action
    message.value = ''
    error.value = ''
  }

  async function confirm() {
    busy.value = true
    error.value = ''
    try {
      await request('/api/system/power', { method: 'POST', body: JSON.stringify({ action: pending.value }) })
      message.value = POWER_ACTIONS[pending.value].done
      done.value = true
    } catch (failure) {
      error.value = failure.message
    } finally {
      busy.value = false
      pending.value = ''
    }
  }

  return { pending, busy, message, error, done, choose, confirm }
}
