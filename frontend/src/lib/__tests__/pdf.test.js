import { expect, it } from 'vitest'
import { buildScansPdf, pdfFilename } from '../pdf.js'

it('builds a one-page audit PDF from filtered scans', () => {
  const scans = [
    { scan_id: 'abc', captured_at: '2026-10-13T08:00:00Z', stage1_status: 'Healthy', stage1_confidence: 0.9, final_grade: 'Class A' },
    { scan_id: 'def', captured_at: '2026-10-13T08:05:00Z', stage1_status: 'Unhealthy', stage1_confidence: 0.95, final_grade: 'Rejected', rejection_reason: 'SURFACE_UNHEALTHY' }
  ]
  const doc = buildScansPdf(scans, { filter: 'All' })
  expect(doc.getNumberOfPages()).toBe(1)
  expect(doc.output('arraybuffer').byteLength).toBeGreaterThan(1000)
  expect(pdfFilename(new Date('2026-10-13T00:00:00Z'))).toBe('banagrade-scans-2026-10-13.pdf')
})
