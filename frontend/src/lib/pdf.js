import { jsPDF } from 'jspdf'
import autoTable from 'jspdf-autotable'
import { WIDTH_THRESHOLD_PX, finalGradeLabel, formatConfidence, formatTimestamp, scanLabel, stage1Label, stage2Label } from './grades.js'

const FILLS = { 'Class A': [255, 241, 196], 'Class B': [219, 234, 254], Rejected: [254, 226, 226] }

export function buildScansPdf(scans, { filter = 'All', search = '', generated = new Date() } = {}) {
  const doc = new jsPDF({ orientation: 'landscape', unit: 'pt', format: 'a4' })
  doc.setFontSize(15)
  doc.text('Banagrade AI Sorting System — Scan Audit Log', 40, 44)
  doc.setFontSize(9)
  doc.setTextColor(90)
  doc.text(`Generated ${formatTimestamp(generated.toISOString())} · ${scans.length} records · Filter: ${filter}${search ? ` · Search: "${search}"` : ''}`, 40, 62)
  doc.text(`Stage 1: stage1_best.pt (YOLO11n-cls) · Stage 2: stage2_best.pt (YOLO11n) · Class A when bbox width ≥ ${WIDTH_THRESHOLD_PX} px (4608×2592 frame)`, 40, 76)
  autoTable(doc, {
    startY: 90,
    head: [['Scan ID', 'Timestamp', 'Stage 1 screening', 'Stage 2 grading', 'Stage 1 confidence', 'Stage 2 confidence', 'Final grade', 'Reason']],
    body: scans.map(scan => [
      scanLabel(scan.scan_id),
      formatTimestamp(scan.captured_at),
      stage1Label(scan),
      stage2Label(scan),
      formatConfidence(scan.stage1_confidence),
      formatConfidence(scan.stage2_confidence),
      finalGradeLabel(scan),
      scan.rejection_reason || ''
    ]),
    styles: { fontSize: 8, cellPadding: 4 },
    headStyles: { fillColor: [17, 24, 39] },
    didParseCell: data => {
      if (data.section === 'body' && data.column.index === 6) {
        const fill = FILLS[data.cell.raw]
        if (fill) data.cell.styles.fillColor = fill
      }
    }
  })
  return doc
}

export function pdfFilename(date = new Date()) {
  return `banagrade-scans-${date.toISOString().slice(0, 10)}.pdf`
}

export function downloadScansPdf(scans, options = {}) {
  const generated = new Date()
  buildScansPdf(scans, { ...options, generated }).save(pdfFilename(generated))
}
