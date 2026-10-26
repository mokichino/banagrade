// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ScanTable from '../ScanTable.vue'
import DisputeModal from '../DisputeModal.vue'
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

vi.mock('vue-chartjs', () => ({ Doughnut: { template: '<canvas />' }, Line: { template: '<canvas />' } }))

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
  it('lists earlier disputes and deletes one after confirming', async () => {
    let items = [
      { id: 'x2', reason: 'Rotting', corrected_grade: 'Rejected', original_grade: 'Class B', created_at: '2026-10-27T05:00:00Z' },
      { id: 'x1', reason: 'Middle finger 12.5 cm', corrected_grade: 'Class A', original_grade: 'Class B', created_at: '2026-10-27T04:00:00Z' }
    ]
    const fetch = vi.fn(async (url, options = {}) => {
      if (options.method === 'DELETE') {
        items = items.filter(item => !String(url).endsWith(`/${item.id}`))
        return { ok: true, status: 200, json: async () => ({ id: 'x2', final_grade: 'Class A', remaining_disputes: 1 }) }
      }
      return { ok: true, status: 200, json: async () => ({ items }) }
    })
    vi.stubGlobal('fetch', fetch)
    const wrapper = mount(DisputeModal, { props: { scan: null } })
    await wrapper.setProps({ scan: { scan_id: 's1', final_grade: 'Rejected', disputed: 1 } })
    await flushPromises()
    expect(wrapper.findAll('.dispute-history li')).toHaveLength(2)
    expect(wrapper.text()).toContain('Class B → Rejected')

    await wrapper.find('.dispute-history .delete-button').trigger('click')
    expect(wrapper.find('.dispute-confirm').text()).toContain('Delete this dispute?')
    expect(fetch).toHaveBeenCalledTimes(1)
    await wrapper.findAll('.dispute-confirm button').find(button => button.text() === 'Delete').trigger('click')
    await flushPromises()

    expect(fetch).toHaveBeenCalledWith('/api/inspection/scans/s1/disputes/x2', expect.objectContaining({ method: 'DELETE' }))
    expect(wrapper.findAll('.dispute-history li')).toHaveLength(1)
    expect(wrapper.text()).toContain('Recorded: Class A')
    expect(wrapper.emitted('changed')).toHaveLength(1)
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
      '/api/sessions/active': { session: null },
      '/api/inspection/scans': { items: [] }
    })
    const wrapper = mount(DashboardView)
    await flushPromises()
    expect(wrapper.text()).toContain('No accepted bunches yet.')
    expect(wrapper.text()).toContain('No graded scans in this period yet.')
    expect(wrapper.emitted('error')).toBeUndefined()
  })

  it('Dashboard reports an unreachable API instead of showing totals', async () => {
    mockFetch({})
    const wrapper = mount(DashboardView)
    await flushPromises()
    expect(wrapper.emitted('error')[0][0]).toBe('Dashboard data unavailable: Service unavailable')
  })

  it('History reports a failed load and disables the PDF export', async () => {
    mockFetch({})
    const wrapper = mount(HistoryView)
    await flushPromises()
    expect(wrapper.emitted('error')[0][0]).toBe('Scan history unavailable: Service unavailable')
    expect(wrapper.find('.result-count').text()).toBe('0 of 0 records')
    expect(wrapper.find('button.primary-button').attributes('disabled')).toBeDefined()
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
