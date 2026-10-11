/**
 * 案例 05 端到端验证：周期性巡航任务的「启用」列，4 个开关初始状态全部为关闭。
 *
 * 读 el-switch 的状态有个坑：aria-checked 不在 .el-switch 这个包装 div 上，
 * 而在内部的 .el-switch__input 上。
 *
 * 另一个坑：active-text / inactive-text 两个 span 始终都在 DOM 里，靠"哪个可见"判断
 * 需要用内层的 aria-hidden="false"。所以这里一律读 aria-checked。
 */
const { run } = require('../../scripts/e2e_common.cjs')

const readSwitches = page => page.evaluate(() => {
  const table = document.querySelector('.el-table')
  if (!table) return { heads: [], rows: [] }
  const heads = [...table.querySelectorAll('thead th')].map(th => th.innerText.trim())
  const rows = [...table.querySelectorAll('tbody tr')].map(tr => {
    const name = (tr.querySelector('td')?.innerText || '').trim()
    const sw = tr.querySelector('.el-switch')
    const input = sw ? sw.querySelector('.el-switch__input') : null
    return {
      name,
      checked: input ? input.getAttribute('aria-checked') : null,
      disabled: input ? input.hasAttribute('disabled') : null,
    }
  })
  return { heads, rows }
})

run({ path: '/task-scheduling/periodic-tasks', shot: 'e2e', waitMs: 3500 },
  async ({ page, ck }) => {
    console.log('\n=== 1. 列表「启用」列初始状态 ===')
    const st = await readSwitches(page)
    console.log('  表头:', JSON.stringify(st.heads))
    st.rows.forEach((r, i) =>
      console.log('  行' + (i + 1) + ': ' + JSON.stringify(r.name) + '  checked=' + r.checked))

    ck('表格有 4 行', st.rows.length === 4, st.rows.length + ' 行')
    ck('每行都能读到 el-switch 状态', st.rows.every(r => r.checked !== null))
    const off = st.rows.filter(r => r.checked === 'false').length
    const on = st.rows.filter(r => r.checked === 'true').length
    console.log('  关闭 ' + off + ' 个 / 打开 ' + on + ' 个')
    ck('4 个开关全部为未启用（aria-checked=false）', off === 4, off + '/4')
    ck('没有开关处于启用状态', on === 0, on + ' 个')

    console.log('\n=== 2. 刷新页面后仍是未启用（确认是初始数据而非交互结果）===')
    await page.reload({ waitUntil: 'networkidle' }).catch(() => {})
    await page.waitForTimeout(3000)
    const st2 = await readSwitches(page)
    const off2 = st2.rows.filter(r => r.checked === 'false').length
    ck('重载后仍全部未启用', off2 === 4, off2 + '/4')

    console.log('\n=== 3. 开关仍可交互（只是初始状态变了，不是被禁用）===')
    const firstSw = page.locator('.el-table tbody tr').first().locator('.el-switch').first()
    const before = (await readSwitches(page)).rows[0].checked
    await firstSw.click({ timeout: 5000 }).catch(() => {})
    await page.waitForTimeout(900)
    const after = (await readSwitches(page)).rows[0].checked
    console.log('  第一次点击: ' + before + ' -> ' + after)
    ck('开关可点击且状态发生翻转', before !== after, before + ' -> ' + after)
    // 翻转回来，别把线上的初始展示状态改脏
    await firstSw.click({ timeout: 5000 }).catch(() => {})
    await page.waitForTimeout(900)
    const back = (await readSwitches(page)).rows[0].checked
    ck('再次点击恢复为未启用', back === 'false', String(back))

    console.log('\n=== 4. 如实记录：新建任务弹窗的「启用状态」默认值仍是启用 ===')
    console.log('  （需求只要求改列表 4 行的初始状态，表单默认值刻意未动）')
    const newBtn = page.locator('button:has-text("新建"), button:has-text("创建任务")').first()
    if (await newBtn.count() > 0) {
      await newBtn.click().catch(() => {})
      await page.waitForTimeout(1500)
      const formSwitch = await page.evaluate(() => {
        const dlg = document.querySelector('.el-dialog, .el-drawer')
        if (!dlg) return null
        const input = dlg.querySelector('.el-switch__input')
        return input ? input.getAttribute('aria-checked') : null
      })
      console.log('  弹窗内开关 aria-checked =', formSwitch)
      ck('弹窗默认值仍为启用（与文档说明一致）', formSwitch === 'true', String(formSwitch))
      await page.keyboard.press('Escape').catch(() => {})
    } else {
      console.log('  （未找到新建按钮，跳过）')
      ck('弹窗默认值检查被跳过', true)
    }
  })
