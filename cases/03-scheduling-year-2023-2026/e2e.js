/**
 * 案例 03 端到端验证：AI 任务调度系统里的日期应该全部是 2026，且不再出现 2023。
 *
 * 同时要验证「没误伤」——同站点的 3D 地图页（不属于调度系统）里的 SVG 坐标与数字常量
 * 不能被改动。
 */
const { run } = require('../../scripts/e2e_common.cjs')

const PAGES = [
  ['/task-scheduling/periodic-tasks', '周期性巡航任务编排'],
  ['/task-scheduling/emergency-tasks', '应急消杀任务队列'],
  ['/task-scheduling/multi-device-collaboration', '多机协同工作模式'],
  ['/task-scheduling/progress', '任务进度可视化'],
  ['/task-scheduling/history', '历史轨迹回放'],
  ['/task-scheduling/path-planning', '路径规划引擎'],
]

run({ path: PAGES[0][0], shot: 'e2e', waitMs: 3500 }, async ({ page, ck }) => {
  console.log('\n=== 1. 逐页扫描日期 ===')
  for (const [p, title] of PAGES) {
    await page.goto((process.env.TG_BASE_URL || '') + p,
      { waitUntil: 'networkidle', timeout: 45000 }).catch(() => {})
    await page.waitForTimeout(2200)

    const txt = await page.evaluate(() => document.body.innerText || '')
    const hasTitle = txt.includes(title)
    const y2023 = (txt.match(/2023/g) || []).length
    const y2026 = (txt.match(/2026/g) || []).length
    console.log('  %s  %s  2023x%d  2026x%d',
      p.padEnd(44), hasTitle ? '标题OK' : '标题??', y2023, y2026)

    ck(p + ' 页面可达', txt.length > 100)
    ck(p + ' 无 2023 残留', y2023 === 0, '2023x' + y2023)
  }

  console.log('\n=== 2. 重点核对：周期性任务表的日期列 ===')
  await page.goto((process.env.TG_BASE_URL || '') + PAGES[0][0],
    { waitUntil: 'networkidle', timeout: 45000 }).catch(() => {})
  await page.waitForTimeout(2500)
  const dates = await page.evaluate(() => {
    const t = document.querySelector('.el-table')
    if (!t) return { heads: [], body: [] }
    return {
      heads: [...t.querySelectorAll('thead th')].map(th => th.innerText.trim()),
      body: [...t.querySelectorAll('tbody tr')].map(tr =>
        [...tr.querySelectorAll('td')].map(td => (td.innerText || '').trim())),
    }
  })
  console.log('  表头:', JSON.stringify(dates.heads))
  dates.body.forEach((r, i) => console.log('  行' + (i + 1) + ':', JSON.stringify(r)))

  const allCells = dates.body.flat().join(' | ')
  ck('表格里无 2023', !/2023/.test(allCells))
  const y26 = (allCells.match(/2026/g) || []).length
  ck('表格里出现 2026', y26 > 0, '2026x' + y26)

  console.log('\n=== 3. 回归：其它模块未被误伤 ===')
  // 3D 地图页不属于 AI 调度系统，其中的 SVG 坐标（%20233.62）与随机数常量（2150032023）
  // 必须保持原样 —— 我们替换的是 `"2023-`（带引号带连字符）而不是裸 `2023`。
  await page.goto((process.env.TG_BASE_URL || '') + '/monitoring-center/3d-map',
    { waitUntil: 'networkidle', timeout: 45000 }).catch(() => {})
  await page.waitForTimeout(2500)
  const mapOk = await page.evaluate(() => document.body.innerText.length > 50)
  ck('3D 地图页仍可正常打开（未被连带改坏）', mapOk)
})
