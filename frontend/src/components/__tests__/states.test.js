// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ScanTable from '../ScanTable.vue'
import DisputeModal from '../DisputeModal.vue'
import ShiftSelect from '../ShiftSelect.vue'
import VoidDialog from '../VoidDialog.vue'
import ModelsCard from '../status/ModelsCard.vue'
import OperationalSummaryCard from '../status/OperationalSummaryCard.vue'
import HardwareStatusCard from '../status/HardwareStatusCard.vue'
import DriftCard from '../status/DriftCard.vue'
import CameraCard from '../status/CameraCard.vue'
import PowerCard from '../status/PowerCard.vue'
import PowerDialog from '../PowerDialog.vue'
import AppSidebar from '../layout/AppSidebar.vue'
import DashboardView from '../../views/DashboardView.vue'
import HistoryView from '../../views/HistoryView.vue'
import SystemStatusView from '../../views/SystemStatusView.vue'

vi.mock('vue-chartjs', () => ({ Doughnut: { template: '<canvas />' }, Line: { name: 'LineChart', props: ['data', 'options', 'plugins'], template: '<canvas />' } }))

function mockFetch(routes) {
  const fetch = vi.fn(async url => {
    const path = String(url).split('?')[0]
    const body = routes[path]
    if (body === undefined) return { ok: false, status: 503, json: async () => ({ detail: 'Service unavailable' }) }
    return { ok: true, status: 200, json: async () => body }
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

afterEach(() => vi.unstubAllGlobals())

const indicator = (key, status, extra = {}) => ({ key, label: key.replace(/_/g, ' '), unit: 'rate', value: null, baseline: 0, limit: 0.05, direction: 'above', samples: 0, status, ...extra })

describe('ScanTable', () => {
  it('shows an empty row when no scans match', () => {
    const wrapper = mount(ScanTable, { props: { scans: [] } })
    expect(wrapper.find('td.empty').text()).toBe('No scan records match.')
  })

  it('labels a failed scan as a technical failure, never as Rejected', () => {
    const scan = { scan_id: 'f1', captured_at: '2026-10-25T08:00:00Z', stage1_status: 'Unhealthy', stage1_confidence: 0.62, final_grade: null, processing_status: 'failed' }
    const text = mount(ScanTable, { props: { scans: [scan] } }).text()
    expect(text).toContain('Technical failure')
    expect(text).not.toContain('Rejected')
  })

  it('marks disputed scans and opens the dispute form from the flag icon', async () => {
    const disputed = { scan_id: 'd1', captured_at: '2026-10-25T08:00:00Z', stage1_status: 'Healthy', final_grade: 'Class A', disputed: 1, model_grade: 'Class B', dispute_reason: 'Middle finger 12.0 cm' }
    const plain = { scan_id: 'p1', captured_at: '2026-10-25T08:01:00Z', stage1_status: 'Healthy', final_grade: 'Class B', disputed: 0 }
    const wrapper = mount(ScanTable, { props: { scans: [disputed, plain] } })
    const badges = wrapper.findAll('.disputed-badge')
    expect(badges).toHaveLength(1)
    expect(badges[0].attributes('title')).toBe('Model graded Class B · Middle finger 12.0 cm')
    const buttons = wrapper.findAll('.dispute-button')
    expect(buttons[1].text()).toBe('')
    expect(buttons[1].attributes('aria-label')).toBe('Dispute #SCN-P1')
    await buttons[0].trigger('click')
    expect(wrapper.emitted('dispute')[0][0]).toEqual(disputed)
  })
})

describe('DisputeModal', () => {
  it('deletes all disputes after confirming and goes back to the scanner grade', async () => {
    const items = [
      { id: 'x2', reason: 'Middle finger 12.5 cm', corrected_grade: 'Class A', original_grade: 'Class B', created_at: '2026-10-27T05:00:00Z' },
      { id: 'x1', reason: 'Middle finger 12.5 cm', corrected_grade: 'Class A', original_grade: 'Class B', created_at: '2026-10-27T04:00:00Z' }
    ]
    const fetch = vi.fn(async (url, options = {}) => {
      if (options.method === 'DELETE') return { ok: true, status: 200, json: async () => ({ scan_id: 's1', final_grade: 'Class B', deleted_disputes: 2 }) }
      return { ok: true, status: 200, json: async () => ({ items }) }
    })
    vi.stubGlobal('fetch', fetch)
    const wrapper = mount(DisputeModal, { props: { scan: null } })
    await wrapper.setProps({ scan: { scan_id: 's1', final_grade: 'Class A', disputed: 1 } })
    await flushPromises()
    expect(wrapper.findAll('.dispute-history li')).toHaveLength(2)
    expect(wrapper.text()).toContain('Class B → Class A')

    await wrapper.findAll('.dispute-history button').find(button => button.text() === 'Delete disputes').trigger('click')
    expect(wrapper.find('.dispute-confirm').text()).toContain('Delete all 2 disputes? The grade goes back to Class B')
    expect(fetch).toHaveBeenCalledTimes(1)
    await wrapper.findAll('.dispute-confirm button').find(button => button.text() === 'Delete').trigger('click')
    await flushPromises()

    expect(fetch).toHaveBeenCalledWith('/api/inspection/scans/s1/disputes', expect.objectContaining({ method: 'DELETE' }))
    expect(wrapper.find('.dispute-history').exists()).toBe(false)
    expect(wrapper.text()).toContain('Recorded: Class B')
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })

  it('starts with no grade chosen, refuses the recorded grade and asks for the finger length', async () => {
    mockFetch({ '/api/inspection/scans/s2/disputes': { items: [] } })
    const wrapper = mount(DisputeModal, { props: { scan: null } })
    await wrapper.setProps({ scan: { scan_id: 's2', final_grade: 'Class B' } })
    await flushPromises()
    const save = () => wrapper.find('.modal-actions .primary-button')
    expect(wrapper.find('select').element.value).toBe('')
    expect(save().attributes('disabled')).toBeDefined()

    await wrapper.find('select').setValue('Class B')
    expect(wrapper.find('.form-error').text()).toContain('already recorded as Class B')
    expect(save().attributes('disabled')).toBeDefined()

    await wrapper.find('select').setValue('Class A')
    expect(wrapper.find('.form-error').exists()).toBe(false)
    expect(wrapper.find('.form-hint').text()).toContain('12 cm or more')
    expect(wrapper.find('textarea').attributes('placeholder')).toContain('middle finger 12.5 cm')
    expect(save().attributes('disabled')).toBeUndefined()
  })

  it('treats a missing grade as a recorded technical failure', async () => {
    mockFetch({ '/api/inspection/scans/s3/disputes': { items: [] } })
    const wrapper = mount(DisputeModal, { props: { scan: null } })
    await wrapper.setProps({ scan: { scan_id: 's3', final_grade: null } })
    await wrapper.find('select').setValue('Technical Failure')
    expect(wrapper.find('.form-error').text()).toContain('already recorded as Technical failure')
  })
})

describe('voiding instead of deleting', () => {
  const voided = { scan_id: 'v1', captured_at: '2026-10-26T20:28:23Z', stage1_status: 'Healthy', final_grade: 'Rejected', voided_at: '2026-10-27T06:40:00Z', void_reason: 'Duplicate scan of the same bunch' }
  const counting = { scan_id: 'c1', captured_at: '2026-10-26T20:45:47Z', stage1_status: 'Healthy', final_grade: 'Class A' }

  it('ScanTable keeps a voided scan listed, marked, with its reason and no dispute', async () => {
    const wrapper = mount(ScanTable, { props: { scans: [voided, counting] } })
    const [row, plain] = wrapper.findAll('tbody tr')
    expect(row.classes()).toContain('voided')
    expect(row.find('.voided-badge').text()).toBe('Voided')
    expect(row.find('.failure-reason').text()).toContain('Duplicate scan of the same bunch')
    expect(row.find('.dispute-button').attributes('disabled')).toBeDefined()
    expect(row.find('.void-button').attributes('aria-label')).toBe('Count again #SCN-V1')
    expect(plain.find('.void-button').attributes('aria-label')).toBe('Void #SCN-C1')
    await plain.find('.void-button').trigger('click')
    expect(wrapper.emitted('void')[0][0]).toEqual({ scans: [counting], restore: false })
  })

  it('VoidDialog needs a reason, offers common ones and posts the scan ids', async () => {
    const fetch = mockFetch({ '/api/inspection/scans/void': { voided: 1, skipped: 0 } })
    const wrapper = mount(VoidDialog, { props: { request: null }, attachTo: document.body })
    await wrapper.setProps({ request: { scans: [counting], restore: false } })
    expect(wrapper.find('h2').text()).toBe('Void #SCN-C1')
    expect(wrapper.text()).toContain('Nothing is deleted')
    await flushPromises()
    expect(document.activeElement).toBe(wrapper.find('textarea').element)
    const submit = () => wrapper.find('.modal-actions .primary-button')
    expect(submit().attributes('disabled')).toBeDefined()
    await wrapper.findAll('.reason-chips button').find(button => button.text() === 'Test object, not a bunch').trigger('click')
    expect(submit().attributes('disabled')).toBeUndefined()
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(fetch).toHaveBeenCalledWith('/api/inspection/scans/void', expect.objectContaining({ method: 'POST', body: JSON.stringify({ scan_ids: ['c1'], reason: 'Test object, not a bunch' }) }))
    expect(wrapper.emitted('saved')).toHaveLength(1)
    wrapper.unmount()
  })

  it('VoidDialog counts a batch again and leaves out scans that already count', async () => {
    const fetch = mockFetch({ '/api/inspection/scans/unvoid': { restored: 2, skipped: 0 } })
    const wrapper = mount(VoidDialog, { props: { request: null } })
    await wrapper.setProps({ request: { scans: [voided, counting, { ...voided, scan_id: 'v2' }], restore: true } })
    expect(wrapper.find('h2').text()).toBe('Count 2 scans again')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ scan_ids: ['v1', 'v2'] })
  })
})

describe('status cards with no data', () => {
  it('ModelsCard shows the load error and Missing badges', () => {
    const models = { available: false, error: 'Model file not found: stage1_best.pt', models: [{ key: 'stage1', label: 'stage1_best.pt', architecture: 'YOLO11n-cls', task: 'Health', path: '/m/stage1_best.pt', state: 'missing' }] }
    const wrapper = mount(ModelsCard, { props: { models } })
    expect(wrapper.find('.alert').text()).toContain('Model file not found')
    expect(wrapper.find('.status-badge').text()).toBe('Missing')
    expect(wrapper.text()).toContain('Raw RGB, whole frame resized to 224 × 224')
    expect(wrapper.text()).toContain('Stage 2 detector · 400 ms stability check')  // fallback when the API names no trigger
    const trained = mount(ModelsCard, { props: { models: { ...models, trigger: 'YOLO11n-presence detector' } } })
    expect(trained.text()).toContain('YOLO11n-presence detector · 400 ms stability check')
  })

  it('OperationalSummaryCard renders placeholders without telemetry', () => {
    const text = mount(OperationalSummaryCard, { props: { telemetry: null } }).text()
    expect(text).toContain('No completed scans yet')
    expect(text).toContain('—')
    expect(text).not.toContain('Connected')
  })

  it('HardwareStatusCard lists exactly four components, all unavailable', () => {
    const rows = mount(HardwareStatusCard, { props: {} }).findAll('.diagnostic-row')
    expect(rows).toHaveLength(4)
    expect(rows.map(row => row.find('.status-badge').text())).toEqual(['Unreachable', 'Unavailable', 'Unavailable', 'Unavailable'])
  })

  it('DriftCard handles missing, insufficient and drifting reports', () => {
    expect(mount(DriftCard, { props: { drift: null } }).text()).toContain('Drift indicators unavailable.')

    const insufficient = { status: 'insufficient_data', min_samples: 30, scans_considered: 4, indicators: [indicator('low_confidence_rate', 'insufficient_data')] }
    const quiet = mount(DriftCard, { props: { drift: insufficient } })
    expect(quiet.text()).toContain('Needs at least 30 scans')
    expect(quiet.find('.drift-grid strong').text()).toBe('—')

    const drifting = { status: 'drift_suspected', min_samples: 30, scans_considered: 200, indicators: [indicator('low_confidence_rate', 'warn', { value: 0.125, samples: 200 })] }
    const loud = mount(DriftCard, { props: { drift: drifting } })
    expect(loud.find('.drift-summary').text()).toBe('Review disputed frames: low confidence rate.')
    expect(loud.find('.drift-grid strong').text()).toBe('12.5%')
    expect(loud.find('a').attributes('href')).toBe('/api/exports/disputes.zip')
  })
})

describe('lens focus and power', () => {
  const camera = extra => ({ camera: { available: true, expected_distance_cm: 45, ...extra } })

  it('CameraCard shows the fixed lens position calibrated at the rig height', () => {
    expect(mount(CameraCard, { props: { pipeline: camera({ focus: 'fixed', lens_position_dioptres: 0.99 }) } }).text()).toContain('Fixed · 0.99 dpt (set at 45 cm)')
    expect(mount(CameraCard, { props: { pipeline: camera({ focus: 'autofocus', lens_position_dioptres: 1.31 }) } }).text()).toContain('Autofocus · 1.31 dpt')
    expect(mount(CameraCard, { props: { pipeline: camera({ focus: 'unset', lens_position_dioptres: null }) } }).find('dd.bad').text()).toBe('Not set')
  })

  it('CameraCard draws the placement guide over the full view, can hide it and go full screen', async () => {
    const wrapper = mount(CameraCard, { props: { pipeline: camera({ focus: 'fixed', lens_position_dioptres: 0.99 }) } })
    expect(wrapper.find('.camera-frame svg.placement-guide').attributes('viewBox')).toBe('0 0 4608 2592')
    expect(wrapper.find('.guide-box').attributes('width')).toBe('2648')
    await wrapper.find('.guide-toggle input').setValue(false)
    expect(wrapper.find('.placement-guide').exists()).toBe(false)
    await wrapper.findAll('.camera-actions button').find(b => b.text() === 'Full screen').trigger('click')
    expect(wrapper.find('.camera-preview').classes()).toContain('expanded')
    await wrapper.find('.preview-exit').trigger('click')
    expect(wrapper.find('.camera-preview').classes()).not.toContain('expanded')
  })

  it('CameraCard checks the camera alignment from a sheet and outlines it', async () => {
    const tilted = { corners: [[1100, 650], [3095, 650], [3250, 2229], [948, 2291]], front_back_ratio: 1.154, side_ratio: 0.962, front_back_tilt_deg: 17.9, side_tilt_deg: -3.7, height_cm: 46.3, level: false, height_ok: true }
    const fetch = mockFetch({ '/api/camera/alignment': tilted })
    const wrapper = mount(CameraCard, { props: { pipeline: camera({ focus: 'fixed', lens_position_dioptres: 0.99 }) } })
    await wrapper.findAll('.camera-actions button').find(b => b.text() === 'Check camera alignment').trigger('click')
    await flushPromises()
    expect(fetch.mock.calls[0][1].method).toBe('POST')
    const text = wrapper.find('.alignment-result').text()
    expect(text).toContain('17.9° towards the top of the view · tip the lens towards the bottom')
    expect(text).toContain('3.7° towards the right of the view · tip the lens towards the left')
    expect(text).toContain('≈ 46 cm')
    expect(wrapper.find('polygon.guide-sheet.tilted').attributes('points')).toBe('1100,650 3095,650 3250,2229 948,2291')
    await wrapper.find('.alignment-result .text-button').trigger('click')
    expect(wrapper.find('polygon.guide-sheet').exists()).toBe(false)
  })

  it('CameraCard locks white balance from a sheet and shows the saved settings', async () => {
    const fetch = mockFetch({ '/api/camera/white-balance': { colour_gains: [1.19, 0.88], sheet_bgr: [190, 190, 190], cast: 0.004, neutral: true } })
    const wrapper = mount(CameraCard, { props: { pipeline: camera({ white_balance: { mode: 'auto' }, brightness: { exposure_value: 0, set_at: null, dataset_bunch_brightness: 149 } }) } })
    expect(wrapper.text()).toContain('Automatic (drifts)')
    expect(wrapper.text()).toContain('Automatic (EV 0)')
    await wrapper.findAll('.tuning-actions button').find(b => b.text() === 'Set white balance from sheet').trigger('click')
    await flushPromises()
    expect(fetch.mock.calls[0][0]).toContain('/api/camera/white-balance')
    expect(wrapper.text()).toContain('White balance locked: the sheet is neutral (within 0.4%)')
    const locked = mount(CameraCard, { props: { pipeline: camera({ white_balance: { mode: 'locked', colour_gains: [1.19, 0.88] }, brightness: { exposure_value: -0.6, bunch_brightness: 150.2, dataset_bunch_brightness: 149, set_at: 'now' } }) } })
    expect(locked.text()).toContain('Locked to sheet · R 1.19 B 0.88')
    expect(locked.text()).toContain('EV -0.6 · bunch 150.2 vs dataset 149')
  })

  it('PowerCard disables both buttons until polkit allows them', () => {
    const power = { reboot: { allowed: false, permission: 'challenge' }, shutdown: { allowed: false, permission: 'challenge' } }
    const wrapper = mount(PowerCard, { props: { power } })
    expect(wrapper.findAll('button').every(button => button.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.text()).toContain('50-banagrade-power.rules')
  })

  it('PowerCard asks before rebooting, then posts the action', async () => {
    const fetch = mockFetch({ '/api/system/power': { action: 'reboot', delay_s: 1.5 } })
    const power = { reboot: { allowed: true, permission: 'yes' }, shutdown: { allowed: true, permission: 'yes' } }
    const wrapper = mount(PowerCard, { props: { power } })
    await wrapper.findAll('button')[0].trigger('click')
    expect(fetch).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Reboot the Pi?')
    await wrapper.find('button.danger').trigger('click')
    await flushPromises()
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ action: 'reboot' })
    expect(wrapper.text()).toContain('Rebooting.')
  })
})

describe('sidebar power shortcut', () => {
  it('the sidebar power icon asks to open the dialog', async () => {
    const wrapper = mount(AppSidebar, { props: { views: [], active: 'dashboard' } })
    await wrapper.find('button.power-shortcut').trigger('click')
    expect(wrapper.emitted('power')).toHaveLength(1)
    expect(wrapper.find('button.power-shortcut svg').exists()).toBe(true)
  })

  it('PowerDialog loads the permission when opened and confirms before shutting down', async () => {
    const power = { reboot: { allowed: true, permission: 'yes' }, shutdown: { allowed: true, permission: 'yes' } }
    const fetch = mockFetch({ '/api/system/status': { power }, '/api/system/power': { action: 'shutdown', delay_s: 1.5 } })
    const wrapper = mount(PowerDialog, { props: { open: false } })
    expect(wrapper.find('[role=dialog]').exists()).toBe(false)
    await wrapper.setProps({ open: true })
    await flushPromises()
    const shutdown = wrapper.findAll('.power-actions button')[1]
    expect(shutdown.attributes('disabled')).toBeUndefined()
    await shutdown.trigger('click')
    expect(wrapper.text()).toContain('Shut down the Pi?')
    await wrapper.find('button.danger').trigger('click')
    await flushPromises()
    expect(JSON.parse(fetch.mock.calls.at(-1)[1].body)).toEqual({ action: 'shutdown' })
    expect(wrapper.text()).toContain('Shutting down.')
  })

  it('PowerDialog keeps the buttons disabled without the polkit rule', async () => {
    const power = { reboot: { allowed: false, permission: 'challenge' }, shutdown: { allowed: false, permission: 'challenge' } }
    mockFetch({ '/api/system/status': { power } })
    const wrapper = mount(PowerDialog, { props: { open: false } })
    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(wrapper.findAll('.power-actions button').every(button => button.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.text()).toContain('50-banagrade-power.rules')
  })
})

describe('views', () => {
  it('Dashboard shows empty charts for a fresh shift', async () => {
    mockFetch({
      '/api/analytics/summary': { total_scans: 0, total_completed_scans: 0, class_a_count: 0, class_b_count: 0, rejected_count: 0, technical_failure_count: 0 },
      '/api/analytics/trend': { items: [] },
      '/api/sessions': { items: [] },
      '/api/inspection/scans': { items: [] }
    })
    const wrapper = mount(DashboardView)
    await flushPromises()
    expect(wrapper.text()).toContain('No accepted bunches in this shift yet.')
    expect(wrapper.text()).toContain('No graded scans in this shift yet.')
    expect(wrapper.text()).toContain('No graded scans yet')  // a share of nothing is not 0%
    expect(wrapper.emitted('error')).toBeUndefined()
  })

  const SHIFTS = [
    { id: 'now', name: 'Toril batch', notes: 'Shift started from dashboard', status: 'open', started_at: '2026-10-27T05:30:00Z', ended_at: null, scan_count: 3 },
    { id: 'old', name: null, notes: 'Shift opened automatically at startup', status: 'closed', started_at: '2026-10-26T18:48:29Z', ended_at: '2026-10-27T05:30:00Z', scan_count: 97 },
    { id: 'restart', name: null, notes: 'Shift opened automatically at startup', status: 'closed', started_at: '2026-10-26T18:32:11Z', ended_at: '2026-10-26T18:48:29Z', scan_count: 0 }
  ]
  const SUMMARY = { total_scans: 97, total_completed_scans: 93, class_a_count: 24, class_b_count: 45, rejected_count: 24, technical_failure_count: 4, export_acceptance_rate: 74.19 }

  it('ShiftSelect lists past shifts by time, hides empty ones and recovers from a cleared one', async () => {
    const wrapper = mount(ShiftSelect, { props: { modelValue: 'gone', shifts: SHIFTS } })
    expect(wrapper.findAll('option').map(option => option.text())).toEqual(['Current shift', 'All shifts', 'Oct 27, 02:48 – 13:30 · 97 scans'])
    expect(wrapper.text()).not.toContain('opened automatically')
    expect(wrapper.emitted('update:modelValue')[0]).toEqual(['active'])
  })

  it('Dashboard grades share one denominator and the trend sits on a clock', async () => {
    mockFetch({
      '/api/analytics/summary': SUMMARY,
      '/api/analytics/trend': { items: [
        { bucket_start: '2026-10-26T19:15:00+00:00', total: 8, rejected: 7, rejection_rate: 87.5 },
        { bucket_start: '2026-10-27T05:15:00+00:00', total: 2, rejected: 0, rejection_rate: 0 }
      ] },
      '/api/sessions': { items: SHIFTS },
      '/api/inspection/scans': { items: [] }
    })
    const wrapper = mount(DashboardView)
    await flushPromises()
    expect(wrapper.findAll('.kpi-share').map(share => share.text())).toEqual(['25.8% of graded', '48.4% of graded', '25.8% of graded'])
    expect(wrapper.find('.yield-legend').text()).toContain('34.8%')
    expect(wrapper.find('.volume-foot').text()).toContain('4 technical failures, not counted in the rates')
    expect(wrapper.find('.chart-keys').text()).toContain('Shift average 25.8%')

    const chart = wrapper.findComponent({ name: 'LineChart' })
    expect(chart.props('data').datasets[0].data.map(point => point.y)).toEqual([87.5, null, 0])  // ten quiet hours break the line
    expect(chart.props('options').scales.x.type).toBe('linear')
    expect(chart.props('options').plugins.tooltip.callbacks.title([{ raw: { x: Date.parse('2026-10-26T19:15:00Z') } }])).toBe('Oct 27, 03:15–03:30')
    expect(wrapper.findAll('.chart-table tbody tr')).toHaveLength(2)
  })

  it('Dashboard marks a past shift and starts a named shift from a dialog', async () => {
    const fetch = mockFetch({
      '/api/analytics/summary': SUMMARY,
      '/api/analytics/trend': { items: [] },
      '/api/sessions': { items: SHIFTS },
      '/api/inspection/scans': { items: [] }
    })
    const wrapper = mount(DashboardView, { attachTo: document.body })
    await flushPromises()
    expect(fetch).toHaveBeenCalledWith(expect.stringMatching(/^\/api\/analytics\/trend\?session=active&bucket_minutes=15&utc_offset_minutes=480$/), expect.anything())
    expect(wrapper.find('.shift-meta').text()).toBe('Toril batch · Started Oct 27, 13:30')
    expect(wrapper.find('.scope-notice').exists()).toBe(false)

    await wrapper.find('select[aria-label="Shift"]').setValue('old')
    await flushPromises()
    expect(fetch).toHaveBeenCalledWith('/api/analytics/summary?session=old', expect.anything())
    expect(fetch).toHaveBeenCalledWith('/api/inspection/scans?session=old&limit=8', expect.anything())
    expect(wrapper.find('.shift-meta').text()).toBe('Ran for 10 h 42 min')
    expect(wrapper.find('.scope-notice').text()).toContain('Past shift.')
    expect(wrapper.find('.volume-card').text()).toContain('scanned in this shift')

    await wrapper.findAll('button').find(button => button.text() === 'Start new shift').trigger('click')
    const dialog = wrapper.find('[aria-labelledby="shift-title"]')
    expect(dialog.text()).toContain('The current shift (started Oct 27, 13:30, 3 scans) ends now')
    expect(document.activeElement).toBe(dialog.find('input').element)
    await dialog.find('input').setValue('  Toril batch 2  ')
    await dialog.trigger('submit')
    await flushPromises()
    expect(fetch).toHaveBeenCalledWith('/api/sessions', expect.objectContaining({ method: 'POST', body: JSON.stringify({ name: 'Toril batch 2' }) }))
    expect(wrapper.find('[aria-labelledby="shift-title"]').exists()).toBe(false)
    expect(wrapper.find('select[aria-label="Shift"]').element.value).toBe('active')
    expect(wrapper.find('.scope-notice').exists()).toBe(false)
    wrapper.unmount()
  })

  it('Dashboard goes back to the current shift from the past-shift notice', async () => {
    mockFetch({ '/api/analytics/summary': SUMMARY, '/api/analytics/trend': { items: [] }, '/api/sessions': { items: SHIFTS }, '/api/inspection/scans': { items: [] } })
    const wrapper = mount(DashboardView, { props: { scope: 'old', 'onUpdate:scope': scope => wrapper.setProps({ scope }) } })
    await flushPromises()
    await wrapper.find('.scope-notice button').trigger('click')
    expect(wrapper.emitted('update:scope').at(-1)).toEqual(['active'])
    expect(wrapper.find('.scope-notice').exists()).toBe(false)
  })

  const scan = (id, grade, extra = {}) => ({ scan_id: id, final_grade: grade, processing_status: grade ? 'completed' : 'failed', captured_at: '2026-10-26T19:00:00Z', ...extra })

  it('History follows the shared shift and exports exactly the rows listed', async () => {
    const fetch = mockFetch({ '/api/inspection/scans': { items: [scan('a1', 'Class B'), scan('r1', 'Rejected', { dispute_reason: '=1+1' })] }, '/api/sessions': { items: SHIFTS } })
    const blobs = []
    vi.stubGlobal('URL', { createObjectURL: blob => { blobs.push(blob); return 'blob:csv' }, revokeObjectURL: vi.fn() })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const wrapper = mount(HistoryView)
    await flushPromises()
    expect(fetch).toHaveBeenCalledWith('/api/inspection/scans?limit=5000&session=active', expect.anything())
    expect(wrapper.find('h2').text()).toBe('Current shift')
    expect(wrapper.find('.result-count').text()).toBe('2 scans')
    // Deleting scans is not offered at all; voiding is per row or for a narrowed list.
    expect(wrapper.text()).not.toContain('Clear all scans')

    await wrapper.find('select[aria-label="Filter by grade"]').setValue('Rejected')
    expect(wrapper.find('.result-count').text()).toBe('1 of 2 scans match')
    expect(wrapper.findAll('.export-actions button').map(button => [button.attributes('aria-label'), button.find('svg text').text()])).toEqual([['Export PDF', 'PDF'], ['Export CSV', 'CSV']])
    await wrapper.find('.export-actions button[aria-label="Export CSV"]').trigger('click')
    expect(click).toHaveBeenCalledTimes(1)
    const csv = await blobs[0].text()
    expect(csv).toContain('r1,Rejected')
    expect(csv).toContain("'=1+1")
    expect(csv).not.toContain('a1')

    await wrapper.find('select[aria-label="Shift"]').setValue('old')
    await flushPromises()
    expect(fetch).toHaveBeenCalledWith('/api/inspection/scans?limit=5000&session=old', expect.anything())
    expect(wrapper.find('h2').text()).toBe('Oct 27, 02:48 – 13:30')
    click.mockRestore()
  })

  it('History pages long lists and says why a list is empty', async () => {
    const many = Array.from({ length: 120 }, (_, index) => scan(`s${index}`, 'Class A'))
    mockFetch({ '/api/inspection/scans': { items: many }, '/api/sessions': { items: SHIFTS } })
    const wrapper = mount(HistoryView, { props: { scope: 'all' } })
    await flushPromises()
    expect(wrapper.findAll('tbody tr')).toHaveLength(50)
    expect(wrapper.find('.result-count').text()).toBe('Showing 1–50 · 120 scans')
    const next = () => wrapper.findAll('.pager button').find(button => button.text() === 'Next')
    await next().trigger('click')
    await next().trigger('click')
    expect(wrapper.find('.result-count').text()).toBe('Showing 101–120 · 120 scans')
    expect(next().attributes('disabled')).toBeDefined()

    await wrapper.find('input[type="search"]').setValue('no such scan')
    expect(wrapper.find('td.empty').text()).toBe('No scans match the search and grade filter.')
    expect(wrapper.find('.pager').exists()).toBe(false)
    await wrapper.findAll('.result-bar button').find(button => button.text() === 'Clear filters').trigger('click')
    expect(wrapper.findAll('tbody tr')).toHaveLength(50)
    expect(wrapper.find('.result-count').text()).toBe('Showing 1–50 · 120 scans')

    mockFetch({ '/api/inspection/scans': { items: [] }, '/api/sessions': { items: SHIFTS } })
    const empty = mount(HistoryView)
    await flushPromises()
    expect(empty.find('td.empty').text()).toBe('No scans in the current shift yet. Choose All shifts to see earlier scans.')
    expect(empty.findAll('.export-actions button').every(button => button.attributes('disabled') !== undefined)).toBe(true)
  })

  it('History voids a narrowed list in one go, never all history unfiltered', async () => {
    const items = [scan('a1', 'Class A'), scan('a2', 'Class B'), scan('v1', 'Rejected', { voided_at: '2026-10-27T06:40:00Z', void_reason: 'Test run' })]
    mockFetch({ '/api/inspection/scans': { items }, '/api/sessions': { items: SHIFTS } })
    const all = mount(HistoryView, { props: { scope: 'all' } })
    await flushPromises()
    expect(all.find('.result-count').text()).toBe('3 scans · 1 voided')
    expect(all.find('.batch-action').exists()).toBe(false)

    const shift = mount(HistoryView, { props: { scope: 'old' } })
    await flushPromises()
    expect(shift.find('button.batch-action').text()).toBe('Void 2 scans…')
    expect(shift.find('.batch-action').attributes('title')).toBe('Void all 2 scans in this list, on every page')
    await shift.find('.batch-action').trigger('click')
    expect(shift.emitted('void')[0][0]).toEqual({ scans: [items[0], items[1]], restore: false })
    await shift.find('select[aria-label="Filter by grade"]').setValue('Class A')
    expect(shift.findAll('tbody tr')).toHaveLength(1)
    await shift.find('select[aria-label="Filter by grade"]').setValue('Voided')
    expect(shift.find('.result-count').text()).toBe('1 of 3 scans match')
  })

  it('System Status no longer offers to delete scans', async () => {
    mockFetch({})
    const wrapper = mount(SystemStatusView, { global: { stubs: { CameraCard: true } } })
    await flushPromises()
    expect(wrapper.text()).not.toContain('Clear all scans')
    wrapper.unmount()
  })

  it('Dashboard reports an unreachable API instead of showing totals', async () => {
    mockFetch({})
    const wrapper = mount(DashboardView)
    await flushPromises()
    expect(wrapper.emitted('error')[0][0]).toBe('Dashboard data unavailable: Service unavailable')
  })

  it('History reports a failed load and disables both exports', async () => {
    mockFetch({})
    const wrapper = mount(HistoryView)
    await flushPromises()
    expect(wrapper.emitted('error')[0][0]).toBe('Scan history unavailable: Service unavailable')
    expect(wrapper.find('.result-count').text()).toBe('0 scans')
    expect(wrapper.findAll('.export-actions button').map(button => button.attributes('disabled'))).toEqual(['', ''])
  })

  it('System Status reports a failed load and clears every card', async () => {
    mockFetch({})
    const wrapper = mount(SystemStatusView, { global: { stubs: { CameraCard: true } } })
    await flushPromises()
    expect(wrapper.emitted('error')[0][0]).toBe('System status unavailable: Service unavailable')
    expect(wrapper.text()).toContain('Drift indicators unavailable.')
    wrapper.unmount()
  })
})
