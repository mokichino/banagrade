import { describe, expect, it } from 'vitest'
import { confidencePercent, finalGradeKey, finalGradeLabel, formatConfidence, matchesGrade, matchesSearch, scanLabel, stage2Label } from '../grades.js'
import { LED_LEGEND, ledInfo } from '../led.js'

const healthyA = { scan_id: 'abcdef12-3456', stage1_status: 'Healthy', final_grade: 'Class A', captured_at: '2026-10-13T08:00:00+00:00' }
const rejected = { scan_id: 'ffff0000-1', stage1_status: 'Unhealthy', final_grade: 'Rejected' }
const failure = { scan_id: '99990000-1', stage1_status: 'Healthy', final_grade: null }

describe('grade presentation', () => {
  it('formats short scan IDs', () => {
    expect(scanLabel(healthyA.scan_id)).toBe('#SCN-ABCDEF')
  })
  it('never shows a technical failure as Rejected', () => {
    expect(finalGradeLabel(failure)).toBe('Technical failure')
    expect(finalGradeKey(failure)).toBe('t')
    expect(finalGradeKey(rejected)).toBe('r')
  })
  it('marks Stage 2 N/A when Stage 1 rejected the bunch', () => {
    expect(stage2Label(rejected)).toBe('N/A')
    expect(stage2Label(healthyA)).toBe('Class A')
    expect(stage2Label(failure)).toBe('N/A')
  })
  it('formats confidence safely', () => {
    expect(formatConfidence(0.9734)).toBe('97.3%')
    expect(formatConfidence(null)).toBe('N/A')
    expect(confidencePercent(1.4)).toBe(100)
  })
  it('filters by grade and search text', () => {
    expect(matchesGrade(healthyA, 'Class A')).toBe(true)
    expect(matchesGrade(failure, 'Rejected')).toBe(false)
    expect(matchesGrade(failure, 'All')).toBe(true)
    expect(matchesSearch(healthyA, '#scn-abc')).toBe(true)
    expect(matchesSearch(healthyA, '2026-10-13')).toBe(true)
    expect(matchesSearch(rejected, 'abcdef')).toBe(false)
  })
})

describe('LED mirror', () => {
  it('maps backend states to the thesis colours', () => {
    expect(ledInfo('ready').color).toBe('Green')
    expect(ledInfo('class_a').color).toBe('Yellow')
    expect(ledInfo('class_b').color).toBe('Blue')
    expect(ledInfo('booting').color).toBe('Slow red blink')
    expect(ledInfo('error').color).toBe('Fast red blink')
    expect(ledInfo('nonsense').tone).toBe('offline')
    expect(LED_LEGEND).toHaveLength(6)
  })
})

describe('LED signal board', async () => {
  const { lampPattern } = await import('../led.js')
  it('lights exactly the thesis lamp for each state', () => {
    expect(lampPattern('ready')).toEqual({ green: 'pulse', yellow: 'off', blue: 'off', red: 'off' })
    expect(lampPattern('class_a').yellow).toBe('flash')
    expect(lampPattern('class_b').blue).toBe('flash')
    expect(lampPattern('rejected').red).toBe('on')
    expect(lampPattern('booting').red).toBe('slow')
    expect(lampPattern('error').red).toBe('fast')
    expect(Object.values(lampPattern('offline')).every(v => v === 'off')).toBe(true)
  })
})
