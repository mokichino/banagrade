import { jsPDF } from 'jspdf'
import autoTable from 'jspdf-autotable'
import { failureReason, finalGradeLabel, formatConfidence, formatTimestamp, isHealthy, isTechnicalFailure, isVoided, scanLabel, stage1Label, stage2Label } from './grades.js'

// Brand palette, mirroring style.css and public/logo.svg.
const INK = [17, 24, 39]
const SECONDARY = [75, 85, 99]
const MUTED = [107, 114, 128]
const BORDER = [229, 231, 235]
const SUBTLE = [249, 250, 251]
const BANANA = [245, 197, 24]
const HEALTHY = [22, 163, 74]
const MARGIN = 40

// Grade pills follow the floor LEDs: yellow = Class A, blue = Class B, red = Rejected.
const TONES = {
  'Class A': { soft: [255, 248, 225], line: [217, 163, 0], ink: [138, 90, 0] },
  'Class B': { soft: [239, 246, 255], line: [37, 99, 235], ink: [29, 78, 216] },
  Rejected: { soft: [254, 242, 242], line: [220, 38, 38], ink: [185, 28, 28] },
  'Technical failure': { soft: [243, 244, 246], line: [156, 163, 175], ink: SECONDARY }
}
const VOIDED_TONE = { soft: [243, 244, 246], line: BORDER, ink: MUTED }

/** public/logo.svg redrawn as vectors: a 64-unit square scaled to `size` points. */
function drawLogo(doc, x, y, size) {
  const s = size / 64
  const at = (px, py) => [x + px * s, y + py * s]
  // The banana group is translate(-3.5 -2.5) rotate(-32 32 33).
  const cos = Math.cos(-32 * Math.PI / 180)
  const sin = Math.sin(-32 * Math.PI / 180)
  const turned = (px, py) => at(32 + (px - 32) * cos - (py - 33) * sin - 3.5, 33 + (px - 32) * sin + (py - 33) * cos - 2.5)
  const trace = (map, [start, ...segments]) => {
    doc.moveTo(...map(...start))
    for (const seg of segments) {
      if (seg.length === 2) doc.lineTo(...map(...seg))
      else doc.curveTo(...map(seg[0], seg[1]), ...map(seg[2], seg[3]), ...map(seg[4], seg[5]))
    }
  }

  doc.setFillColor(...INK)
  doc.roundedRect(x, y, size, size, 14 * s, 14 * s, 'F')
  doc.setDrawColor(...BANANA)
  doc.setFillColor(...BANANA)
  doc.setLineCap('round')
  doc.setLineJoin('round')
  doc.setLineWidth(4 * s)
  for (const corner of [
    [[10, 20], [10, 12], [10, 10.9, 10.9, 10, 12, 10], [20, 10]],
    [[44, 10], [52, 10], [53.1, 10, 54, 10.9, 54, 12], [54, 20]],
    [[54, 44], [54, 52], [54, 53.1, 53.1, 54, 52, 54], [44, 54]],
    [[20, 54], [12, 54], [10.9, 54, 10, 53.1, 10, 52], [10, 44]]
  ]) {
    trace(at, corner)
    doc.stroke()
  }
  doc.setLineWidth(2.2 * s)
  trace(turned, [[14, 29], [17.5, 44, 45, 47, 50.5, 31.5], [42, 31], [22, 31]])
  doc.close()
  doc.fillStroke()
  trace(turned, [[47.6, 31.4], [49.8, 24.6], [50.5, 22.6, 53.5, 23.6, 52.8, 25.6], [51, 32]])
  doc.close()
  doc.fill()
  doc.setDrawColor(...INK)
  doc.setLineWidth(1.5 * s)
  trace(turned, [[18.5, 32.8], [24.5, 38.4, 38, 39.8, 45.8, 34.6]])
  doc.stroke()
  doc.setLineCap('butt')
  doc.setLineJoin('miter')
}

function drawHeader(doc, generated) {
  const width = doc.internal.pageSize.getWidth()
  drawLogo(doc, MARGIN, 22, 30)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(15)
  doc.setTextColor(...INK)
  doc.text('Banagrade', MARGIN + 40, 36)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(6.5)
  doc.setTextColor(...MUTED)
  doc.text('AI SORTING SYSTEM', MARGIN + 40, 47, { charSpace: 1.2 })
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(13)
  doc.setTextColor(...INK)
  doc.text('Scan Audit Log', width - MARGIN, 36, { align: 'right' })
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.setTextColor(...MUTED)
  doc.text(`Generated ${formatTimestamp(generated.toISOString())}`, width - MARGIN, 47, { align: 'right' })
  doc.setFillColor(...BANANA)
  doc.rect(MARGIN, 62, width - MARGIN * 2, 2, 'F')
}

function drawFooter(doc, page, pages) {
  const width = doc.internal.pageSize.getWidth()
  const height = doc.internal.pageSize.getHeight()
  doc.setDrawColor(...BORDER)
  doc.setLineWidth(0.5)
  doc.line(MARGIN, height - 34, width - MARGIN, height - 34)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(...MUTED)
  doc.text('Banagrade AI Sorting System · Scan Audit Log', MARGIN, height - 22)
  doc.text(`Page ${page} of ${pages}`, width - MARGIN, height - 22, { align: 'right' })
}

/** Record count plus a tile per outcome; voided scans count nowhere, so grade shares are of the rest. */
function drawSummary(doc, scans, y) {
  const counted = scans.filter(scan => !isVoided(scan))
  const voided = scans.length - counted.length
  const tiles = [
    { label: 'RECORDS', value: scans.length, tone: { soft: SUBTLE, line: INK, ink: INK } },
    ...Object.entries(TONES).map(([grade, tone]) => ({ label: grade.toUpperCase(), value: counted.filter(scan => finalGradeLabel(scan) === grade).length, tone, share: true })),
    ...(voided ? [{ label: 'VOIDED', value: voided, tone: { ...VOIDED_TONE, line: MUTED } }] : [])
  ]
  const gap = 8
  const width = (doc.internal.pageSize.getWidth() - MARGIN * 2 - gap * (tiles.length - 1)) / tiles.length
  tiles.forEach(({ label, value, tone, share }, index) => {
    const x = MARGIN + index * (width + gap)
    doc.setFillColor(...tone.soft)
    doc.setDrawColor(...BORDER)
    doc.setLineWidth(0.5)
    doc.roundedRect(x, y, width, 40, 4, 4, 'FD')
    doc.setFillColor(...tone.line)
    doc.rect(x, y + 6, 2.5, 28, 'F')
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(6.5)
    doc.setTextColor(...MUTED)
    doc.text(label, x + 11, y + 14, { charSpace: 0.6 })
    doc.setFontSize(15)
    doc.setTextColor(...tone.ink)
    doc.text(String(value), x + 11, y + 32)
    if (share && counted.length) {
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(8)
      doc.setTextColor(...MUTED)
      doc.text(`${Math.round(value / counted.length * 100)}%`, x + width - 10, y + 32, { align: 'right' })
    }
  })
}

export function buildScansPdf(scans, { filter = 'All', search = '', shift = 'All shifts', generated = new Date() } = {}) {
  const doc = new jsPDF({ orientation: 'landscape', unit: 'pt', format: 'a4' })
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(...SECONDARY)
  doc.text(`Shift: ${shift}  ·  Filter: ${filter}${search ? `  ·  Search: "${search}"` : ''}`, MARGIN, 86)
  drawSummary(doc, scans, 96)

  autoTable(doc, {
    startY: 152,
    margin: { top: 80, right: MARGIN, bottom: 48, left: MARGIN },
    theme: 'plain',
    head: [['Scan ID', 'Timestamp', 'Stage 1 screening', 'Stage 2 grading', 'Stage 1 confidence', 'Stage 2 confidence', 'Final grade', 'Reason']],
    body: scans.map(scan => [
      scanLabel(scan.scan_id),
      formatTimestamp(scan.captured_at),
      stage1Label(scan),
      stage2Label(scan),
      formatConfidence(scan.stage1_confidence),
      formatConfidence(scan.stage2_confidence),
      isVoided(scan) ? `${finalGradeLabel(scan)} (voided)` : finalGradeLabel(scan),
      isVoided(scan) ? `Voided: ${scan.void_reason}` : failureReason(scan) || scan.rejection_reason || ''
    ]),
    styles: { font: 'helvetica', fontSize: 8, cellPadding: { top: 6, right: 6, bottom: 6, left: 6 }, textColor: SECONDARY, lineColor: BORDER, lineWidth: { bottom: 0.5 }, valign: 'middle' },
    headStyles: { fillColor: INK, textColor: 255, fontStyle: 'bold', fontSize: 7.5, lineWidth: 0 },
    alternateRowStyles: { fillColor: SUBTLE },
    columnStyles: { 0: { fontStyle: 'bold', textColor: INK, cellWidth: 72 }, 1: { cellWidth: 108 }, 2: { cellWidth: 78 }, 3: { cellWidth: 72 }, 4: { cellWidth: 72 }, 5: { cellWidth: 72 }, 6: { cellWidth: 96 } },
    didParseCell: data => {
      if (data.section !== 'body') return
      const scan = scans[data.row.index]
      if (isVoided(scan)) data.cell.styles.textColor = MUTED
      else if (data.column.index === 2 && !isTechnicalFailure(scan)) data.cell.styles.textColor = isHealthy(scan) ? HEALTHY : TONES.Rejected.ink
      // The grade is drawn as a pill in didDrawCell, so autoTable leaves the cell blank.
      if (data.column.index === 6) data.cell.text = []
    },
    didDrawCell: data => {
      if (data.section !== 'body' || data.column.index !== 6) return
      const label = data.cell.raw
      const tone = isVoided(scans[data.row.index]) ? VOIDED_TONE : TONES[label] || TONES['Technical failure']
      doc.setFont('helvetica', 'bold')
      doc.setFontSize(7.5)
      const width = doc.getTextWidth(label) + 12
      const x = data.cell.x + 6
      const y = data.cell.y + (data.cell.height - 13) / 2
      doc.setFillColor(...tone.soft)
      doc.setDrawColor(...tone.line)
      doc.setLineWidth(0.6)
      doc.roundedRect(x, y, width, 13, 6.5, 6.5, 'FD')
      doc.setTextColor(...tone.ink)
      doc.text(label, x + 6, y + 9.2)
    }
  })

  const pages = doc.getNumberOfPages()
  for (let page = 1; page <= pages; page++) {
    doc.setPage(page)
    drawHeader(doc, generated)
    drawFooter(doc, page, pages)
  }
  return doc
}

export function pdfFilename(date = new Date()) {
  return `banagrade-scans-${date.toISOString().slice(0, 10)}.pdf`
}

export function downloadScansPdf(scans, options = {}) {
  const generated = new Date()
  buildScansPdf(scans, { ...options, generated }).save(pdfFilename(generated))
}
