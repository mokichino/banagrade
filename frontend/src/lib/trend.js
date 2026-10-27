// The rejection trend on a real clock. Buckets are placed at their start time, so a lunch break or an overnight
// stop shows as empty space instead of two distant buckets sitting side by side, and the line breaks where
// nothing was graded rather than drawing a slope through hours without data.

const MINUTE = 60_000
const DAY = 24 * 60 * MINUTE
const STEPS = [5, 10, 15, 30, 60, 120, 180, 360, 720, 1440, 2880, 10080].map(minutes => minutes * MINUTE)
const TIME = { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }
const DATE = { month: 'short', day: 'numeric' }

/** One point per bucket; a null point after any bucket whose next interval has no graded scan, which breaks the line. */
export function trendPoints(items, bucketMinutes) {
  const size = bucketMinutes * MINUTE
  const points = []
  for (const item of items) {
    const x = Date.parse(item.bucket_start)
    const last = points.at(-1)
    if (last && x - last.x > size) points.push({ x: last.x + size, y: null })
    points.push({ x, y: item.rejection_rate, total: item.total, rejected: item.rejected })
  }
  return points
}

/** A point with no line on either side; it needs a marker to be seen at all. */
export function isIsolated(points, index) {
  return points[index - 1]?.y == null && points[index + 1]?.y == null
}

/** Axis limits with half a bucket of air on each side, so the first and last markers are not cut in half. */
export function trendBounds(points, bucketMinutes) {
  const pad = (bucketMinutes * MINUTE) / 2
  return { min: points[0].x - pad, max: points.at(-1).x + pad }
}

export function tickStep(min, max, maxTicks = 7) {
  return STEPS.find(step => (max - min) / step <= maxTicks) ?? Math.ceil((max - min) / maxTicks / STEPS.at(-1)) * STEPS.at(-1)
}

/** Tick times on round local clock times (13:00, 13:15 …), not on whatever the data's first bucket happens to be. */
export function timeTicks(min, max, maxTicks = 7) {
  const step = tickStep(min, max, maxTicks)
  const local = -new Date(min).getTimezoneOffset() * MINUTE
  const ticks = []
  for (let tick = Math.ceil((min + local) / step) * step - local; tick <= max; tick += step) ticks.push(tick)
  return ticks
}

/** Clock labels for the ticks. When the axis crosses midnight, the date goes under the first tick of each day. */
export function tickLabels(ticks, step, spansDays) {
  return ticks.map((tick, index) => {
    const date = new Date(tick)
    if (step >= DAY) return date.toLocaleDateString(undefined, DATE)
    const clock = date.toLocaleTimeString(undefined, TIME)
    const newDay = index === 0 || date.toDateString() !== new Date(ticks[index - 1]).toDateString()
    return spansDays && newDay ? [clock, date.toLocaleDateString(undefined, DATE)] : clock
  })
}

/** "Oct 27, 03:30–03:45" for a bucket, or the day for 1-day buckets. */
export function bucketLabel(start, bucketMinutes) {
  const from = new Date(start)
  if (bucketMinutes >= 1440) return from.toLocaleDateString(undefined, { weekday: 'short', ...DATE })
  const to = new Date(start + bucketMinutes * MINUTE)
  return `${from.toLocaleDateString(undefined, DATE)}, ${from.toLocaleTimeString(undefined, TIME)}–${to.toLocaleTimeString(undefined, TIME)}`
}

export function intervalName(bucketMinutes) {
  if (bucketMinutes >= 1440) return 'day'
  if (bucketMinutes >= 60) return bucketMinutes === 60 ? 'hour' : `${bucketMinutes / 60} hours`
  return `${bucketMinutes} minutes`
}
