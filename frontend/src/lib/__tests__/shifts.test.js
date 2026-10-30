import { describe, expect, it } from 'vitest'
import { formatPercent } from '../grades.js'
import { pastShifts, plural, scopeDescription, scopeQuery, scopeTitle, shiftDate, shiftDuration, shiftOptionLabel, shiftTitle } from '../shifts.js'
import { bucketLabel, intervalName, isIsolated, tickLabels, tickStep, timeTicks, trendBounds, trendPoints } from '../trend.js'
import { scansCsv } from '../csv.js'

// Times are UTC in the API and shown in Manila time (UTC+8), as on the Pi.
const MORNING = { id: 'm', status: 'closed', notes: 'Shift opened automatically at startup', name: null, started_at: '2026-10-26T18:48:29+00:00', ended_at: '2026-10-27T05:30:11+00:00', scan_count: 97 }
const NIGHT = { id: 'n', status: 'closed', notes: 'Shift started from dashboard', name: 'Toril batch', started_at: '2026-10-26T10:00:00+00:00', ended_at: '2026-10-26T18:30:00+00:00', scan_count: 1 }
const NOW = { id: 'c', status: 'open', notes: 'Shift opened after clearing scans', name: null, started_at: '2026-10-27T05:46:08+00:00', ended_at: null, scan_count: 0 }
const EMPTY = { id: 'e', status: 'closed', notes: 'Shift opened automatically at startup', name: null, started_at: '2026-10-26T18:32:11+00:00', ended_at: '2026-10-26T18:48:29+00:00', scan_count: 0 }

describe('shift labels', () => {
  it('names a shift by its day in Manila, never by how it was opened', () => {
    expect(shiftDate(MORNING)).toBe('Tue, Oct 27, 2026')  // 02:48 on Oct 27 in Manila, though Oct 26 in UTC
    expect(shiftDate(NIGHT)).toBe('Mon, Oct 26, 2026')
    expect(shiftTitle(MORNING)).toBe('Tue, Oct 27, 2026')
    expect(shiftTitle(NIGHT)).toBe('Toril batch')
    expect(shiftOptionLabel(MORNING)).toBe('Tue, Oct 27, 2026 · 97 scans')
    expect(shiftOptionLabel(NIGHT)).toBe('Toril batch · Mon, Oct 26, 2026 · 1 scan')
  })

  it('gives durations in hours and days', () => {
    expect(shiftDuration(MORNING)).toBe('10 h 42 min')
    expect(shiftDuration({ started_at: '2026-10-20T04:58:24Z', ended_at: '2026-10-26T16:45:28Z' })).toBe('6 d 11 h')
    expect(shiftDuration(NOW, Date.parse('2026-10-27T06:00:00Z'))).toBe('14 min')
  })

  it('lists only past shifts that hold scans', () => {
    expect(pastShifts([NOW, MORNING, EMPTY, NIGHT]).map(shift => shift.id)).toEqual(['m', 'n'])
    const voidedRun = { ...EMPTY, id: 'v', voided_count: 12 }
    expect(pastShifts([voidedRun]).map(shift => shift.id)).toEqual(['v'])  // still reachable, to count them again
    expect(shiftOptionLabel(voidedRun)).toBe('Tue, Oct 27, 2026 · 0 scans · 12 voided')
  })

  it('describes the scope for headings, exports and the API', () => {
    const shifts = [NOW, MORNING]
    expect(scopeTitle('active', shifts)).toBe('Current shift')
    expect(scopeTitle('m', shifts)).toBe('Tue, Oct 27, 2026')
    expect(scopeDescription('active', shifts)).toBe('Current shift · Tue, Oct 27, 2026 · 0 scans')
    expect(scopeDescription('all', shifts)).toBe('All shifts')
    expect(scopeQuery('all')).toBe('')
    expect(scopeQuery('active')).toBe('session=active')
    expect(plural(1, 'scan')).toBe('1 scan')
    expect(plural(1234, 'scan')).toBe('1,234 scans')
  })

  it('rounds rates to one decimal', () => {
    expect(formatPercent(25.81)).toBe('25.8%')
    expect(formatPercent(74.19)).toBe('74.2%')
    expect(formatPercent(0)).toBe('0%')
    expect(formatPercent(100)).toBe('100%')
    expect(formatPercent(null)).toBe('—')
  })
})

describe('rejection trend on a clock', () => {
  const bucket = (time, total, rejected) => ({ bucket_start: time, total, rejected, rejection_rate: Math.round((rejected / total) * 10000) / 100 })
  // The 27 Oct run: steady until 04:45, nothing graded at 03:45, then one bucket after lunch at 13:15 (UTC+8).
  const items = [
    bucket('2026-10-26T19:15:00+00:00', 8, 7),
    bucket('2026-10-26T19:30:00+00:00', 5, 0),
    bucket('2026-10-26T20:00:00+00:00', 4, 1),
    bucket('2026-10-27T05:15:00+00:00', 2, 0)
  ]

  it('breaks the line where an interval had nothing graded', () => {
    const points = trendPoints(items, 15)
    expect(points.map(point => point.y)).toEqual([87.5, 0, null, 25, null, 0])
    expect(new Date(points[2].x).toISOString()).toBe('2026-10-26T19:45:00.000Z')
    expect(isIsolated(points, 3)).toBe(true)
    expect(isIsolated(points, 0)).toBe(false)
    expect(isIsolated(points, 5)).toBe(true)
  })

  it('puts ticks on round local times across the real gap', () => {
    const { min, max } = trendBounds(trendPoints(items, 15), 15)
    expect(tickStep(min, max)).toBe(2 * 60 * 60_000)
    const ticks = timeTicks(min, max)
    expect(tickLabels(ticks, tickStep(min, max), false)).toEqual(['04:00', '06:00', '08:00', '10:00', '12:00'])
  })

  it('aligns a day step to local midnight and dates the first tick of each day', () => {
    const min = Date.parse('2026-10-22T20:00:00Z')
    const max = Date.parse('2026-10-27T10:00:00Z')
    const ticks = timeTicks(min, max)
    expect(new Date(ticks[0]).toISOString()).toBe('2026-10-23T16:00:00.000Z')  // Oct 24, 00:00 in Manila
    expect(tickLabels(ticks, tickStep(min, max), true)).toEqual(['Oct 24', 'Oct 25', 'Oct 26', 'Oct 27'])

    const hours = [Date.parse('2026-10-26T14:00:00Z'), Date.parse('2026-10-26T16:00:00Z'), Date.parse('2026-10-26T18:00:00Z')]
    expect(tickLabels(hours, 2 * 60 * 60_000, true)).toEqual([['22:00', 'Oct 26'], ['00:00', 'Oct 27'], '02:00'])
  })

  it('labels buckets and intervals in words', () => {
    expect(bucketLabel(Date.parse('2026-10-26T19:30:00Z'), 15)).toBe('Oct 27, 03:30–03:45')
    expect(bucketLabel(Date.parse('2026-10-26T16:00:00Z'), 1440)).toBe('Tue, Oct 27')
    expect([5, 15, 60, 1440].map(intervalName)).toEqual(['5 minutes', '15 minutes', 'hour', 'day'])
  })
})

describe('CSV export', () => {
  it('quotes and defuses what a spreadsheet would misread', () => {
    const csv = scansCsv([
      { scan_id: 'a', final_grade: 'Class A', stage1_confidence: 0.97, dispute_reason: 'Bruise, "soft" spot\nnear the crown' },
      { scan_id: 'b', final_grade: null, stage1_confidence: -0.5, dispute_reason: '=HYPERLINK("x")' }
    ])
    expect(csv.split('\r\n')[0]).toBe('scan_id,final_grade,stage1_confidence,dispute_reason')
    expect(csv).toContain('a,Class A,0.97,"Bruise, ""soft"" spot\nnear the crown"')
    expect(csv).toContain(`b,,-0.5,"'=HYPERLINK(""x"")"`)
    expect(scansCsv([])).toBe('scan_id\r\n')
  })
})
