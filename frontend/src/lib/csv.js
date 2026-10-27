// CSV of exactly the rows on screen, so the CSV and the PDF always hold the same scans.

// Spreadsheets run a cell that starts with one of these as a formula; dispute reasons are typed by hand.
const FORMULA = /^[=+\-@\t\r]/

function cell(value) {
  if (value === null || value === undefined) return ''
  let text = String(value)
  if (typeof value === 'string' && FORMULA.test(text) && Number.isNaN(Number(text))) text = `'${text}`
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

export function scansCsv(scans) {
  const fields = scans.length ? Object.keys(scans[0]) : ['scan_id']
  return [fields.join(','), ...scans.map(scan => fields.map(field => cell(scan[field])).join(','))].join('\r\n') + '\r\n'
}

export function csvFilename(date = new Date()) {
  return `banagrade-scans-${date.toISOString().slice(0, 10)}.csv`
}

export function downloadScansCsv(scans) {
  // The byte-order mark makes Excel read the file as UTF-8, so "≥" and "·" survive.
  const url = URL.createObjectURL(new Blob(['﻿', scansCsv(scans)], { type: 'text/csv;charset=utf-8' }))
  const link = Object.assign(document.createElement('a'), { href: url, download: csvFilename() })
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
