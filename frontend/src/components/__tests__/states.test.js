// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ScanTable from '../ScanTable.vue'
import ModelsCard from '../status/ModelsCard.vue'
import OperationalSummaryCard from '../status/OperationalSummaryCard.vue'
import HardwareStatusCard from '../status/HardwareStatusCard.vue'
import DriftCard from '../status/DriftCard.vue'
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
})

describe('status cards with no data', () => {
  it('ModelsCard shows the load error and Missing badges', () => {
    const models = { available: false, error: 'Model file not found: stage1_best.pt', models: [{ key: 'stage1', label: 'stage1_best.pt', architecture: 'YOLO11n-cls', task: 'Health', path: '/m/stage1_best.pt', state: 'missing' }] }
    const wrapper = mount(ModelsCard, { props: { models } })
    expect(wrapper.find('.alert').text()).toContain('Model file not found')
    expect(wrapper.find('.status-badge').text()).toBe('Missing')
    expect(wrapper.text()).toContain('Raw RGB, whole frame resized to 224 × 224')
    expect(wrapper.text()).toContain('then the COCO YOLO11n banana class')
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
