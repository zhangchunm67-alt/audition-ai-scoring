import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const code = ts.transpile(readFileSync(new URL('../src/components/reportAbilities.ts', import.meta.url), 'utf8'), { module: ts.ModuleKind.ESNext });
const { weakestItems, gradeRadius } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const item = (id, score, max, status = 'scored', dimension = 'P') => ({ item_id:id, score, max, status, dimension });
test('比较得分率，保留并列，排除其他维度、缺证据和不适用项', () => {
  assert.deepEqual(weakestItems([item('A', 5, 10), item('B', 2, 5), item('C', 4, 10), item('D',0,10,'not_applicable'),item('E',null,10,'missing_evidence'),item('F',0,10,'scored','S')], 'P').map(i=>i.item_id), ['B','C']);
});
test('全满分及无有效评分时不制造最弱项，真实零分仍参与比较', () => {
  assert.deepEqual(weakestItems([item('A',10,10),item('B',0,0),item('C',null,10)],'P'),[]);
  assert.deepEqual(weakestItems([], 'P'), []);
  assert.deepEqual(weakestItems([item('A',0,10),item('B',2,10)],'P').map(i=>i.item_id),['A']);
});
test('五轴方向一致：总档位按平均档位绘图，越低越靠外，缺失不伪造零分', () => {
  assert.equal(gradeRadius(4,true),1); assert.equal(gradeRadius(32,true),gradeRadius(8));
  assert.equal(gradeRadius(12,true),gradeRadius(3)); assert(gradeRadius(2)>gradeRadius(7));
  assert.equal(gradeRadius(null),null); assert.equal(gradeRadius(0),null);assert.equal(gradeRadius(33,true),null);
});
