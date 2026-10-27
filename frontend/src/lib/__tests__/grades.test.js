import { describe, expect, it } from 'vitest'
import { confidencePercent, disputeSummary, finalGradeKey, finalGradeLabel, formatConfidence, matchesGrade, matchesSearch, scanLabel, stage2Label } from '../grades.js'
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
  it('keeps the Stage 2 result when an operator corrects the final grade', () => {
    expect(stage2Label({ ...healthyA, final_grade: 'Rejected', disputed: 1, model_grade: 'Class A' })).toBe('Class A')
    expect(stage2Label({ ...healthyA, final_grade: 'Class A', disputed: 1, model_grade: 'Class B' })).toBe('Class B')
    expect(stage2Label({ ...healthyA, final_grade: 'Class A', disputed: 1, model_grade: 'Technical Failure' })).toBe('N/A')
    expect(stage2Label({ ...healthyA, final_grade: 'Class B', disputed: 1, model_grade: null })).toBe('Class B')  // too old to know
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
    expect(matchesGrade(failure, 'Technical failure')).toBe(true)
    expect(matchesGrade(rejected, 'Technical failure')).toBe(false)
    expect(matchesGrade({ ...healthyA, disputed: 1 }, 'Disputed')).toBe(true)
    expect(matchesGrade(healthyA, 'Disputed')).toBe(false)
  })
  it('summarises a dispute for the table badge', () => {
    expect(disputeSummary(healthyA)).toBe('')
    expect(disputeSummary({ ...healthyA, disputed: 1, model_grade: 'Class B', dispute_reason: 'Middle finger 12.0 cm' })).toBe('Model graded Class B · Middle finger 12.0 cm')
    expect(disputeSummary({ ...rejected, disputed: 1, model_grade: 'Technical Failure', dispute_reason: null })).toBe('Model graded Technical failure')
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
    expect(ledInfo('check')).toMatchObject({ color: 'Fast red blink', label: 'Check by hand' })  // same lamp, not a fault
    expect(LED_LEGEND).toHaveLength(7)
  })
})

describe('LED signal board', async () => {
  const { lampPattern } = await import('../led.js')
  it('lights exactly the thesis lamp for each state', () => {
    expect(lampPattern('ready')).toEqual({ green: 'on', yellow: 'off', blue: 'off', red: 'off' })
    expect(lampPattern('class_a').yellow).toBe('on')
    expect(lampPattern('class_b').blue).toBe('on')
    expect(lampPattern('rejected').red).toBe('on')
    expect(lampPattern('booting').red).toBe('slow')
    expect(lampPattern('error').red).toBe('fast')
    expect(Object.values(lampPattern('offline')).every(v => v === 'off')).toBe(true)
  })
})

describe('failure reasons', async () => {
  const { failureReason } = await import('../grades.js')

  it('says why a scan was not graded', () => {
    expect(failureReason({ final_grade: null, rejection_reason: 'LOW_CONFIDENCE', stage1_status: 'Unhealthy', stage1_confidence: 0.65, error_details: 'Stage 1 confidence 0.65 is below 0.80' }))
      .toBe('Unsure: Unhealthy 65% (needs 80%) · check by hand')
    expect(failureReason({ final_grade: null, rejection_reason: 'DETECTION_FAILED', stage2_confidence: 0.874, error_details: 'Stage 2 confidence 0.87 is below 0.90' }))
      .toBe('Not measured: outline 87% (needs 90%) · check by hand')
    expect(failureReason({ final_grade: null, rejection_reason: 'DETECTION_FAILED', stage2_confidence: null })).toBe('Not measured: no outline found · check by hand')
    expect(failureReason({ final_grade: null, rejection_reason: 'NOT_A_BUNCH' })).toBe('Not a bunch: no banana colour')
    expect(failureReason({ final_grade: 'Rejected', rejection_reason: 'SURFACE_UNHEALTHY' })).toBe('Unhealthy at Stage 1')
    expect(failureReason({ final_grade: 'Class A' })).toBe('')
  })
})
