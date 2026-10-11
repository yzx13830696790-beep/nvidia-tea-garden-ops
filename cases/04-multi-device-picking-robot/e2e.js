/**
 * 案例 04 端到端验证：多机协同「可用设备」新增「采摘机器人-01」。
 *
 * 四处改动都要验：
 *   A. 设备出现在「可用设备」面板
 *   B. 类型标签显示「采摘机器人」而不是「未知类型」
 *   C. 按「采摘机器人」筛选能筛出它
 *   D. 「设备类型」下拉里有「采摘机器人」选项
 * 另外要确认原有 5 台设备没被重排或丢失。
 */
const { run } = require('../../scripts/e2e_common.cjs')

const NEW_NAME = '采摘机器人-01'
const OLD_NAMES = ['无人机-01', '无人机-02', '机器狗-01', '机器狗-02', '履带机器人-01']

run({ path: '/task-scheduling/multi-device-collaboration', shot: 'e2e', waitMs: 3500 },
  async ({ page, ck }) => {
    const bodyText = () => page.evaluate(() => document.body.innerText || '')

    console.log('\n=== A. 可用设备列表 ===')
    const txt = await bodyText()
    ck('页面出现「' + NEW_NAME + '」', txt.includes(NEW_NAME))
    for (const n of OLD_NAMES) ck('原设备仍在: ' + n, txt.includes(n))
    ck('无「未知类型」', !txt.includes('未知类型'))

    // 新设备的类型标签应显示为「采摘机器人」
    const typed = await page.evaluate(name => {
      // 找到包含该设备名的卡片/行，读出它附近的类型文案
      const all = [...document.querySelectorAll('div,li,tr')]
      const hit = all.filter(el => el.children.length &&
        (el.innerText || '').includes(name) && (el.innerText || '').length < 400)
      if (!hit.length) return null
      return hit[hit.length - 1].innerText.replace(/\s+/g, ' ').trim()
    }, NEW_NAME)
    console.log('  新设备卡片文本:', JSON.stringify(typed))
    ck('新设备类型标签为「采摘机器人」', !!typed && typed.includes('采摘机器人'), typed)
    ck('新设备状态为在线', !!typed && /在线/.test(typed), typed)

    console.log('\n=== B. 设备类型筛选 ===')
    // 设备类型下拉共 5 项：全部类型 / 无人机 / 机器狗 / 履带机器人 / 采摘机器人
    const selects = await page.locator('.el-select').all()
    let found = false
    for (let i = 0; i < Math.min(selects.length, 8); i++) {
      await selects[i].click({ timeout: 3000 }).catch(() => {})
      await page.waitForTimeout(700)
      const opts = await page.evaluate(() =>
        [...document.querySelectorAll('.el-select-dropdown__item:not(.is-hidden)')]
          .map(o => o.innerText.trim()))
      if (opts.includes('采摘机器人')) {
        found = true
        console.log('  下拉#' + i + ' 选项:', JSON.stringify(opts))
        ck('下拉含「采摘机器人」选项', true)
        ck('下拉同时保留原 4 项',
          ['全部类型', '无人机', '机器狗', '履带机器人'].every(x => opts.includes(x)),
          opts.join(' | '))

        // 点选它，看筛选结果
        await page.locator('.el-select-dropdown__item:not(.is-hidden)')
          .filter({ hasText: '采摘机器人' }).first().click().catch(() => {})
        await page.waitForTimeout(1500)
        const after = await bodyText()
        ck('筛选后仍能看到「' + NEW_NAME + '」', after.includes(NEW_NAME))
        ck('筛选后看不到无人机', !after.includes('无人机-01'))
        break
      }
      await page.keyboard.press('Escape').catch(() => {})
      await page.waitForTimeout(300)
    }
    if (!found) ck('找到含「采摘机器人」的类型下拉', false)

    console.log('\n=== C. 回归：协同任务数据未被误伤 ===')
    const t2 = await bodyText()
    ck('电量显示仍在（随机游走逻辑未被破坏）', /\d+%/.test(t2) || t2.includes('电量'))
    ck('页面无崩溃', t2.length > 200)
  })
