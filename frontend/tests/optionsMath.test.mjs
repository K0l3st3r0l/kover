import assert from 'node:assert/strict'
import { test } from 'node:test'
import fs from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
const source = fs.readFileSync(new URL('../src/utils/optionsMath.ts', import.meta.url), 'utf8')
const sandbox = { exports: {} }
vm.runInNewContext(ts.transpile(source, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }), sandbox)
const { calcBrokerOption: calc, rollCost } = sandbox.exports
const now = new Date(2026, 8, 12)
const row = { id: 1, side: 'sell', type: 'call', strike: '22', premium: '1', contracts: '1', expiration: '2026-10-12' }
const run = (changes = {}, fee = 0) => calc({ ...row, ...changes }, 20, 20, fee, now)
test('premium ROI does not change with contract count or proportional fees', () => {
  assert.equal(run().roiPct, 5)
  assert.equal(run({ contracts: '2' }).roiPct, 5)
  assert.equal(run({}, .65).roiPct, run({ contracts: '2' }, .65).roiPct)
  assert.equal(run({ type: 'put' }, .65).roiPct, run({ type: 'put', contracts: '2' }, .65).roiPct)
})
test('covered call maximum includes the stock payoff', () => {
  assert.equal(run().maxProfit, 300)
  assert.equal(run({ contracts: '2' }).maxProfit, 600)
  assert.equal(run({ strike: '18' }).maxProfit, -100)
  assert.equal(run({}, .65).breakeven, 19.0065)
  assert.equal(run({}, .65).maxLoss, 1900.65)
})
test('long option spot scenario uses premium capital and cannot win a live ranking', () => {
  const call = calc({ ...row, side: 'buy', strike: '20', premium: '2' }, 25, 25, 0, now)
  assert.equal(call.roiPct, 150)
  assert.equal(call.score, -Infinity)
  assert.equal(run({ side:'buy', strike:'30', premium:'2' }).roiPct, -100)
})
test('invalid contracts, negative prices and past expiries have no result', () => {
  for (const contracts of ['0', '-1', '1.5', '', 'x']) assert.equal(run({ contracts }), null)
  assert.equal(run({ premium: '-1' }), null)
  assert.equal(run({ expiration: '2026-09-11' }), null)
  assert.equal(run({ expiration: 'nonsense' }), null)
})
test('roll needs a current closing quote; zero is valid and both legs include fees', () => {
  assert.equal(rollCost('', 2, .65), null)
  assert.equal(rollCost('-1', 2, .65), null)
  assert.equal(rollCost('0', 2, .65), 1.3)
  assert.equal(rollCost('.4', 2, .65), 81.3)
  assert.ok(Math.abs(run({ premium:'.8', contracts:'2' }, .65).totalCashFlow - rollCost('.4',2,.65) - 77.4) < 1e-8)
})
test('a roll realizes the original premium less the buyback into the next stock basis', () => {
  assert.equal(sandbox.exports.rolledCostBasis(20, 1, 2, 80, 200), 19.4)
  assert.equal(sandbox.exports.rolledCostBasis(20, 1, 2, 80, 400), 19.7)
})
