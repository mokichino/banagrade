// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ScanDrawer from '../ScanDrawer.vue'

const scan = (extra = {}) => ({
  scan_id: 'abcdef12-0000-4000-8000-000000000001',
  captured_at: '2026-11-09T05:30:00+00:00',
  final_grade: 'Class B',
  stage1_status: 'Healthy',
  image_refs: '["/var/lib/banagrade/frames/abcdef12.jpg"]',
  bbox_coords: '[400,200,2800,2200]',
  pixel_length: 2400,
  ...extra
})

// jsdom loads no images, so a test fires load/error itself, with the size a quarter-scale preview would have.
function loadImage(img, width = 1152, height = 648) {
  Object.defineProperty(img.element, 'naturalWidth', { value: width, configurable: true })
  Object.defineProperty(img.element, 'naturalHeight', { value: height, configurable: true })
  return img.trigger('load')
}

let wrapper
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
  vi.useRealTimers()
})

function mountDrawer(props) {
  const app = document.createElement('div')
  app.id = 'app'
  document.body.appendChild(app)
  wrapper = mount(ScanDrawer, { props, attachTo: app })
  return wrapper
}

describe('ScanDrawer photo', () => {
  it('shows the preview with the measured box scaled onto it', async () => {
    mountDrawer({ scan: scan() })
    const img = wrapper.get('.photo-open img')
    expect(img.attributes('src')).toBe('/api/inspection/scans/abcdef12-0000-4000-8000-000000000001/photo')
    expect(img.attributes('alt')).toContain('outlined')
    expect(wrapper.text()).toContain('Loading photo')
    expect(wrapper.get('.photo-open').attributes('disabled')).toBeDefined()

    await loadImage(img)
    expect(wrapper.text()).not.toContain('Loading photo')
    expect(wrapper.get('.photo-open').attributes('disabled')).toBeUndefined()
    // The overlay is in full-frame pixels over a quarter-size image, so the box sits at 400/4608 of the width.
    expect(wrapper.get('.photo-box').attributes('viewBox')).toBe('0 0 4608 2592')
    const rect = wrapper.get('.photo-box-line')
    expect([rect.attributes('x'), rect.attributes('y'), rect.attributes('width'), rect.attributes('height')]).toEqual(['400', '200', '2400', '2000'])
    expect(wrapper.get('.photo-frame').attributes('style')).toContain('1152 / 648')

    const toggle = wrapper.get('.photo-toggle')
    expect(toggle.attributes('aria-pressed')).toBe('true')
    await toggle.trigger('click')
    expect(wrapper.find('.photo-box').exists()).toBe(false)
    expect(toggle.attributes('aria-pressed')).toBe('false')
  })

  it('explains a scan that never had a photo', () => {
    mountDrawer({ scan: scan({ image_refs: null, bbox_coords: null }) })
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toContain('No photo was saved for this scan.')
  })

  it('retries a photo that is not written yet, then explains a pruned one', async () => {
    vi.useFakeTimers()
    mountDrawer({ scan: scan() })
    for (let attempt = 1; attempt <= 2; attempt += 1) {
      await wrapper.get('.photo-open img').trigger('error')
      vi.advanceTimersByTime(1500)
      await wrapper.vm.$nextTick()
      expect(wrapper.get('.photo-open img').attributes('src')).toMatch(new RegExp(`\\?attempt=${attempt}$`))
    }
    await wrapper.get('.photo-open img').trigger('error')
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toContain('Photo no longer available.')
    expect(wrapper.text()).toContain('latest 1,000 photos')
  })

  it('has no box or outline toggle for a scan Stage 2 did not measure', async () => {
    mountDrawer({ scan: scan({ final_grade: 'Rejected', bbox_coords: null }) })
    await loadImage(wrapper.get('.photo-open img'))
    expect(wrapper.find('.photo-box').exists()).toBe(false)
    expect(wrapper.find('.photo-toggle').exists()).toBe(false)
  })
})

describe('ScanDrawer full-screen viewer', () => {
  it('opens over an inert page, swaps in the full frame, and Escape closes only the viewer', async () => {
    const images = []
    vi.stubGlobal('Image', class { constructor() { images.push(this) } })
    mountDrawer({ scan: scan() })
    await loadImage(wrapper.get('.photo-open img'))
    await wrapper.get('.photo-open').trigger('click')
    await wrapper.vm.$nextTick()

    const viewer = document.querySelector('.photo-viewer')
    expect(viewer).not.toBeNull()
    expect(viewer.getAttribute('aria-modal')).toBe('true')
    expect(document.getElementById('app').inert).toBe(true)
    expect(document.activeElement?.getAttribute('aria-label')).toBe('Close photo')
    expect(viewer.querySelector('img').getAttribute('src')).toBe('/api/inspection/scans/abcdef12-0000-4000-8000-000000000001/photo')
    expect(viewer.textContent).toContain('loading full resolution')

    expect(images[0].src).toBe('/api/inspection/scans/abcdef12-0000-4000-8000-000000000001/photo?size=full')
    const viewerImg = viewer.querySelector('img')
    Object.defineProperty(viewerImg, 'naturalWidth', { value: 1152, configurable: true })
    Object.defineProperty(viewerImg, 'naturalHeight', { value: 648, configurable: true })
    viewerImg.dispatchEvent(new Event('load'))
    await wrapper.vm.$nextTick()
    images[0].onload()
    await wrapper.vm.$nextTick()
    expect(viewerImg.getAttribute('src')).toContain('?size=full')
    // Until the full frame reports its size, the overlay keeps the preview's mapping: same full-frame viewBox.
    expect(viewer.querySelector('.photo-box').getAttribute('viewBox')).toBe('0 0 4608 2592')
    Object.defineProperty(viewerImg, 'naturalWidth', { value: 4608, configurable: true })
    Object.defineProperty(viewerImg, 'naturalHeight', { value: 2592, configurable: true })
    viewerImg.dispatchEvent(new Event('load'))
    await wrapper.vm.$nextTick()
    expect(viewer.querySelector('.photo-box').getAttribute('viewBox')).toBe('0 0 4608 2592')
    expect(viewer.textContent).not.toContain('loading full resolution')

    viewer.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(document.querySelector('.photo-viewer')).toBeNull()
    expect(document.getElementById('app').inert).toBe(false)
    expect(wrapper.emitted('close')).toBeUndefined()
    vi.unstubAllGlobals()
  })
})

describe('ScanDrawer details', () => {
  it('shows the grade, both stages and the width against the Class A minimum', () => {
    mountDrawer({ scan: scan({ stage1_confidence: 0.981, stage2_confidence: 0.934, inference_time_ms: 812.4 }) })
    expect(wrapper.get('.grade-summary').classes()).toContain('b')
    expect(wrapper.get('.grade-summary strong').text()).toBe('Class B')
    const stages = wrapper.findAll('.stage-card')
    expect(stages.map(stage => stage.get('strong').text())).toEqual(['Healthy', 'Class B'])
    expect(stages.map(stage => stage.get('small').text())).toEqual(['98.1% confidence', '93.4% confidence'])
    const facts = wrapper.findAll('.fact-list dd').map(dd => dd.text())
    expect(facts[0]).toContain('2,400.0 px')
    expect(facts[0]).toContain('330.1 px under the Class A minimum')
    expect(facts.slice(1)).toEqual(['2,730.07 px', '812 ms'])
  })

  it('explains a rejected, voided scan without a Stage 2 grade', () => {
    mountDrawer({ scan: scan({ final_grade: 'Rejected', stage1_status: 'Unhealthy', rejection_reason: 'SURFACE_UNHEALTHY', pixel_length: null, bbox_coords: null, voided_at: '2026-11-09T06:00:00+00:00', void_reason: 'Test run', shift_closed: 1 }) })
    expect(wrapper.get('.grade-summary').text()).toContain('Unhealthy at Stage 1')
    expect(wrapper.findAll('.stage-card')[1].text()).toContain('Runs on healthy bunches only')
    expect(wrapper.get('.scan-note').text()).toContain('Test run')
    expect(wrapper.find('.voided-badge').exists()).toBe(true)
    expect(wrapper.find('.read-only-badge').exists()).toBe(true)
    expect(wrapper.findAll('.fact-list dd')[0].text()).toBe('Not measured')
  })
})

describe('ScanDrawer keyboard', () => {
  it('moves focus to Close on open and closes on Escape', async () => {
    mountDrawer({ scan: null })
    await wrapper.setProps({ scan: scan() })
    await wrapper.vm.$nextTick()
    expect(document.activeElement?.getAttribute('aria-label')).toBe('Close scan detail')
    await wrapper.get('.modal-backdrop').trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
